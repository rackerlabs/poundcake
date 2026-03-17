from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "ui" / "src" / "App.tsx"


def test_login_page_only_shows_auth0_button_for_browser_capable_providers() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert 'provider.name === "auth0" && provider.browser_login' in content
    assert "No browser-capable login providers are configured right now." in content


def test_access_page_describes_split_browser_and_device_provider_modes() -> None:
    content = APP_TSX.read_text(encoding="utf-8")
    assert "Browser login and CLI device login enabled." in content
    assert "No external auth providers are enabled yet." in content
