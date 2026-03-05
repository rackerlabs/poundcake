from __future__ import annotations

from api.validation.execution import (
    validate_execution_request,
    validate_runtime_execution_payload,
)


def test_validate_execution_request_rejects_unknown_engine():
    error = validate_execution_request(
        execution_engine="native",
        execution_target="noop",
        execution_payload={},
        execution_parameters={},
    )
    assert "execution_engine must be one of" in str(error)


def test_validate_execution_request_accepts_valid_stackstorm_payload():
    error = validate_execution_request(
        execution_engine="stackstorm",
        execution_target="poundcake.test",
        execution_payload={"optional": True},
        execution_parameters={"foo": "bar"},
    )
    assert error is None


def test_validate_runtime_execution_payload_requires_bakery_comms_template():
    error = validate_runtime_execution_payload(
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="core",
        execution_payload={"context": {"x": 1}},
        execution_parameters={"operation": "ticket_comment"},
    )
    assert "execution_payload.template must be an object" in str(error)
