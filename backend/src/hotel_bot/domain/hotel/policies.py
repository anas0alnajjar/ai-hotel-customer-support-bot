"""Pure hotel inventory and service-request business rules."""

import re
from collections import Counter
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.errors import (
    IdempotencyConflict,
    InvalidServiceRequest,
    InvalidStatusTransition,
    InvalidStay,
)
from hotel_bot.domain.hotel.models import (
    AvailabilityOption,
    AvailabilityResult,
    InventorySnapshot,
    NewServiceRequest,
    ServiceRequestSnapshot,
)

MAX_STAY_NIGHTS = 30
MAX_ADVANCE_DAYS = 365
INVENTORY_HOLDING_STATUSES = {
    BookingStatus.PENDING,
    BookingStatus.CONFIRMED,
    BookingStatus.CHECKED_IN,
}
SERVICE_CATEGORIES = {
    ServiceRequestType.ROOM_SERVICE: {
        "food_and_beverage",
        "housekeeping",
        "amenities",
        "laundry",
    },
    ServiceRequestType.MAINTENANCE: {
        "plumbing",
        "electrical",
        "hvac",
        "appliance",
        "furniture",
        "safety",
    },
}
SERVICE_CATEGORY_KEYWORDS: dict[
    ServiceRequestType,
    dict[str, tuple[str, ...]],
] = {
    ServiceRequestType.ROOM_SERVICE: {
        "food_and_beverage": (
            "food",
            "meal",
            "dinner",
            "breakfast",
            "طعام",
            "أكل",
            "اكل",
            "وجبة",
            "غداء",
            "عشاء",
            "فطور",
            "مشروب",
        ),
        "housekeeping": (
            "clean",
            "cleaning",
            "housekeeping",
            "تنظيف",
        ),
        "amenities": (
            "towel",
            "blanket",
            "pillow",
            "منشف",
            "بطاني",
            "وساد",
        ),
        "laundry": (
            "laundry",
            "washing",
            "ملابس",
            "غسيل",
        ),
    },
    ServiceRequestType.MAINTENANCE: {
        "hvac": (
            "مكيف",
            "التكييف",
            "تكييف",
            "تبريد",
            "air conditioner",
            "air conditioning",
            "ac",
            "hvac",
        ),
        "plumbing": (
            "تسريب",
            "مياه",
            "حنفية",
            "مرحاض",
            "مغسلة",
            "دوش",
            "صرف",
            "plumbing",
            "leak",
            "water",
            "toilet",
            "sink",
            "shower",
            "drain",
        ),
        "electrical": (
            "كهرباء",
            "كهربائي",
            "مقبس",
            "فيشة",
            "إنارة",
            "ضوء",
            "مصباح",
            "electric",
            "electrical",
            "socket",
            "outlet",
            "light",
            "lamp",
        ),
        "appliance": (
            "تلفاز",
            "تلفزيون",
            "ثلاجة",
            "غلاية",
            "مجفف",
            "جهاز",
            "tv",
            "television",
            "fridge",
            "refrigerator",
            "kettle",
            "dryer",
            "appliance",
        ),
        "furniture": (
            "سرير",
            "كرسي",
            "طاولة",
            "خزانة",
            "باب",
            "نافذة",
            "bed",
            "chair",
            "table",
            "wardrobe",
            "door",
            "window",
            "furniture",
        ),
        "safety": (
            "دخان",
            "حريق",
            "غاز",
            "شرر",
            "خطر",
            "smoke",
            "fire",
            "gas",
            "spark",
            "danger",
            "safety",
        ),
    },
}
ALLOWED_STATUS_TRANSITIONS = {
    ServiceRequestStatus.OPEN: {
        ServiceRequestStatus.ACKNOWLEDGED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.ACKNOWLEDGED: {
        ServiceRequestStatus.IN_PROGRESS,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.IN_PROGRESS: {
        ServiceRequestStatus.COMPLETED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.COMPLETED: set(),
    ServiceRequestStatus.CANCELLED: set(),
}


def validate_stay(
    check_in: date,
    check_out: date,
    adults: int,
    children: int,
    *,
    today: date,
) -> None:
    if check_in < today:
        raise InvalidStay("check_in_in_past", "check-in cannot be in the past")
    if check_out <= check_in:
        raise InvalidStay("invalid_date_range", "check-out must be after check-in")
    if (check_out - check_in).days > MAX_STAY_NIGHTS:
        raise InvalidStay("stay_too_long", f"stay cannot exceed {MAX_STAY_NIGHTS} nights")
    if (check_in - today).days > MAX_ADVANCE_DAYS:
        raise InvalidStay(
            "check_in_too_far", f"check-in cannot exceed {MAX_ADVANCE_DAYS} days in advance"
        )
    if adults < 1:
        raise InvalidStay("adults_required", "at least one adult is required")
    if children < 0:
        raise InvalidStay("invalid_children", "children cannot be negative")


def stays_overlap(
    existing_check_in: date,
    existing_check_out: date,
    requested_check_in: date,
    requested_check_out: date,
) -> bool:
    """Use half-open stays so same-day check-out/check-in does not overlap."""

    return existing_check_in < requested_check_out and existing_check_out > requested_check_in


def calculate_availability(
    inventory: InventorySnapshot,
    *,
    check_in: date,
    check_out: date,
    adults: int,
    children: int,
    today: date,
    room_type_code: str | None = None,
) -> AvailabilityResult:
    validate_stay(check_in, check_out, adults, children, today=today)
    normalized_code = room_type_code.strip().lower() if room_type_code else None

    blocked_room_ids: set[UUID] = set()
    unassigned_holds: Counter[UUID] = Counter()
    for booking in inventory.overlapping_bookings:
        if booking.status not in INVENTORY_HOLDING_STATUSES:
            continue
        if not stays_overlap(booking.check_in, booking.check_out, check_in, check_out):
            continue
        if booking.room_id is None:
            unassigned_holds[booking.room_type_id] += 1
        else:
            blocked_room_ids.add(booking.room_id)

    available_by_type: Counter[UUID] = Counter()
    for room in inventory.rooms:
        if room.operational_status is not RoomOperationalStatus.AVAILABLE:
            continue
        if room.id not in blocked_room_ids:
            available_by_type[room.room_type_id] += 1

    options: list[AvailabilityOption] = []
    for room_type in sorted(inventory.room_types, key=lambda item: item.code):
        if not room_type.active:
            continue
        if normalized_code and room_type.code.lower() != normalized_code:
            continue
        if adults > room_type.capacity_adults or children > room_type.capacity_children:
            continue
        count = max(0, available_by_type[room_type.id] - unassigned_holds[room_type.id])
        if count:
            options.append(
                AvailabilityOption(
                    room_type_code=room_type.code,
                    names=room_type.names,
                    capacity_adults=room_type.capacity_adults,
                    capacity_children=room_type.capacity_children,
                    available_rooms=count,
                    amenities=room_type.amenities,
                )
            )

    return AvailabilityResult(
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        children=children,
        options=tuple(options),
    )


def normalize_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 16 <= len(normalized) <= 128:
        raise InvalidServiceRequest(
            "invalid_idempotency_key", "idempotency key must contain 16 to 128 characters"
        )
    return normalized


def normalize_service_description(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not 10 <= len(normalized) <= 1000:
        raise InvalidServiceRequest(
            "invalid_description", "description must contain 10 to 1000 characters"
        )
    return normalized


def validate_service_category(request_type: ServiceRequestType, category: str) -> str:
    normalized = category.strip().lower()
    if normalized not in SERVICE_CATEGORIES[request_type]:
        raise InvalidServiceRequest(
            "invalid_category", f"category is not allowed for {request_type.value}"
        )
    return normalized


def resolve_service_category(
    request_type: ServiceRequestType,
    category: str,
    description: str,
) -> str | None:
    """Return an allowed category or infer one deterministically from the issue text."""

    normalized_category = category.strip().casefold()
    allowed = SERVICE_CATEGORIES[request_type]
    if normalized_category in allowed:
        return normalized_category

    searchable = " ".join((normalized_category, description.casefold()))
    for resolved, keywords in SERVICE_CATEGORY_KEYWORDS[request_type].items():
        if resolved not in allowed:
            continue
        if any(_contains_category_keyword(searchable, keyword) for keyword in keywords):
            return resolved
    return None


def _contains_category_keyword(text: str, keyword: str) -> bool:
    if keyword.isascii() and " " not in keyword:
        return re.search(
            rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])",
            text,
        ) is not None
    return keyword in text


def build_new_service_request(
    *,
    request_type: ServiceRequestType,
    category: str,
    room_id: UUID,
    booking_id: UUID | None,
    requested_by_guest_id: UUID | None,
    description: str,
    urgency: Urgency,
    idempotency_key: str,
) -> NewServiceRequest:
    normalized_key = normalize_idempotency_key(idempotency_key)
    normalized_category = validate_service_category(request_type, category)
    normalized_description = normalize_service_description(description)
    stable_id = uuid5(NAMESPACE_URL, f"nour-al-sham:service-request:{normalized_key}")
    tracking_code = f"SR-{stable_id.hex[:12].upper()}"
    return NewServiceRequest(
        id=stable_id,
        tracking_code=tracking_code,
        request_type=request_type,
        category=normalized_category,
        room_id=room_id,
        booking_id=booking_id,
        requested_by_guest_id=requested_by_guest_id,
        description=normalized_description,
        urgency=urgency,
        idempotency_key=normalized_key,
    )


def assert_idempotent_payload_matches(
    existing: ServiceRequestSnapshot, requested: NewServiceRequest
) -> None:
    comparable_existing = (
        existing.request_type,
        existing.category,
        existing.room_id,
        existing.booking_id,
        existing.requested_by_guest_id,
        existing.description,
        existing.urgency,
    )
    comparable_requested = (
        requested.request_type,
        requested.category,
        requested.room_id,
        requested.booking_id,
        requested.requested_by_guest_id,
        requested.description,
        requested.urgency,
    )
    if comparable_existing != comparable_requested:
        raise IdempotencyConflict(
            "idempotency_payload_mismatch",
            "the idempotency key was already used with different request data",
        )


def requires_immediate_contact(request: ServiceRequestSnapshot | NewServiceRequest) -> bool:
    return request.urgency is Urgency.EMERGENCY or (
        request.request_type is ServiceRequestType.MAINTENANCE and request.category == "safety"
    )


def validate_status_transition(current: ServiceRequestStatus, target: ServiceRequestStatus) -> None:
    if target not in ALLOWED_STATUS_TRANSITIONS[current]:
        raise InvalidStatusTransition(
            "invalid_status_transition", f"cannot transition from {current.value} to {target.value}"
        )
