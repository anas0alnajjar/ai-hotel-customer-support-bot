"""Verification hashing behavior for simulated bookings."""

from hotel_bot.domain.hotel.security import (
    deterministic_seed_salt,
    hash_verification_value,
    verify_verification_value,
)


def test_booking_verification_hash_is_deterministic_for_seed_and_constant_time_verifiable() -> None:
    salt = deterministic_seed_salt("BKG-2026-0001")
    encoded = hash_verification_value(" 01  01 ", salt=salt)

    assert encoded.startswith("pbkdf2_sha256$")
    assert "0101" not in encoded
    assert verify_verification_value("01 01", encoded) is True
    assert verify_verification_value("9999", encoded) is False


def test_malformed_booking_hash_fails_closed() -> None:
    assert verify_verification_value("0101", "not-a-valid-hash") is False
