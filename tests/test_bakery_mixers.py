from types import SimpleNamespace

from bakery.api.mixers import MIXER_ACTIONS, _check_credentials_configured


def test_webhook_mixers_report_configured_when_webhook_url_is_present() -> None:
    teams = SimpleNamespace(webhook_url="https://teams.example/webhook")
    discord = SimpleNamespace(webhook_url="https://discord.example/webhook")

    assert _check_credentials_configured("teams", teams) is True
    assert _check_credentials_configured("discord", discord) is True


def test_webhook_mixers_do_not_report_search_support() -> None:
    assert MIXER_ACTIONS["teams"] == ["create", "update", "close", "comment"]
    assert MIXER_ACTIONS["discord"] == ["create", "update", "close", "comment"]
