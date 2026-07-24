"""Typed application configuration loaded from environment variables."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(default="AI Hotel Customer Support Bot", alias="APP_NAME")
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENVIRONMENT"
    )
    debug: bool = Field(default=False, alias="APP_DEBUG")
    log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    trusted_hosts: str = Field(
        default="localhost,127.0.0.1,testserver,backend",
        alias="TRUSTED_HOSTS",
    )

    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=3306, ge=1, le=65535, alias="DB_PORT")
    db_name: str = Field(min_length=1, alias="DB_NAME")
    db_user: str = Field(min_length=1, alias="DB_USER")
    db_password: SecretStr = Field(alias="DB_PASSWORD")
    db_pool_size: int = Field(default=10, ge=1, le=100, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, ge=0, le=200, alias="DB_MAX_OVERFLOW")

    conversation_retention_days: int = Field(
        default=90, ge=1, le=3650, alias="CONVERSATION_RETENTION_DAYS"
    )
    conversation_context_turns: int = Field(
        default=5, ge=1, le=20, alias="CONVERSATION_CONTEXT_TURNS"
    )
    conversation_context_max_tokens: int = Field(
        default=3000, ge=500, le=100_000, alias="CONVERSATION_CONTEXT_MAX_TOKENS"
    )
    conversation_inactivity_minutes: int = Field(
        default=30, ge=5, le=1440, alias="CONVERSATION_INACTIVITY_MINUTES"
    )
    retention_cleanup_batch_size: int = Field(
        default=500, ge=1, le=10_000, alias="RETENTION_CLEANUP_BATCH_SIZE"
    )
    intent_general_confidence_threshold: float = Field(
        default=0.60, ge=0, le=1, alias="INTENT_GENERAL_CONFIDENCE_THRESHOLD"
    )
    intent_action_confidence_threshold: float = Field(
        default=0.80, ge=0, le=1, alias="INTENT_ACTION_CONFIDENCE_THRESHOLD"
    )
    intent_confidence_margin_threshold: float = Field(
        default=0.15, ge=0, le=1, alias="INTENT_CONFIDENCE_MARGIN_THRESHOLD"
    )

    knowledge_index_path: Path = Field(
        default=Path("backend/data/faiss"), alias="KNOWLEDGE_INDEX_PATH"
    )
    knowledge_chunk_max_chars: int = Field(
        default=800, ge=200, le=4000, alias="KNOWLEDGE_CHUNK_MAX_CHARS"
    )
    knowledge_chunk_overlap_chars: int = Field(
        default=120, ge=0, le=1000, alias="KNOWLEDGE_CHUNK_OVERLAP_CHARS"
    )
    embedding_provider: Literal["sentence_transformers", "hashing_test"] = Field(
        default="sentence_transformers", alias="EMBEDDING_PROVIDER"
    )
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        alias="EMBEDDING_MODEL",
    )
    embedding_model_revision: str = Field(
        default="86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d",
        alias="EMBEDDING_MODEL_REVISION",
    )
    embedding_cache_path: Path = Field(
        default=Path("backend/data/models"), alias="EMBEDDING_CACHE_PATH"
    )
    embedding_dimension: int = Field(default=384, ge=8, le=8192, alias="EMBEDDING_DIMENSION")
    embedding_batch_size: int = Field(default=32, ge=1, le=256, alias="EMBEDDING_BATCH_SIZE")
    retrieval_top_k: int = Field(default=5, ge=1, le=20, alias="RETRIEVAL_TOP_K")
    retrieval_min_score: float = Field(default=0.35, ge=-1, le=1, alias="RETRIEVAL_MIN_SCORE")

    tool_read_timeout_ms: int = Field(default=2000, ge=100, le=30_000, alias="TOOL_READ_TIMEOUT_MS")
    tool_write_timeout_ms: int = Field(
        default=5000, ge=100, le=30_000, alias="TOOL_WRITE_TIMEOUT_MS"
    )
    tool_max_calls_per_turn: int = Field(default=3, ge=1, le=10, alias="TOOL_MAX_CALLS_PER_TURN")

    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_timeout_ms: int = Field(default=20_000, ge=1_000, le=60_000, alias="GEMINI_TIMEOUT_MS")
    gemini_retry_attempts: int = Field(default=2, ge=1, le=5, alias="GEMINI_RETRY_ATTEMPTS")
    gemini_max_output_tokens: int = Field(
        default=1024, ge=64, le=8192, alias="GEMINI_MAX_OUTPUT_TOKENS"
    )
    gemini_max_tokens_per_turn: int = Field(
        default=10_000, ge=500, le=100_000, alias="GEMINI_MAX_TOKENS_PER_TURN"
    )
    gemini_max_estimated_cost_usd_per_turn: float = Field(
        default=0.05, ge=0.001, le=10, alias="GEMINI_MAX_ESTIMATED_COST_USD_PER_TURN"
    )
    gemini_input_usd_per_million_tokens: float = Field(
        default=1.50, ge=0, alias="GEMINI_INPUT_USD_PER_MILLION_TOKENS"
    )
    gemini_output_usd_per_million_tokens: float = Field(
        default=9.00, ge=0, alias="GEMINI_OUTPUT_USD_PER_MILLION_TOKENS"
    )

    telegram_bot_token: SecretStr | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: SecretStr | None = Field(default=None, alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_identity_pepper: SecretStr | None = Field(
        default=None, alias="TELEGRAM_IDENTITY_PEPPER"
    )
    telegram_api_base_url: str = Field(
        default="https://api.telegram.org", alias="TELEGRAM_API_BASE_URL"
    )
    telegram_timeout_ms: int = Field(
        default=10_000, ge=1_000, le=30_000, alias="TELEGRAM_TIMEOUT_MS"
    )
    telegram_max_update_bytes: int = Field(
        default=262_144, ge=1024, le=1_048_576, alias="TELEGRAM_MAX_UPDATE_BYTES"
    )

    admin_token_secret: SecretStr | None = Field(default=None, alias="ADMIN_TOKEN_SECRET")
    admin_access_token_minutes: int = Field(
        default=15, ge=5, le=60, alias="ADMIN_ACCESS_TOKEN_MINUTES"
    )
    admin_login_max_attempts: int = Field(default=5, ge=3, le=20, alias="ADMIN_LOGIN_MAX_ATTEMPTS")
    admin_login_window_minutes: int = Field(
        default=15, ge=1, le=60, alias="ADMIN_LOGIN_WINDOW_MINUTES"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"log level must be one of {sorted(allowed)}")
        return normalized

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value == "/":
            raise ValueError("API prefix must start with '/' and contain a path")
        return value.rstrip("/")

    @field_validator("trusted_hosts")
    @classmethod
    def validate_trusted_hosts(cls, value: str) -> str:
        hosts = tuple(item.strip().lower() for item in value.split(",") if item.strip())
        if not hosts:
            raise ValueError("at least one trusted host is required")
        if any(
            host != "*"
            and re.fullmatch(r"(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host) is None
            for host in hosts
        ):
            raise ValueError("trusted hosts contain an invalid hostname")
        return ",".join(dict.fromkeys(hosts))

    @model_validator(mode="after")
    def validate_production_settings(self) -> Self:
        if self.environment == "production" and self.debug:
            raise ValueError("debug mode cannot be enabled in production")
        if self.knowledge_chunk_overlap_chars >= self.knowledge_chunk_max_chars:
            raise ValueError("knowledge chunk overlap must be smaller than chunk size")
        if self.environment == "production" and self.embedding_provider == "hashing_test":
            raise ValueError("hashing_test embedding provider is forbidden in production")
        telegram_secrets = (
            self.telegram_bot_token,
            self.telegram_webhook_secret,
            self.telegram_identity_pepper,
        )
        if self.telegram_bot_token and len(self.telegram_bot_token.get_secret_value()) < 20:
            raise ValueError("Telegram bot token must contain at least 20 characters")
        if self.telegram_webhook_secret and not re.fullmatch(
            r"[A-Za-z0-9_-]{16,256}",
            self.telegram_webhook_secret.get_secret_value(),
        ):
            raise ValueError("Telegram webhook secret must use 16-256 safe characters")
        if (
            self.telegram_identity_pepper
            and len(self.telegram_identity_pepper.get_secret_value()) < 32
        ):
            raise ValueError("Telegram identity pepper must contain at least 32 characters")
        if any(value is not None for value in telegram_secrets) and not all(
            value is not None for value in telegram_secrets
        ):
            raise ValueError(
                "Telegram token, webhook secret, and identity pepper are required together"
            )
        if self.environment == "production" and not all(
            value is not None for value in telegram_secrets
        ):
            raise ValueError("Telegram secrets are required in production")
        if self.environment == "production" and not self.telegram_api_base_url.startswith(
            "https://"
        ):
            raise ValueError("Telegram API must use HTTPS in production")
        if self.admin_token_secret and len(self.admin_token_secret.get_secret_value()) < 32:
            raise ValueError("Admin token secret must contain at least 32 characters")
        if self.environment == "production" and self.admin_token_secret is None:
            raise ValueError("Admin token secret is required in production")
        if self.environment == "production" and "*" in self.trusted_host_list:
            raise ValueError("wildcard trusted host is forbidden in production")
        return self

    @field_validator("telegram_api_base_url")
    @classmethod
    def validate_telegram_api_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("Telegram API base URL must be HTTP or HTTPS")
        return normalized

    @property
    def sqlalchemy_url(self) -> URL:
        """Build a safely escaped SQLAlchemy URL without string concatenation."""

        return URL.create(
            drivername="mysql+asyncmy",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

    @property
    def trusted_host_list(self) -> tuple[str, ...]:
        return tuple(self.trusted_hosts.split(","))


@lru_cache
def load_settings() -> Settings:
    """Load and cache process-wide settings."""

    return Settings()  # type: ignore[call-arg]
