"""add llm run telemetry

Revision ID: a8210f76e4ce
Revises: 064d8b1e00ec
Create Date: 2026-07-21 15:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8210f76e4ce"
down_revision: str | None = "064d8b1e00ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_runs",
        sa.Column(
            "request_kind", sa.String(length=32), server_default="final_answer", nullable=False
        ),
    )
    op.add_column("llm_runs", sa.Column("thought_tokens", sa.Integer(), nullable=True))
    op.add_column("llm_runs", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("llm_runs", sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True))
    op.add_column("llm_runs", sa.Column("provider_request_id", sa.String(128), nullable=True))
    op.create_check_constraint(
        op.f("ck_llm_runs_thought_tokens_nonnegative"),
        "llm_runs",
        "thought_tokens IS NULL OR thought_tokens >= 0",
    )
    op.create_check_constraint(
        op.f("ck_llm_runs_total_tokens_nonnegative"),
        "llm_runs",
        "total_tokens IS NULL OR total_tokens >= 0",
    )
    op.create_check_constraint(
        op.f("ck_llm_runs_estimated_cost_nonnegative"),
        "llm_runs",
        "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_llm_runs_estimated_cost_nonnegative"), "llm_runs", type_="check")
    op.drop_constraint(op.f("ck_llm_runs_total_tokens_nonnegative"), "llm_runs", type_="check")
    op.drop_constraint(op.f("ck_llm_runs_thought_tokens_nonnegative"), "llm_runs", type_="check")
    op.drop_column("llm_runs", "provider_request_id")
    op.drop_column("llm_runs", "estimated_cost_usd")
    op.drop_column("llm_runs", "total_tokens")
    op.drop_column("llm_runs", "thought_tokens")
    op.drop_column("llm_runs", "request_kind")
