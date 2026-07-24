"""Privacy-preserving verification helpers for simulated bookings."""

import base64
import hashlib
import hmac

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 210_000


def normalize_verification_value(value: str) -> str:
    """Normalize user-provided verification text before hashing."""

    return " ".join(value.strip().casefold().split())


def deterministic_seed_salt(booking_reference: str) -> bytes:
    """Return a reproducible salt used only for committed synthetic seed records."""

    material = f"nour-al-sham-seed-v1:{booking_reference.upper()}".encode()
    return hashlib.sha256(material).digest()[:16]


def hash_verification_value(value: str, *, salt: bytes) -> str:
    normalized = normalize_verification_value(value).encode()
    digest = hashlib.pbkdf2_hmac("sha256", normalized, salt, ITERATIONS)
    salt_text = base64.urlsafe_b64encode(salt).decode().rstrip("=")
    digest_text = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"{ALGORITHM}${ITERATIONS}${salt_text}${digest_text}"


def verify_verification_value(value: str, encoded_hash: str) -> bool:
    """Verify without exposing the stored or supplied verification value."""

    try:
        algorithm, iterations_text, salt_text, expected_text = encoded_hash.split("$", 3)
        if algorithm != ALGORITHM or int(iterations_text) != ITERATIONS:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(expected_text + "=" * (-len(expected_text) % 4))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256", normalize_verification_value(value).encode(), salt, ITERATIONS
    )
    return hmac.compare_digest(actual, expected)
