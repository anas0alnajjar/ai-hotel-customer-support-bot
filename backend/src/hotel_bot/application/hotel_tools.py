"""Strict schemas and handlers for the six simulated hotel tools."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, model_validator

from hotel_bot.domain.hotel.enums import ServiceRequestType, Urgency
from hotel_bot.domain.hotel.models import (
    AvailabilityResult,
    BookingSummary,
    RoomTypeSnapshot,
    ServiceRequestCreationResult,
    ServiceRequestSnapshot,
)
from hotel_bot.domain.tools.enums import ToolCaller, ToolEffect
from hotel_bot.domain.tools.models import RegisteredTool
from hotel_bot.domain.tools.registry import ToolDefinition, ToolRegistry

ToolHandler = Callable[[BaseModel], Awaitable[BaseModel]]
SecretValue = Annotated[SecretStr, Field(min_length=1, max_length=128)]


class HotelToolService(Protocol):
    async def list_room_types(self) -> tuple[RoomTypeSnapshot, ...]: ...

    async def check_availability(
        self,
        *,
        check_in: date,
        check_out: date,
        adults: int,
        children: int = 0,
        room_type_code: str | None = None,
    ) -> AvailabilityResult: ...

    async def lookup_booking(
        self, booking_reference: str, verification_value: str
    ) -> BookingSummary: ...

    async def create_service_request(
        self,
        *,
        request_type: ServiceRequestType,
        category: str,
        room_number: str,
        description: str,
        urgency: Urgency,
        idempotency_key: str,
        booking_reference: str | None = None,
        verification_value: str | None = None,
    ) -> ServiceRequestCreationResult: ...

    async def get_service_request_status(
        self, tracking_code: str, verification_value: str
    ) -> ServiceRequestSnapshot: ...


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolOutput(BaseModel):
    model_config = ConfigDict(frozen=True)


class ListRoomTypesInput(ToolInput):
    pass


class RoomTypeItem(ToolOutput):
    code: str
    name_ar: str
    name_en: str
    description_ar: str
    description_en: str
    capacity_adults: int
    capacity_children: int
    amenities: tuple[str, ...]


class RoomTypesOutput(ToolOutput):
    room_types: tuple[RoomTypeItem, ...]
    simulation: bool = True


class AvailabilityInput(ToolInput):
    check_in: date
    check_out: date
    adults: Annotated[StrictInt, Field(ge=1, le=10)]
    children: Annotated[StrictInt, Field(ge=0, le=10)] = 0
    room_type_code: Annotated[str, Field(pattern=r"^[a-z0-9_]{3,32}$")] | None = None


class AvailabilityOptionOutput(ToolOutput):
    room_type_code: str
    name_ar: str
    name_en: str
    capacity_adults: int
    capacity_children: int
    available_rooms: int
    amenities: tuple[str, ...]


class AvailabilityOutput(ToolOutput):
    check_in: date
    check_out: date
    adults: int
    children: int
    options: tuple[AvailabilityOptionOutput, ...]
    simulation: bool = True


class BookingLookupInput(ToolInput):
    booking_reference: Annotated[str, Field(min_length=6, max_length=32, pattern=r"^[\w-]+$")]
    verification_value: SecretValue


class BookingLookupOutput(ToolOutput):
    reference: str
    guest_name_masked: str
    check_in: date
    check_out: date
    room_type_code: str
    room_number: str | None
    adults: int
    children: int
    status: str
    simulation: bool = True


class ServiceRequestInput(ToolInput):
    category: Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z_]+$")]
    room_number: Annotated[str, Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")]
    description: Annotated[str, Field(min_length=10, max_length=1000)]
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]
    booking_reference: (
        Annotated[str, Field(min_length=6, max_length=32, pattern=r"^[\w-]+$")] | None
    ) = None
    verification_value: SecretValue | None = None

    @model_validator(mode="after")
    def validate_optional_verification_pair(self) -> Self:
        if (self.booking_reference is None) != (self.verification_value is None):
            raise ValueError("booking_reference and verification_value must be supplied together")
        return self


class RoomServiceRequestInput(ServiceRequestInput):
    urgency: Literal[Urgency.NORMAL, Urgency.HIGH] = Urgency.NORMAL


class MaintenanceRequestInput(ServiceRequestInput):
    urgency: Urgency = Urgency.NORMAL


class ServiceRequestCreatedOutput(ToolOutput):
    tracking_code: str
    request_type: str
    category: str
    urgency: str
    status: str
    created: bool
    requires_immediate_contact: bool
    emergency_guidance_code: str | None
    simulation: bool = True


class ServiceRequestStatusInput(ToolInput):
    tracking_code: Annotated[str, Field(min_length=6, max_length=32, pattern=r"^[A-Za-z0-9-]+$")]
    verification_value: SecretValue


class ServiceRequestStatusOutput(ToolOutput):
    tracking_code: str
    request_type: str
    category: str
    urgency: str
    status: str
    simulation: bool = True


def _typed[InputT: BaseModel](arguments: BaseModel, expected: type[InputT]) -> InputT:
    if not isinstance(arguments, expected):
        raise TypeError("tool input contract mismatch")
    return arguments


def build_hotel_tool_registry(
    service: HotelToolService,
    *,
    read_timeout_ms: int = 2_000,
    write_timeout_ms: int = 5_000,
) -> ToolRegistry:
    """Build the closed guest-assistant registry; no arbitrary dynamic tools are accepted."""

    async def list_room_types(arguments: BaseModel) -> BaseModel:
        _typed(arguments, ListRoomTypesInput)
        room_types = await service.list_room_types()
        return RoomTypesOutput(
            room_types=tuple(
                RoomTypeItem(
                    code=item.code,
                    name_ar=item.names["ar"],
                    name_en=item.names["en"],
                    description_ar=item.descriptions["ar"],
                    description_en=item.descriptions["en"],
                    capacity_adults=item.capacity_adults,
                    capacity_children=item.capacity_children,
                    amenities=item.amenities,
                )
                for item in room_types
            )
        )

    async def check_availability(arguments: BaseModel) -> BaseModel:
        values = _typed(arguments, AvailabilityInput)
        result = await service.check_availability(
            check_in=values.check_in,
            check_out=values.check_out,
            adults=values.adults,
            children=values.children,
            room_type_code=values.room_type_code,
        )
        return AvailabilityOutput(
            check_in=result.check_in,
            check_out=result.check_out,
            adults=result.adults,
            children=result.children,
            options=tuple(
                AvailabilityOptionOutput(
                    room_type_code=item.room_type_code,
                    name_ar=item.names["ar"],
                    name_en=item.names["en"],
                    capacity_adults=item.capacity_adults,
                    capacity_children=item.capacity_children,
                    available_rooms=item.available_rooms,
                    amenities=item.amenities,
                )
                for item in result.options
            ),
        )

    async def lookup_booking(arguments: BaseModel) -> BaseModel:
        values = _typed(arguments, BookingLookupInput)
        result = await service.lookup_booking(
            values.booking_reference, values.verification_value.get_secret_value()
        )
        return BookingLookupOutput(
            reference=result.reference,
            guest_name_masked=result.guest_name_masked,
            check_in=result.check_in,
            check_out=result.check_out,
            room_type_code=result.room_type_code,
            room_number=result.room_number,
            adults=result.adults,
            children=result.children,
            status=result.status.value,
        )

    def create_request_handler(
        request_type: ServiceRequestType,
        input_model: type[ServiceRequestInput],
    ) -> ToolHandler:
        async def create_request(arguments: BaseModel) -> BaseModel:
            values = cast(
                RoomServiceRequestInput | MaintenanceRequestInput,
                _typed(arguments, input_model),
            )
            result = await service.create_service_request(
                request_type=request_type,
                category=values.category,
                room_number=values.room_number,
                description=values.description,
                urgency=values.urgency,
                idempotency_key=values.idempotency_key,
                booking_reference=values.booking_reference,
                verification_value=(
                    values.verification_value.get_secret_value()
                    if values.verification_value
                    else None
                ),
            )
            return ServiceRequestCreatedOutput(
                tracking_code=result.request.tracking_code,
                request_type=result.request.request_type.value,
                category=result.request.category,
                urgency=result.request.urgency.value,
                status=result.request.status.value,
                created=result.created,
                requires_immediate_contact=result.requires_immediate_contact,
                emergency_guidance_code=result.emergency_guidance_code,
            )

        return create_request

    async def get_request_status(arguments: BaseModel) -> BaseModel:
        values = _typed(arguments, ServiceRequestStatusInput)
        result = await service.get_service_request_status(
            values.tracking_code, values.verification_value.get_secret_value()
        )
        return ServiceRequestStatusOutput(
            tracking_code=result.tracking_code,
            request_type=result.request_type.value,
            category=result.category,
            urgency=result.urgency.value,
            status=result.status.value,
        )

    allowed = frozenset({ToolCaller.ASSISTANT})
    return ToolRegistry(
        (
            RegisteredTool(
                ToolDefinition(
                    name="list_room_types",
                    description=(
                        "List active room types and approved public attributes from hotel data."
                    ),
                    input_model=ListRoomTypesInput,
                    output_model=RoomTypesOutput,
                    allowed_callers=allowed,
                    timeout_ms=read_timeout_ms,
                    effect=ToolEffect.READ,
                    requires_confirmation=False,
                ),
                list_room_types,
            ),
            RegisteredTool(
                ToolDefinition(
                    name="check_room_availability",
                    description="Check simulated room inventory for validated dates and occupancy.",
                    input_model=AvailabilityInput,
                    output_model=AvailabilityOutput,
                    allowed_callers=allowed,
                    timeout_ms=read_timeout_ms,
                    effect=ToolEffect.READ,
                    requires_confirmation=False,
                ),
                check_availability,
            ),
            RegisteredTool(
                ToolDefinition(
                    name="lookup_booking",
                    description=(
                        "Return minimal simulated booking data after secondary verification."
                    ),
                    input_model=BookingLookupInput,
                    output_model=BookingLookupOutput,
                    allowed_callers=allowed,
                    timeout_ms=read_timeout_ms,
                    effect=ToolEffect.READ,
                    requires_confirmation=False,
                    sensitive_argument_fields=frozenset(
                        {"booking_reference", "verification_value"}
                    ),
                    sensitive_result_fields=frozenset({"reference", "room_number"}),
                ),
                lookup_booking,
            ),
            RegisteredTool(
                ToolDefinition(
                    name="create_room_service_request",
                    description=(
                        "Create one idempotent simulated room-service request after confirmation."
                    ),
                    input_model=RoomServiceRequestInput,
                    output_model=ServiceRequestCreatedOutput,
                    allowed_callers=allowed,
                    timeout_ms=write_timeout_ms,
                    effect=ToolEffect.WRITE,
                    requires_confirmation=True,
                    sensitive_argument_fields=frozenset(
                        {
                            "room_number",
                            "description",
                            "idempotency_key",
                            "booking_reference",
                            "verification_value",
                        }
                    ),
                ),
                create_request_handler(ServiceRequestType.ROOM_SERVICE, RoomServiceRequestInput),
            ),
            RegisteredTool(
                ToolDefinition(
                    name="create_maintenance_request",
                    description=(
                        "Create one idempotent simulated maintenance request after confirmation."
                    ),
                    input_model=MaintenanceRequestInput,
                    output_model=ServiceRequestCreatedOutput,
                    allowed_callers=allowed,
                    timeout_ms=write_timeout_ms,
                    effect=ToolEffect.WRITE,
                    requires_confirmation=True,
                    sensitive_argument_fields=frozenset(
                        {
                            "room_number",
                            "description",
                            "idempotency_key",
                            "booking_reference",
                            "verification_value",
                        }
                    ),
                ),
                create_request_handler(ServiceRequestType.MAINTENANCE, MaintenanceRequestInput),
            ),
            RegisteredTool(
                ToolDefinition(
                    name="get_service_request_status",
                    description=(
                        "Return minimal simulated service-request status after verification."
                    ),
                    input_model=ServiceRequestStatusInput,
                    output_model=ServiceRequestStatusOutput,
                    allowed_callers=allowed,
                    timeout_ms=read_timeout_ms,
                    effect=ToolEffect.READ,
                    requires_confirmation=False,
                    sensitive_argument_fields=frozenset({"verification_value"}),
                ),
                get_request_status,
            ),
        )
    )
