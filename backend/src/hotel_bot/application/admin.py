"""Application-owned administration authentication and authorization policy."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from hotel_bot.domain.admin.errors import (
    AdminAuthenticationError,
    AdminAuthorizationError,
    AdminRateLimitError,
)
from hotel_bot.domain.admin.models import AdminCredential, AdminLoginResult, AdminPrincipal
from hotel_bot.domain.admin.security import (
    AdminAccessTokenCodec,
    hash_admin_password,
    login_identifier_key,
    normalize_admin_identifier,
    verify_admin_password,
)
from hotel_bot.persistence.enums import AdminRole

DUMMY_PASSWORD_HASH = hash_admin_password(
    "dummy-admin-password-not-a-credential",
    salt=b"hotel-admin-dummy",
)


class AdminAuthRepository(Protocol):
    async def find_credential(self, identifier: str) -> AdminCredential | None: ...

    async def get_active_principal(self, admin_id: UUID) -> AdminPrincipal | None: ...

    async def count_recent_login_failures(self, identifier_key: UUID, since: datetime) -> int: ...

    async def record_login_failure(
        self, *, identifier_key: UUID, correlation_id: str, reason: str
    ) -> None: ...

    async def record_login_success(
        self,
        *,
        principal: AdminPrincipal,
        identifier_key: UUID,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None: ...

    async def record_access_denied(
        self,
        *,
        correlation_id: str,
        reason: str,
        admin_id: UUID | None,
        resource: str,
    ) -> None: ...


class AdminAuthService:
    def __init__(
        self,
        repository: AdminAuthRepository,
        token_codec: AdminAccessTokenCodec,
        *,
        max_login_attempts: int = 5,
        login_window_minutes: int = 15,
    ) -> None:
        if not 3 <= max_login_attempts <= 20:
            raise ValueError("admin max login attempts must be 3 to 20")
        if not 1 <= login_window_minutes <= 60:
            raise ValueError("admin login window must be 1 to 60 minutes")
        self._repository = repository
        self._tokens = token_codec
        self._max_login_attempts = max_login_attempts
        self._login_window = timedelta(minutes=login_window_minutes)

    async def login(
        self,
        *,
        identifier: str,
        password: str,
        correlation_id: str,
        now: datetime | None = None,
    ) -> AdminLoginResult:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        normalized = normalize_admin_identifier(identifier)
        identifier_key = login_identifier_key(normalized, self._tokens.secret_bytes)
        since = (occurred_at - self._login_window).replace(tzinfo=None)
        failures = await self._repository.count_recent_login_failures(identifier_key, since)
        if failures >= self._max_login_attempts:
            await self._repository.record_login_failure(
                identifier_key=identifier_key,
                correlation_id=correlation_id,
                reason="rate_limited",
            )
            raise AdminRateLimitError(
                "admin_login_rate_limited", "too many login attempts; retry later"
            )

        credential = await self._repository.find_credential(normalized)
        candidate_hash = credential.password_hash if credential else DUMMY_PASSWORD_HASH
        valid = verify_admin_password(password, candidate_hash)
        if credential is None or not valid:
            await self._repository.record_login_failure(
                identifier_key=identifier_key,
                correlation_id=correlation_id,
                reason="invalid_credentials",
            )
            raise AdminAuthenticationError(
                "invalid_admin_credentials", "invalid administration credentials"
            )

        await self._repository.record_login_success(
            principal=credential.principal,
            identifier_key=identifier_key,
            correlation_id=correlation_id,
            occurred_at=occurred_at.replace(tzinfo=None),
        )
        return AdminLoginResult(
            access_token=self._tokens.issue(credential.principal.id, now=occurred_at),
            expires_in=self._tokens.lifetime_seconds,
            principal=credential.principal,
        )

    async def authenticate(
        self,
        *,
        token: str | None,
        correlation_id: str,
        resource: str,
        now: datetime | None = None,
    ) -> AdminPrincipal:
        admin_id: UUID | None = None
        try:
            if not token:
                raise ValueError("missing bearer token")
            claims = self._tokens.decode(token, now=now)
            admin_id = claims.admin_id
            principal = await self._repository.get_active_principal(admin_id)
            if principal is None:
                raise ValueError("inactive administration principal")
            return principal
        except ValueError as exc:
            await self._repository.record_access_denied(
                correlation_id=correlation_id,
                reason="invalid_or_missing_token",
                admin_id=admin_id,
                resource=resource,
            )
            raise AdminAuthenticationError(
                "admin_authentication_required", "valid administration authentication is required"
            ) from exc

    async def authorize(
        self,
        principal: AdminPrincipal,
        *,
        allowed_roles: frozenset[AdminRole],
        correlation_id: str,
        resource: str,
    ) -> AdminPrincipal:
        if principal.role in allowed_roles:
            return principal
        await self._repository.record_access_denied(
            correlation_id=correlation_id,
            reason="role_forbidden",
            admin_id=principal.id,
            resource=resource,
        )
        raise AdminAuthorizationError(
            "admin_role_forbidden", "the administration role cannot access this resource"
        )
