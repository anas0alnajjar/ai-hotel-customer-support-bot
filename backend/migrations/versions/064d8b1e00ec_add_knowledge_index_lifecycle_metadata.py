"""add knowledge index lifecycle metadata

Revision ID: 064d8b1e00ec
Revises: 1835ab98d850
Create Date: 2026-07-13 21:22:39.459653
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "064d8b1e00ec"
down_revision: str | None = "1835ab98d850"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "index_versions", sa.Column("artifact_path", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "index_versions",
        sa.Column("document_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "index_versions",
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("index_versions", sa.Column("build_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_index_versions_document_count_nonnegative"),
        "index_versions",
        "document_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_index_versions_chunk_count_nonnegative"),
        "index_versions",
        "chunk_count >= 0",
    )
    op.alter_column(
        "index_versions",
        "checksum",
        existing_type=mysql.VARCHAR(length=64),
        nullable=True,
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_format", sa.String(length=16), server_default="plain_text", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "source_format")
    op.execute(
        "UPDATE index_versions "
        "SET checksum = SHA2(CONCAT('legacy:', HEX(id)), 256) "
        "WHERE checksum IS NULL"
    )
    op.alter_column(
        "index_versions",
        "checksum",
        existing_type=mysql.VARCHAR(length=64),
        nullable=False,
    )
    op.drop_constraint(
        op.f("ck_index_versions_chunk_count_nonnegative"), "index_versions", type_="check"
    )
    op.drop_constraint(
        op.f("ck_index_versions_document_count_nonnegative"),
        "index_versions",
        type_="check",
    )
    op.drop_column("index_versions", "build_error")
    op.drop_column("index_versions", "chunk_count")
    op.drop_column("index_versions", "document_count")
    op.drop_column("index_versions", "artifact_path")
