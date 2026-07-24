"""Typed domain failures safe for application-layer mapping."""


class HotelDomainError(ValueError):
    """Base class carrying a stable machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidStay(HotelDomainError):
    pass


class OccupancyNotSupported(HotelDomainError):
    pass


class BookingNotFound(HotelDomainError):
    pass


class VerificationFailed(HotelDomainError):
    pass


class RoomNotFound(HotelDomainError):
    pass


class InvalidServiceRequest(HotelDomainError):
    pass


class IdempotencyConflict(HotelDomainError):
    pass


class ServiceRequestNotFound(HotelDomainError):
    pass


class InvalidStatusTransition(HotelDomainError):
    pass
