from pathlib import Path


def _auth_source() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "api/api/auth.py").read_text(encoding="utf-8")


def test_auth_defines_request_secure_helper() -> None:
    source = _auth_source()
    assert "def _request_is_secure(request: Request) -> bool:" in source
    assert 'request.headers.get("x-forwarded-proto", "")' in source
    assert 'return request.url.scheme.lower() == "https"' in source


def test_login_cookie_secure_flag_is_request_aware() -> None:
    source = _auth_source()
    assert "secure=_request_is_secure(request)," in source
