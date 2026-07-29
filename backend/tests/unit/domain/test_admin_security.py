"""Administration password, token, privacy, and policy tests."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from hotel_bot.application.admin import AdminAuthService
from hotel_bot.domain.admin.errors import (
    AdminAuthenticationError,
    AdminAuthorizationError,
    AdminRateLimitError,
)
from hotel_bot.domain.admin.models import AdminCredential, AdminPrincipal
from hotel_bot.domain.admin.security import (
    AdminAccessTokenCodec,
    hash_admin_password,
    redact_admin_text,
    verify_admin_password,
)
from hotel_bot.persistence.enums import AdminRole


class FakeAuthRepository:
    def __init__(self, credential: AdminCredential | None, *, failures: int = 0) -> None:
        self.credential = credential
        self.failures = failures
        self.events: list[tuple[str, str]] = []

    async def find_credential(self, identifier: str) -> AdminCredential | None:
        return self.credential

    async def get_active_principal(self, admin_id: UUID) -> AdminPrincipal | None:
        if self.credential and self.credential.principal.id == admin_id:
            return self.credential.principal
        return None

    async def count_recent_login_failures(self, identifier_key: UUID, since: datetime) -> int:
        return self.failures

    async def record_login_failure(
        self, *, identifier_key: UUID, correlation_id: str, reason: str
    ) -> None:
        self.events.append(("login_failed", reason))

    async def record_login_success(
        self,
        *,
        principal: AdminPrincipal,
        identifier_key: UUID,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None:
        self.events.append(("login_succeeded", principal.role.value))

    async def record_access_denied(
        self,
        *,
        correlation_id: str,
        reason: str,
        admin_id: UUID | None,
        resource: str,
    ) -> None:
        self.events.append(("access_denied", reason))


def principal(role: AdminRole = AdminRole.ADMIN) -> AdminPrincipal:
    return AdminPrincipal(
        id=uuid4(),
        email="admin@example.invalid",
        username="admin",
        role=role,
    )


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_admin_password("Strong local password 1!")
    second = hash_admin_password("Strong local password 1!")

    assert first != second
    assert "Strong local password" not in first
    assert verify_admin_password("Strong local password 1!", first) is True
    assert verify_admin_password("wrong password", first) is False


def test_access_token_rejects_tampering_and_expiry() -> None:
    codec = AdminAccessTokenCodec("s" * 32, lifetime_minutes=15)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    admin_id = uuid4()
    token = codec.issue(admin_id, now=now)

    claims = codec.decode(token, now=now + timedelta(minutes=15, microseconds=-1))
    assert claims.admin_id == admin_id
    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(f"{token[:-1]}x", now=now)
    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(token, now=now + timedelta(minutes=15))
    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(token, now=now + timedelta(minutes=15, microseconds=1))


def _replace_character(value: str, index: int) -> str:
    replacement = "A" if value[index] != "A" else "B"
    return f"{value[:index]}{replacement}{value[index + 1 :]}"


def test_access_token_rejects_modified_payload_and_signature() -> None:
    codec = AdminAccessTokenCodec("p" * 32)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    version, payload, signature = codec.issue(uuid4(), now=now).split(".")

    modified_payload = _replace_character(payload, len(payload) // 2)
    modified_signature = _replace_character(signature, 0)

    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(f"{version}.{modified_payload}.{signature}", now=now)
    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(f"{version}.{payload}.{modified_signature}", now=now)


def test_access_token_rejects_truncation_and_malformed_base64() -> None:
    codec = AdminAccessTokenCodec("m" * 32)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    token = codec.issue(uuid4(), now=now)
    version, payload, signature = token.split(".")

    invalid_tokens = (
        token[:-1],
        f"{version}.{payload}*.{signature}",
        f"{version}.{payload}.{signature}*",
        f"{version}.{payload}.",
        f"{version}.{payload}",
    )
    for invalid_token in invalid_tokens:
        with pytest.raises(ValueError, match="invalid admin access token"):
            codec.decode(invalid_token, now=now)


def test_access_token_rejects_non_canonical_base64_pad_bits() -> None:
    codec = AdminAccessTokenCodec("c" * 32)
    now = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    version, payload, signature = codec.issue(uuid4(), now=now).split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    canonical_index = alphabet.index(signature[-1])
    non_canonical_signature = f"{signature[:-1]}{alphabet[canonical_index ^ 1]}"

    canonical_bytes = base64.urlsafe_b64decode(signature + "=")
    non_canonical_bytes = base64.urlsafe_b64decode(non_canonical_signature + "=")
    assert non_canonical_bytes == canonical_bytes

    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(f"{version}.{payload}.{non_canonical_signature}", now=now)
    with pytest.raises(ValueError, match="invalid admin access token"):
        codec.decode(f"{version}.{payload}.{signature}=", now=now)


def test_access_token_expiry_boundary_is_exact() -> None:
    codec = AdminAccessTokenCodec("e" * 32, lifetime_minutes=15)
    issued_at = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    expires_at = issued_at + timedelta(minutes=15)
    token = codec.issue(uuid4(), now=issued_at)

    assert codec.decode(token, now=expires_at - timedelta(microseconds=1))
    for invalid_time in (expires_at, expires_at + timedelta(microseconds=1)):
        with pytest.raises(ValueError, match="invalid admin access token"):
            codec.decode(token, now=invalid_time)


def test_admin_text_masks_high_risk_identifiers() -> None:
    masked = redact_admin_text(
        "BKG-TEST-123 verification=Secret77 email admin@example.com phone +963 944 123 456"
    )

    assert "BKG-TEST-123" not in masked
    assert "Secret77" not in masked
    assert "admin@example.com" not in masked
    assert "+963 944 123 456" not in masked


def test_admin_text_preserves_iso_dates_while_masking_phone_numbers() -> None:
    masked = redact_admin_text("Arrival 2026-08-10, departure 2026-08-12, phone +963 944 123 456")

    assert "2026-08-10" in masked
    assert "2026-08-12" in masked
    assert "+963 944 123 456" not in masked
    assert "[PHONE_REDACTED]" in masked


def test_auth_service_has_generic_failure_rate_limit_and_rbac() -> None:
    async def exercise() -> None:
        admin = principal()
        credential = AdminCredential(
            principal=admin,
            password_hash=hash_admin_password("Strong local password 1!"),
        )
        repository = FakeAuthRepository(credential)
        codec = AdminAccessTokenCodec("t" * 32)
        service = AdminAuthService(repository, codec)

        result = await service.login(
            identifier="ADMIN@example.invalid",
            password="Strong local password 1!",
            correlation_id="test-login",
        )
        assert result.principal == admin
        assert repository.events == [("login_succeeded", "admin")]

        authenticated = await service.authenticate(
            token=result.access_token,
            correlation_id="test-auth",
            resource="/admin/knowledge",
        )
        assert authenticated == admin

        with pytest.raises(AdminAuthorizationError):
            await service.authorize(
                AdminPrincipal(
                    id=uuid4(),
                    email="support@example.invalid",
                    username="support",
                    role=AdminRole.SUPPORT,
                ),
                allowed_roles=frozenset({AdminRole.ADMIN}),
                correlation_id="test-forbidden",
                resource="/admin/knowledge",
            )

        limited = AdminAuthService(FakeAuthRepository(None, failures=5), codec)
        with pytest.raises(AdminRateLimitError):
            await limited.login(
                identifier="missing@example.invalid",
                password="Strong local password 1!",
                correlation_id="test-limited",
            )

        unknown = AdminAuthService(FakeAuthRepository(None), codec)
        with pytest.raises(AdminAuthenticationError, match="invalid administration credentials"):
            await unknown.login(
                identifier="missing@example.invalid",
                password="Strong local password 1!",
                correlation_id="test-invalid",
            )

    asyncio.run(exercise())
