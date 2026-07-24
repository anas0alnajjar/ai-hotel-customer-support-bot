"""Create the first administration user without placing a password in shell history."""

import argparse
import asyncio
import getpass
import re
from uuid import uuid4

from sqlalchemy import or_, select

from hotel_bot.core.config import load_settings
from hotel_bot.domain.admin.security import hash_admin_password, normalize_admin_identifier
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.persistence.enums import ActorType, AdminRole, AdminStatus
from hotel_bot.persistence.models import AdminUser, AuditEvent

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,64}$")


async def create_user(*, email: str, username: str, role: AdminRole, password: str) -> None:
    settings = load_settings()
    database = DatabaseManager(settings)
    normalized_email = normalize_admin_identifier(email)
    normalized_username = normalize_admin_identifier(username)
    if not EMAIL_PATTERN.fullmatch(normalized_email):
        raise ValueError("email format is invalid")
    if not USERNAME_PATTERN.fullmatch(normalized_username):
        raise ValueError(
            "username must use 3-64 lowercase letters, digits, dot, dash, or underscore"
        )
    password_hash = hash_admin_password(password)
    user_id = uuid4()
    try:
        async with database.transaction() as session:
            existing = await session.scalar(
                select(AdminUser.id)
                .where(
                    or_(
                        AdminUser.email == normalized_email,
                        AdminUser.username == normalized_username,
                    )
                )
                .limit(1)
            )
            if existing is not None:
                raise ValueError("an administration user already owns this email or username")
            session.add(
                AdminUser(
                    id=user_id,
                    email=normalized_email,
                    username=normalized_username,
                    password_hash=password_hash,
                    role=role,
                    status=AdminStatus.ACTIVE,
                )
            )
            session.add(
                AuditEvent(
                    actor_type=ActorType.SYSTEM,
                    actor_id=None,
                    action="admin_user_bootstrapped",
                    resource_type="admin_user",
                    resource_id=user_id,
                    metadata_redacted={"role": role.value},
                    correlation_id=f"admin-bootstrap:{user_id}",
                )
            )
    finally:
        await database.dispose()
    print(f"Administration user created: id={user_id} role={role.value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create one administration user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=[item.value for item in AdminRole], default="admin")
    args = parser.parse_args()
    password = getpass.getpass("Password (12-128 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if not secrets_match(password, confirmation):
        raise SystemExit("Passwords do not match.")
    asyncio.run(
        create_user(
            email=args.email,
            username=args.username,
            role=AdminRole(args.role),
            password=password,
        )
    )


def secrets_match(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())


if __name__ == "__main__":
    main()
