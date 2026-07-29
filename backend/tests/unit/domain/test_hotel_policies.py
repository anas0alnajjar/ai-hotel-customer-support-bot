"""Pure business-rule tests for simulated hotel operations."""

from datetime import date
from uuid import uuid4

import pytest

from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.errors import (
    IdempotencyConflict,
    InvalidStatusTransition,
    InvalidStay,
)
from hotel_bot.domain.hotel.models import (
    BookingSnapshot,
    InventorySnapshot,
    RoomSnapshot,
    RoomTypeSnapshot,
    ServiceRequestSnapshot,
)
from hotel_bot.domain.hotel.policies import (
    assert_idempotent_payload_matches,
    build_new_service_request,
    calculate_availability,
    requires_immediate_contact,
    resolve_service_category,
    stays_overlap,
    validate_status_transition,
    validate_stay,
)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("المكيف لا يعمل والتبريد متوقف", "hvac"),
        ("There is a water leak under the sink", "plumbing"),
        ("The electrical outlet has no power", "electrical"),
        ("The room television is broken", "appliance"),
        ("The wardrobe door is damaged", "furniture"),
        ("There is smoke and a gas danger", "safety"),
    ],
)
def test_maintenance_category_resolution_uses_domain_allow_list(
    description: str,
    expected: str,
) -> None:
    assert (
        resolve_service_category(
            ServiceRequestType.MAINTENANCE,
            "general",
            description,
        )
        == expected
    )


@pytest.mark.parametrize(
    "description",
    [
        "أريد طعاماً للغرفة",
        "أريد أكل",
        "أريد وجبة غداء",
        "أريد فطور",
        "أريد عشاء",
        "أريد مشروبات",
    ],
)
def test_room_service_food_expressions_resolve_to_food_and_beverage(
    description: str,
) -> None:
    assert (
        resolve_service_category(
            ServiceRequestType.ROOM_SERVICE,
            "general",
            description,
        )
        == "food_and_beverage"
    )


def test_category_resolution_preserves_valid_values_and_rejects_unknown_issues() -> None:
    assert (
        resolve_service_category(
            ServiceRequestType.MAINTENANCE,
            "hvac",
            "Unstructured issue",
        )
        == "hvac"
    )
    assert (
        resolve_service_category(
            ServiceRequestType.MAINTENANCE,
            "general",
            "Something in the room is not right",
        )
        is None
    )
    assert (
        resolve_service_category(
            ServiceRequestType.ROOM_SERVICE,
            "food",
            "Please send breakfast to the room",
        )
        == "food_and_beverage"
    )


def build_inventory() -> tuple[InventorySnapshot, str]:
    standard_id = uuid4()
    family_id = uuid4()
    standard_rooms = [
        RoomSnapshot(uuid4(), str(101 + index), standard_id, RoomOperationalStatus.AVAILABLE)
        for index in range(3)
    ]
    maintenance_room = RoomSnapshot(uuid4(), "199", standard_id, RoomOperationalStatus.MAINTENANCE)
    family_room = RoomSnapshot(uuid4(), "301", family_id, RoomOperationalStatus.AVAILABLE)
    bookings = (
        BookingSnapshot(
            uuid4(),
            "BKG-ASSIGNED",
            "hash",
            "A***",
            date(2026, 8, 1),
            date(2026, 8, 5),
            standard_id,
            standard_rooms[0].id,
            2,
            0,
            BookingStatus.CONFIRMED,
        ),
        BookingSnapshot(
            uuid4(),
            "BKG-UNASSIGNED",
            "hash",
            "B***",
            date(2026, 8, 2),
            date(2026, 8, 6),
            standard_id,
            None,
            2,
            0,
            BookingStatus.PENDING,
        ),
        BookingSnapshot(
            uuid4(),
            "BKG-CANCELLED",
            "hash",
            "C***",
            date(2026, 8, 1),
            date(2026, 8, 5),
            standard_id,
            standard_rooms[1].id,
            2,
            0,
            BookingStatus.CANCELLED,
        ),
    )
    inventory = InventorySnapshot(
        room_types=(
            RoomTypeSnapshot(
                standard_id,
                "standard",
                {"ar": "قياسية", "en": "Standard"},
                {"ar": "غرفة", "en": "Room"},
                2,
                1,
                ("wifi",),
                True,
            ),
            RoomTypeSnapshot(
                family_id,
                "family",
                {"ar": "عائلية", "en": "Family"},
                {"ar": "جناح", "en": "Suite"},
                4,
                2,
                ("wifi", "kitchenette"),
                True,
            ),
        ),
        rooms=tuple([*standard_rooms, maintenance_room, family_room]),
        overlapping_bookings=bookings,
    )
    return inventory, "standard"


