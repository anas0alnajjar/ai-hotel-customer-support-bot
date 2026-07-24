"""Shared test configuration."""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENVIRONMENT", "test")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_NAME", "hotel_bot_test")
os.environ.setdefault("DB_USER", "hotel_bot_test")
os.environ.setdefault("DB_PASSWORD", "test-only-password")

from hotel_bot.core.config import Settings  # noqa: E402
from hotel_bot.main import create_app  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
