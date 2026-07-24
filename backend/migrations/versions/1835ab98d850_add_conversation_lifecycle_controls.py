"""add conversation lifecycle controls

Revision ID: 1835ab98d850
Revises: 2b4ece01b94b
Create Date: 2026-07-13 19:44:00.471005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1835ab98d850"
down_revision: str | None = "2b4ece01b94b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_updates",
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_update_id", sa.String(length=128), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("guest_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=True),
        sa.Column("response_message_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "processing",
                "completed",
                "failed",
                name="channel_update_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="processing",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_channel_updates_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guests.id"],
            name=op.f("fk_channel_updates_guest_id_guests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["messages.id"],
            name=op.f("fk_channel_updates_inbound_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["response_message_id"],
            ["messages.id"],
            name=op.f("fk_channel_updates_response_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_updates")),
        sa.UniqueConstraint("channel", "external_update_id", name="uq_channel_updates_external"),
    )
    op.create_index(
        "ix_channel_updates_correlation_id", "channel_updates", ["correlation_id"], unique=False
    )

    op.add_column("conversations", sa.Column("last_activity_at", sa.DateTime(), nullable=True))
    op.execute(
        """
        UPDATE conversations AS c
        LEFT JOIN (
            SELECT conversation_id, MAX(created_at) AS last_message_at
            FROM messages
            GROUP BY conversation_id
        ) AS m ON m.conversation_id = c.id
        SET c.last_activity_at = COALESCE(m.last_message_at, c.started_at, CURRENT_TIMESTAMP)
        """
    )
    op.alter_column(
        "conversations",
        "last_activity_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.create_index(
        "ix_conversations_status_last_activity",
        "conversations",
        ["status", "last_activity_at"],
        unique=False,
    )

    op.add_column("messages", sa.Column("sequence_number", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE messages AS target
        JOIN (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY conversation_id ORDER BY created_at, id
            ) AS generated_sequence
            FROM messages
        ) AS ranked ON ranked.id = target.id
        SET target.sequence_number = ranked.generated_sequence
        """
    )
    op.alter_column("messages", "sequence_number", existing_type=sa.Integer(), nullable=False)
    op.add_column("messages", sa.Column("redacted_at", sa.DateTime(), nullable=True))
    op.add_column("messages", sa.Column("retention_action", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_messages_sequence_number_positive"), "messages", "sequence_number > 0"
    )
    op.create_unique_constraint(
        "uq_messages_conversation_seq", "messages", ["conversation_id", "sequence_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_messages_conversation_seq", "messages", type_="unique")
    op.drop_constraint(op.f("ck_messages_sequence_number_positive"), "messages", type_="check")
    op.drop_column("messages", "retention_action")
    op.drop_column("messages", "redacted_at")
    op.drop_column("messages", "sequence_number")
    op.drop_index("ix_conversations_status_last_activity", table_name="conversations")
    op.drop_column("conversations", "last_activity_at")
    op.drop_index("ix_channel_updates_correlation_id", table_name="channel_updates")
    op.drop_table("channel_updates")
