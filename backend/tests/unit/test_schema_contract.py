"""Static contracts for the authoritative relational schema."""

from typing import cast

from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, UniqueConstraint

from hotel_bot.persistence import Base

EXPECTED_DOMAIN_TABLES = {
    "admin_users",
    "audit_events",
    "bookings",
    "channel_updates",
    "conversations",
    "escalations",
    "evaluation_runs",
    "feedback",
    "guests",
    "index_versions",
    "knowledge_chunks",
    "knowledge_documents",
    "knowledge_revisions",
    "llm_runs",
    "messages",
    "rooms",
    "room_types",
    "service_requests",
    "tool_executions",
}


def test_metadata_contains_exactly_the_approved_domain_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_DOMAIN_TABLES


def test_persisted_enums_are_portable_checked_strings() -> None:
    enum_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Enum)
    ]

    assert enum_columns
    enum_types = [cast(Enum, column.type) for column in enum_columns]
    assert all(enum.native_enum is False for enum in enum_types)
    assert all(enum.create_constraint is True for enum in enum_types)

    admin_role = cast(Enum, Base.metadata.tables["admin_users"].c.role.type)
    actor_type = cast(Enum, Base.metadata.tables["audit_events"].c.actor_type.type)
    assert set(admin_role.enums) == {"admin", "support", "evaluator"}
    assert set(actor_type.enums) == {"guest", "admin", "support", "evaluator", "system"}


def test_privacy_and_idempotency_fields_are_constrained() -> None:
    bookings = Base.metadata.tables["bookings"]
    service_requests = Base.metadata.tables["service_requests"]
    guests = Base.metadata.tables["guests"]
    channel_updates = Base.metadata.tables["channel_updates"]
    messages = Base.metadata.tables["messages"]
    tool_executions = Base.metadata.tables["tool_executions"]
    llm_runs = Base.metadata.tables["llm_runs"]

    assert "guest_verification_hash" in bookings.c
    assert "verification_value" not in bookings.c
    assert "telegram_user_hash" in guests.c
    assert "telegram_user_id" not in guests.c

    unique_column_sets = {
        tuple(constraint.columns.keys())
        for constraint in service_requests.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("idempotency_key",) in unique_column_sets
    assert ("tracking_code",) in unique_column_sets

    channel_unique_sets = {
        tuple(constraint.columns.keys())
        for constraint in channel_updates.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    message_unique_sets = {
        tuple(constraint.columns.keys())
        for constraint in messages.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("channel", "external_update_id") in channel_unique_sets
    assert ("conversation_id", "sequence_number") in message_unique_sets
    assert "redacted_at" in messages.c
    assert "retention_action" in messages.c
    assert "arguments_redacted" in tool_executions.c
    assert "result_redacted" in tool_executions.c
    assert "arguments" not in tool_executions.c
    assert "result" not in tool_executions.c
    assert {
        "request_kind",
        "thought_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "provider_request_id",
    } <= set(llm_runs.c.keys())


def test_critical_foreign_keys_define_delete_behavior() -> None:
    expected = {
        ("messages", ("conversation_id",)): "CASCADE",
        ("bookings", ("room_id",)): "SET NULL",
        ("service_requests", ("room_id",)): "RESTRICT",
        ("tool_executions", ("message_id",)): "CASCADE",
    }

    actual: dict[tuple[str, tuple[str, ...]], str | None] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                columns = tuple(constraint.columns.keys())
                actual[(table.name, columns)] = constraint.ondelete

    for key, ondelete in expected.items():
        assert actual[key] == ondelete


def test_numeric_and_temporal_invariants_have_database_checks() -> None:
    required_checks = {
        "bookings": {
            "ck_bookings_date_range_valid",
            "ck_bookings_adults_positive",
            "ck_bookings_children_nonnegative",
        },
        "messages": {"ck_messages_confidence_range"},
        "feedback": {"ck_feedback_rating_range"},
        "knowledge_chunks": {
            "ck_knowledge_chunks_chunk_index_nonnegative",
            "ck_knowledge_chunks_faiss_vector_id_nonnegative",
        },
        "index_versions": {
            "ck_index_versions_dimension_positive",
            "ck_index_versions_document_count_nonnegative",
            "ck_index_versions_chunk_count_nonnegative",
        },
        "llm_runs": {
            "ck_llm_runs_input_tokens_nonnegative",
            "ck_llm_runs_output_tokens_nonnegative",
            "ck_llm_runs_thought_tokens_nonnegative",
            "ck_llm_runs_total_tokens_nonnegative",
            "ck_llm_runs_estimated_cost_nonnegative",
        },
    }

    for table_name, expected_names in required_checks.items():
        table = Base.metadata.tables[table_name]
        actual_names = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert expected_names <= actual_names


def test_knowledge_schema_separates_authoritative_revisions_from_derived_index() -> None:
    documents = Base.metadata.tables["knowledge_documents"]
    versions = Base.metadata.tables["index_versions"]

    assert "source_format" in documents.c
    assert documents.c.current_revision_id.nullable is True
    assert versions.c.checksum.nullable is True
    assert {"artifact_path", "document_count", "chunk_count", "build_error"} <= set(
        versions.c.keys()
    )
