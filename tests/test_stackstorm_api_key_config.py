"""Regression tests for StackStorm API key config resolution."""

from __future__ import annotations

from api.core.config import Settings


def test_get_stackstorm_api_key_uses_explicit_st2_api_key_file(
    monkeypatch,
    tmp_path,
) -> None:
    key_file = tmp_path / "custom_st2_api_key"
    key_file.write_text("runtime-key\n", encoding="utf-8")

    monkeypatch.delenv("POUNDCAKE_STACKSTORM_API_KEY", raising=False)
    monkeypatch.setenv("ST2_API_KEY_FILE", str(key_file))

    settings = Settings()

    assert settings.get_stackstorm_api_key() == "runtime-key"


def test_get_stackstorm_api_key_uses_secret_mount_path_when_env_is_empty(
    monkeypatch,
    tmp_path,
) -> None:
    mounted_key = tmp_path / "st2_api_key"
    mounted_key.write_text("mounted-key\n", encoding="utf-8")

    monkeypatch.setenv("POUNDCAKE_STACKSTORM_API_KEY", "")
    monkeypatch.setenv("ST2_API_KEY_FILE", str(mounted_key))

    settings = Settings()

    assert settings.get_stackstorm_api_key() == "mounted-key"
