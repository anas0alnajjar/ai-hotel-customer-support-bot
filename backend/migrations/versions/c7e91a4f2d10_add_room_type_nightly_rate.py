"""add room type nightly rate

Revision ID: c7e91a4f2d10
Revises: b2d4e6f8091a
Create Date: 2026-07-30 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e91a4f2d10"
down_revision: str | None = "b2d4e6f8091a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "room_types",
        sa.Column(
            "nightly_rate_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        op.f("ck_room_types_nightly_rate_nonnegative"),
        "room_types",
        "nightly_rate_cents >= 0",
    )
    op.execute(
        """
        UPDATE room_types
        SET nightly_rate_cents = CASE code
            WHEN 'standard_king' THEN 8500
            WHEN 'standard_twin' THEN 9000
            WHEN 'deluxe_king' THEN 12500
            WHEN 'family_suite' THEN 18000
            WHEN 'executive_suite' THEN 22000
            ELSE nightly_rate_cents
        END
        WHERE code IN (
            'standard_king',
            'standard_twin',
            'deluxe_king',
            'family_suite',
            'executive_suite'
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_room_types_nightly_rate_nonnegative"),
        "room_types",
        type_="check",
    )
    op.drop_column("room_types", "nightly_rate_cents")
