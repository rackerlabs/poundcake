"""Regression tests for PoundCake Redis configuration defaults."""

from __future__ import annotations

from api.core.config import Settings


def test_api_settings_redis_url_defaults_to_stack_env(monkeypatch) -> None:
    monkeypatch.delenv("POUNDCAKE_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setenv("REDIS_HOST", "stackstorm-redis")
    monkeypatch.setenv("REDIS_PORT", "6379")

    settings = Settings()

    assert settings.redis_url == "redis://stackstorm-redis:6379/0"


def test_api_settings_redis_url_escapes_raw_password(monkeypatch) -> None:
    monkeypatch.delenv("POUNDCAKE_REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_HOST", "stackstorm-redis")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", "p@ss word")

    settings = Settings()

    assert settings.redis_url == "redis://:p%40ss%20word@stackstorm-redis:6379/0"
