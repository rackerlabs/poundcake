"""Regression tests for runtime version reporting."""

from __future__ import annotations

from api.core.config import Settings as ApiSettings
from bakery.config import Settings as BakerySettings
from shared.version import __version__, resolve_version


def test_resolve_version_uses_first_configured_env_var(monkeypatch) -> None:
    monkeypatch.setenv("PRIMARY_VERSION", "2.0.999")
    monkeypatch.setenv("SECONDARY_VERSION", "2.0.998")

    assert resolve_version("PRIMARY_VERSION", "SECONDARY_VERSION") == "2.0.999"


def test_resolve_version_falls_back_to_repo_version(monkeypatch) -> None:
    monkeypatch.delenv("PRIMARY_VERSION", raising=False)
    monkeypatch.delenv("SECONDARY_VERSION", raising=False)

    assert resolve_version("PRIMARY_VERSION", "SECONDARY_VERSION") == __version__


def test_api_settings_app_version_uses_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("POUNDCAKE_APP_VERSION", "2.0.999")

    settings = ApiSettings()

    assert settings.app_version == "2.0.999"


def test_bakery_settings_app_version_prefers_bakery_env(monkeypatch) -> None:
    monkeypatch.setenv("POUNDCAKE_APP_VERSION", "2.0.998")
    monkeypatch.setenv("BAKERY_APP_VERSION", "2.0.999")

    settings = BakerySettings()

    assert settings.app_version == "2.0.999"


def test_bakery_settings_app_version_falls_back_to_poundcake_env(monkeypatch) -> None:
    monkeypatch.delenv("BAKERY_APP_VERSION", raising=False)
    monkeypatch.setenv("POUNDCAKE_APP_VERSION", "2.0.999")

    settings = BakerySettings()

    assert settings.app_version == "2.0.999"
