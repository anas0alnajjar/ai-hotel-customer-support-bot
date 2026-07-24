"""Framework-independent password, access-token, and privacy helpers."""

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

PASSWORD_ALGORITHM = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
TOKEN_VERSION = "admin-v1"
TOKEN_MAX_LENGTH = 1024
TOKEN_SIGNATURE_BYTES = hashlib.sha256().digest_size
BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
TOKEN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

BOOKING_PATTERN = re.compile(r"\bBKG-[A-Z0-9-]{4,28}\b", re.IGNORECASE)
TRACKING_PATTERN = re.compile(r"\bSR-[A-Z0-9-]{3,28}\b", re.IGNORECASE)
VERIFICATION_PATTERN = re.compile(
    r"\b(?:verification|verify|code|رمز\s*التحقق)\s*[:=]?\s*[\w@.+-]{3,64}",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not value or len(value) % 4 == 1 or BASE64URL_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid base64url value")
    decoded = base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical base64url value")
    return decoded


def normalize_admin_identifier(value: str) -> str:
    return value.strip().casefold()


def validate_admin_password(value: str) -> str:
    if not 12 <= len(value) <= 128:
        raise ValueError("admin password must contain 12 to 128 characters")
    if value.isspace():
        raise ValueError("admin password cannot contain only whitespace")
    return value


def hash_admin_password(value: str, *, salt: bytes | None = None) -> str:
    password = validate_admin_password(value).encode("utf-8")
    selected_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password,
        salt=selected_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return (
        f"{PASSWORD_ALGORITHM}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{_b64encode(selected_salt)}${_b64encode(digest)}"
    )


def verify_admin_password(value: str, encoded_hash: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded_hash.split("$", 5)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        n, r, p = int(n_text), int(r_text), int(p_text)
        if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        if not 1 <= len(value) <= 128:
            value = "invalid-password-shape"
        actual = hashlib.scrypt(
            value.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def login_identifier_key(identifier: str, secret: bytes) -> UUID:
    digest = hmac.new(
        secret,
        f"admin-login:{normalize_admin_identifier(identifier)}".encode(),
        hashlib.sha256,
    ).digest()
    return UUID(bytes=digest[:16])


def mask_guest_reference(identity_hash: str) -> str:
    suffix = identity_hash[-8:] if len(identity_hash) >= 8 else "unknown"
    return f"guest_********{suffix}"


def mask_tracking_code(value: str) -> str:
    suffix = value[-4:] if len(value) >= 4 else "****"
    return f"SR-******{suffix}"


def redact_admin_text(value: str) -> str:
    """Mask high-risk identifiers before conversation text reaches an admin client."""

    redacted = BOOKING_PATTERN.sub("[BOOKING_REFERENCE]", value)
    redacted = TRACKING_PATTERN.sub("[TRACKING_CODE]", redacted)
    redacted = VERIFICATION_PATTERN.sub("verification=[REDACTED]", redacted)
    redacted = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", redacted)
    return PHONE_PATTERN.sub("[PHONE_REDACTED]", redacted)


@dataclass(frozen=True, slots=True)
class AdminTokenClaims:
    admin_id: UUID
    issued_at: datetime
    expires_at: datetime
    token_id: str


class AdminAccessTokenCodec:
    """Issue and validate bounded HMAC tokens without storing bearer credentials."""

    def __init__(self, secret: str, *, lifetime_minutes: int = 15) -> None:
        if len(secret) < 32:
            raise ValueError("admin token secret must contain at least 32 characters")
        if not 5 <= lifetime_minutes <= 60:
            raise ValueError("admin access lifetime must be 5 to 60 minutes")
        self._secret = secret.encode("utf-8")
        self._lifetime = timedelta(minutes=lifetime_minutes)

    @property
    def lifetime_seconds(self) -> int:
        return int(self._lifetime.total_seconds())

    @property
    def secret_bytes(self) -> bytes:
        return self._secret

    def issue(self, admin_id: UUID, *, now: datetime | None = None) -> str:
        issued = (now or datetime.now(UTC)).astimezone(UTC)
        payload = {
            "sub": str(admin_id),
            "iat": int(issued.timestamp()),
            "exp": int((issued + self._lifetime).timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        encoded = _b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signed = f"{TOKEN_VERSION}.{encoded}".encode("ascii")
        signature = _b64encode(hmac.new(self._secret, signed, hashlib.sha256).digest())
        return f"{TOKEN_VERSION}.{encoded}.{signature}"

    def decode(self, token: str, *, now: datetime | None = None) -> AdminTokenClaims:
        try:
            if not isinstance(token, str) or not token or len(token) > TOKEN_MAX_LENGTH:
                raise ValueError("invalid token shape")
            version, encoded, signature = token.split(".")
            if version != TOKEN_VERSION:
                raise ValueError("unsupported token version")
            signed = f"{version}.{encoded}".encode("ascii")
            expected = hmac.new(self._secret, signed, hashlib.sha256).digest()
            supplied_signature = _b64decode(signature)
            if len(supplied_signature) != TOKEN_SIGNATURE_BYTES or not hmac.compare_digest(
                expected, supplied_signature
            ):
                raise ValueError("invalid token signature")
            payload_bytes = _b64decode(encoded)
            payload = json.loads(payload_bytes)
            if not isinstance(payload, dict):
                raise ValueError("invalid token payload")
            canonical_payload = json.dumps(
                payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if not hmac.compare_digest(payload_bytes, canonical_payload):
                raise ValueError("non-canonical token payload")
            claims = self._claims(payload)

            current_value = now or datetime.now(UTC)
            if current_value.tzinfo is None:
                raise ValueError("token validation time must be timezone-aware")
            current = current_value.astimezone(UTC)
            if claims.expires_at <= current or claims.issued_at > current + timedelta(seconds=30):
                raise ValueError("expired or not-yet-valid admin access token")
            if claims.expires_at - claims.issued_at != self._lifetime:
                raise ValueError("invalid admin access lifetime")
            return claims
        except (
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
            OverflowError,
            OSError,
        ) as exc:
            raise ValueError("invalid admin access token") from exc

    @staticmethod
    def _claims(payload: dict[str, Any]) -> AdminTokenClaims:
        if set(payload) != {"sub", "iat", "exp", "jti"}:
            raise ValueError("unexpected token claims")
        if type(payload["iat"]) is not int or type(payload["exp"]) is not int:
            raise ValueError("invalid token timestamps")
        if (
            not isinstance(payload["jti"], str)
            or TOKEN_ID_PATTERN.fullmatch(payload["jti"]) is None
        ):
            raise ValueError("invalid token id")
        if not isinstance(payload["sub"], str):
            raise ValueError("invalid token subject")
        admin_id = UUID(payload["sub"])
        if str(admin_id) != payload["sub"]:
            raise ValueError("non-canonical token subject")
        return AdminTokenClaims(
            admin_id=admin_id,
            issued_at=datetime.fromtimestamp(payload["iat"], UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            token_id=payload["jti"],
        )
