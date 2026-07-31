"""Configuration validation tests."""

import pytest
from pydantic import ValidationError

from hotel_bot.core.config import Settings


def build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "db_host": "localhost",
        "db_port": 3306,
        "db_name": "hotel_bot_test",
        "db_user": "hotel_bot",
        "db_password": "p@ss:word",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_database_url_escapes_credentials() -> None:
    settings = build_settings()

    url = settings.sqlalchemy_url.render_as_string(hide_password=False)

    assert (
        url
        == "mysql+asyncmy://hotel_bot:p%40ss%3Aword@localhost:3306/hotel_bot_test?charset=utf8mb4"
    )


def test_context_and_retention_defaults_match_approved_policy() -> None:
    settings = build_settings()

    assert settings.conversation_context_turns == 5
    assert settings.conversation_retention_days == 90
    assert settings.conversation_context_max_tokens == 3000
    assert settings.conversation_inactivity_minutes == 30
    assert settings.retention_cleanup_batch_size == 500
    assert settings.intent_general_confidence_threshold == 0.60
    assert settings.intent_action_confidence_threshold == 0.80
    assert settings.intent_confidence_margin_threshold == 0.15
    assert settings.hybrid_llm_router_enabled is True
    assert settings.hybrid_llm_router_confidence_threshold == 0.75
    assert settings.hybrid_llm_router_timeout_seconds == 5.0
    assert settings.tool_read_timeout_ms == 2000
    assert settings.tool_write_timeout_ms == 5000
    assert settings.tool_max_calls_per_turn == 3
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.gemini_timeout_ms == 20_000
    assert settings.gemini_retry_attempts == 2
    assert settings.gemini_max_output_tokens == 1024
    assert settings.gemini_max_tokens_per_turn == 10_000
    assert settings.gemini_max_estimated_cost_usd_per_turn == 0.05
    assert settings.telegram_timeout_ms == 10_000
    assert settings.telegram_max_update_bytes == 262_144
    assert settings.admin_access_token_minutes == 15
    assert settings.admin_login_max_attempts == 5
    assert settings.admin_login_window_minutes == 15
    assert settings.trusted_host_list == ("localhost", "127.0.0.1", "testserver", "backend")


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="debug mode cannot be enabled"):
        build_settings(environment="production", debug=True)


def test_trusted_hosts_are_normalized_and_wildcard_is_forbidden_in_production() -> None:
    settings = build_settings(trusted_hosts=" Hotel.Example.com,backend,hotel.example.com ")
    assert settings.trusted_host_list == ("hotel.example.com", "backend")

    with pytest.raises(ValidationError, match="wildcard trusted host"):
        build_settings(
            environment="production",
            trusted_hosts="*",
            telegram_bot_token="123456789:valid-test-token",
            telegram_webhook_secret="webhook-test-secret",
            telegram_identity_pepper="p" * 32,
            admin_token_secret="a" * 32,
        )


def test_tool_limits_are_bounded() -> None:
    with pytest.raises(ValidationError):
        build_settings(tool_max_calls_per_turn=0)
    with pytest.raises(ValidationError):
        build_settings(tool_write_timeout_ms=30_001)


def test_telegram_secrets_are_all_or_nothing_and_required_in_production() -> None:
    with pytest.raises(ValidationError, match="required together"):
        build_settings(telegram_bot_token="123456789:partial-token")
    with pytest.raises(ValidationError, match="required in production"):
        build_settings(environment="production")

    production = build_settings(
        environment="production",
        telegram_bot_token="123456789:valid-test-token",
        telegram_webhook_secret="webhook-test-secret",
        telegram_identity_pepper="p" * 32,
        admin_token_secret="a" * 32,
    )
    assert production.telegram_api_base_url == "https://api.telegram.org"
