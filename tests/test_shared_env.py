"""Unit tests for shared environment parsing helpers."""

from shared.env import env_to_bool


def test_env_to_bool_defaults_for_none() -> None:
    assert env_to_bool(None) is False
    assert env_to_bool(None, default=True) is True


def test_env_to_bool_truthy_values() -> None:
    for value in ("1", "true", "TRUE", " yes ", "On"):
        assert env_to_bool(value) is True


def test_env_to_bool_falsy_values() -> None:
    for value in ("0", "false", "no", "off", "random", " "):
        assert env_to_bool(value) is False
