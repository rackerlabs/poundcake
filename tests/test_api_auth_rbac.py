from __future__ import annotations

from api.services.auth_service import (
    AuthContext,
    ensure_request_authorized,
    is_authorized_for_role,
    request_role_requirement,
)


def _human_context(role: str, *, is_superuser: bool = False) -> AuthContext:
    return AuthContext(
        provider="auth0",
        subject_id="user-1",
        username="alice",
        display_name="Alice",
        groups=["monitoring"],
        role=role,  # type: ignore[arg-type]
        principal_type="user",
        is_superuser=is_superuser,
        permissions=["read"],
    )


def test_request_role_requirement_maps_expected_routes() -> None:
    assert request_role_requirement("/api/v1/orders", "GET") == "reader"
    assert request_role_requirement("/api/v1/orders", "POST") == "service"
    assert request_role_requirement("/api/v1/suppressions/12/cancel", "POST") == "operator"
    assert request_role_requirement("/api/v1/prometheus/reload", "POST") == "operator"
    assert request_role_requirement("/api/v1/communications/policy", "PUT") == "admin"
    assert request_role_requirement("/api/v1/auth/providers", "GET") is None


def test_service_role_can_read_but_not_modify_human_config() -> None:
    service = AuthContext(
        provider="service",
        subject_id="service-token",
        username="service",
        display_name="Internal Service",
        groups=[],
        role="service",
        principal_type="service",
        permissions=["read", "service"],
    )

    assert is_authorized_for_role(service, "reader") is True
    assert is_authorized_for_role(service, "operator") is False
    assert is_authorized_for_role(service, "admin") is False
    assert is_authorized_for_role(service, "service") is True


def test_operator_and_admin_role_checks() -> None:
    reader = _human_context("reader")
    operator = _human_context("operator")
    admin = _human_context("admin")
    superuser = _human_context("admin", is_superuser=True)

    assert is_authorized_for_role(reader, "reader") is True
    assert is_authorized_for_role(reader, "operator") is False
    assert is_authorized_for_role(operator, "operator") is True
    assert is_authorized_for_role(operator, "admin") is False
    assert is_authorized_for_role(admin, "admin") is True
    assert is_authorized_for_role(superuser, "admin") is True


def test_request_authorization_uses_role_matrix() -> None:
    operator = _human_context("operator")
    ensure_request_authorized(operator, "/api/v1/recipes/1", "PUT")

    admin = _human_context("admin")
    ensure_request_authorized(admin, "/api/v1/communications/policy", "PUT")
