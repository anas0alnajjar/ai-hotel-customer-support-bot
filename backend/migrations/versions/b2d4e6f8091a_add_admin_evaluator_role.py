"""add admin evaluator role

Revision ID: b2d4e6f8091a
Revises: a8210f76e4ce
Create Date: 2026-07-22 13:25:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4e6f8091a"
down_revision: str | None = "a8210f76e4ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_admin_users_admin_role"), "admin_users", type_="check")
    op.alter_column(
        "admin_users",
        "role",
        existing_type=sa.String(length=7),
        type_=sa.String(length=9),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_admin_users_admin_role"),
        "admin_users",
        "role IN ('admin', 'support', 'evaluator')",
    )
    op.drop_constraint(op.f("ck_audit_events_audit_actor_type"), "audit_events", type_="check")
    op.alter_column(
        "audit_events",
        "actor_type",
        existing_type=sa.String(length=7),
        type_=sa.String(length=9),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_audit_events_audit_actor_type"),
        "audit_events",
        "actor_type IN ('guest', 'admin', 'support', 'evaluator', 'system')",
    )


def downgrade() -> None:
    op.execute("UPDATE audit_events SET actor_type = 'admin' WHERE actor_type = 'evaluator'")
    op.execute("UPDATE admin_users SET role = 'admin' WHERE role = 'evaluator'")
    op.drop_constraint(op.f("ck_audit_events_audit_actor_type"), "audit_events", type_="check")
    op.alter_column(
        "audit_events",
        "actor_type",
        existing_type=sa.String(length=9),
        type_=sa.String(length=7),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_audit_events_audit_actor_type"),
        "audit_events",
        "actor_type IN ('guest', 'admin', 'support', 'system')",
    )
    op.drop_constraint(op.f("ck_admin_users_admin_role"), "admin_users", type_="check")
    op.alter_column(
        "admin_users",
        "role",
        existing_type=sa.String(length=9),
        type_=sa.String(length=7),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_admin_users_admin_role"),
        "admin_users",
        "role IN ('admin', 'support')",
    )