def test_availability_counts_assigned_and_unassigned_holds() -> None:
    inventory, standard_code = build_inventory()

    result = calculate_availability(
        inventory,
        check_in=date(2026, 8, 2),
        check_out=date(2026, 8, 4),
        adults=2,
        children=0,
        today=date(2026, 7, 13),
        room_type_code=standard_code,
    )

    assert len(result.options) == 1
    assert result.options[0].available_rooms == 1
    assert result.simulation is True


def test_availability_filters_room_types_by_occupancy() -> None:
    inventory, _ = build_inventory()

    result = calculate_availability(
        inventory,
        check_in=date(2026, 8, 7),
        check_out=date(2026, 8, 9),
        adults=4,
        children=2,
        today=date(2026, 7, 13),
    )

    assert [option.room_type_code for option in result.options] == ["family"]


def test_same_day_turnover_does_not_overlap() -> None:
    assert not stays_overlap(
        date(2026, 8, 1),
        date(2026, 8, 5),
        date(2026, 8, 5),
        date(2026, 8, 7),
    )


@pytest.mark.parametrize(
    ("check_in", "check_out", "adults", "children", "code"),
    [
        (date(2026, 7, 12), date(2026, 7, 14), 1, 0, "check_in_in_past"),
        (date(2026, 7, 14), date(2026, 7, 14), 1, 0, "invalid_date_range"),
        (date(2026, 7, 14), date(2026, 8, 14), 1, 0, "stay_too_long"),
        (date(2026, 7, 14), date(2026, 7, 15), 0, 0, "adults_required"),
        (date(2026, 7, 14), date(2026, 7, 15), 1, -1, "invalid_children"),
    ],
)
def test_invalid_stay_inputs_are_rejected(
    check_in: date, check_out: date, adults: int, children: int, code: str
) -> None:
    with pytest.raises(InvalidStay) as error:
        validate_stay(check_in, check_out, adults, children, today=date(2026, 7, 13))
    assert error.value.code == code


def test_idempotency_builds_stable_identity_and_rejects_payload_changes() -> None:
    room_id = uuid4()
    first = build_new_service_request(
        request_type=ServiceRequestType.ROOM_SERVICE,
        category="amenities",
        room_id=room_id,
        booking_id=None,
        requested_by_guest_id=None,
        description="Please deliver two extra towels.",
        urgency=Urgency.NORMAL,
        idempotency_key="telegram-update-123456",
    )
    retry = build_new_service_request(
        request_type=ServiceRequestType.ROOM_SERVICE,
        category="amenities",
        room_id=room_id,
        booking_id=None,
        requested_by_guest_id=None,
        description="Please deliver two extra towels.",
        urgency=Urgency.NORMAL,
        idempotency_key="telegram-update-123456",
    )
    assert first.id == retry.id
    assert first.tracking_code == retry.tracking_code

    stored = ServiceRequestSnapshot(
        id=first.id,
        tracking_code=first.tracking_code,
        request_type=first.request_type,
        category=first.category,
        room_id=first.room_id,
        booking_id=None,
        requested_by_guest_id=None,
        description="Different request details",
        urgency=first.urgency,
        status=ServiceRequestStatus.OPEN,
        idempotency_key=first.idempotency_key,
    )
    with pytest.raises(IdempotencyConflict):
        assert_idempotent_payload_matches(stored, retry)


def test_emergency_policy_never_implies_resolution() -> None:
    request = build_new_service_request(
        request_type=ServiceRequestType.MAINTENANCE,
        category="safety",
        room_id=uuid4(),
        booking_id=None,
        requested_by_guest_id=None,
        description="There is a simulated smoke alarm warning.",
        urgency=Urgency.EMERGENCY,
        idempotency_key="emergency-test-1234",
    )
    assert requires_immediate_contact(request) is True


def test_service_request_status_machine_rejects_skipped_and_terminal_transitions() -> None:
    validate_status_transition(ServiceRequestStatus.OPEN, ServiceRequestStatus.ACKNOWLEDGED)
    with pytest.raises(InvalidStatusTransition):
        validate_status_transition(ServiceRequestStatus.OPEN, ServiceRequestStatus.COMPLETED)
    with pytest.raises(InvalidStatusTransition):
        validate_status_transition(ServiceRequestStatus.COMPLETED, ServiceRequestStatus.OPEN)
