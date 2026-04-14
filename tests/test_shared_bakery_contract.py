from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.bakery_contract import (
    CollectionJobClaimResponse,
    CollectionJobCompleteRequest,
    CollectionJobCreateRequest,
    CommunicationAcceptedResponse,
    CommunicationCloseRequest,
    CommunicationNotifyRequest,
    CommunicationOpenRequest,
    MonitorHeartbeatRequest,
    MonitorHeartbeatResponse,
    MonitorRegistrationRequest,
    MonitorRouteCatalogEntry,
)


def test_communication_open_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CommunicationOpenRequest.model_validate(
            {
                "title": "Disk alert",
                "description": "details",
                "unexpected": "boom",
            }
        )


def test_communication_notify_request_coalesces_message_and_comment() -> None:
    payload = CommunicationNotifyRequest.model_validate({"comment": "manual action required"})

    assert payload.message == "manual action required"
    assert payload.comment == "manual action required"


def test_communication_open_request_accepts_managed_payload_fields() -> None:
    payload = CommunicationOpenRequest.model_validate(
        {
            "title": "Alert cleared after successful auto-remediation",
            "description": "PoundCake remediated this alert successfully.",
            "message": "Alert cleared after successful auto-remediation.",
            "source": "poundcake",
            "context": {"route_label": "Rackspace Core"},
        }
    )

    assert payload.message == "Alert cleared after successful auto-remediation."
    assert payload.source == "poundcake"


def test_communication_close_request_accepts_managed_payload_fields() -> None:
    payload = CommunicationCloseRequest.model_validate(
        {
            "title": "Alert resolved",
            "description": "PoundCake is closing this communication.",
            "message": "Alert resolved after successful auto-remediation.",
            "source": "poundcake",
            "state": "closed",
            "context": {"route_label": "Discord"},
        }
    )

    assert payload.title == "Alert resolved"
    assert payload.message == "Alert resolved after successful auto-remediation."
    assert payload.source == "poundcake"


def test_communication_accepted_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CommunicationAcceptedResponse.model_validate(
            {
                "communication_id": "comm-1",
                "operation_id": "op-1",
                "action": "create",
                "status": "queued",
                "created_at": datetime.now(timezone.utc),
                "unexpected": "boom",
            }
        )


def test_monitor_route_catalog_entry_requires_normalized_identity_fields() -> None:
    payload = MonitorRouteCatalogEntry.model_validate(
        {
            "scope": "global",
            "owner_key": "global",
            "route_id": "core-primary",
            "label": "Primary Core",
            "execution_target": "rackspace_core",
            "destination_target": "primary-core",
            "provider_config": {"account_number": "1234567"},
            "enabled": True,
            "outage_enabled": True,
            "position": 1,
        }
    )

    assert payload.route_id == "core-primary"
    assert payload.outage_enabled is True


def test_monitor_heartbeat_response_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MonitorHeartbeatResponse.model_validate(
            {
                "monitor_uuid": "uuid-1",
                "monitor_id": "example/poundcake",
                "status": "healthy",
                "route_sync_required": False,
                "heartbeat_interval_sec": 30,
                "miss_threshold": 5,
                "recorded_at": datetime.now(timezone.utc),
                "unexpected": "boom",
            }
        )


def test_monitor_registration_and_heartbeat_accept_metadata_fields() -> None:
    registration = MonitorRegistrationRequest.model_validate(
        {
            "monitor_id": "example/poundcake",
            "environment_label": "example/poundcake",
            "region": "test-region",
            "cluster_name": "example-cluster",
            "namespace": "example-namespace",
            "release_name": "poundcake",
            "tags": ["shared-bakery", "example"],
        }
    )
    heartbeat = MonitorHeartbeatRequest.model_validate(
        {
            "catalog_hash": "abc123",
            "environment_label": "example/poundcake",
            "region": "test-region",
            "cluster_name": "example-cluster",
            "namespace": "example-namespace",
            "release_name": "poundcake",
            "tags": ["shared-bakery", "example"],
            "details": {"instance_id": "pod-1"},
        }
    )

    assert registration.environment_label == "example/poundcake"
    assert registration.tags == ["shared-bakery", "example"]
    assert heartbeat.cluster_name == "example-cluster"
    assert heartbeat.details["instance_id"] == "pod-1"


def test_collection_job_contracts_validate_expected_shapes() -> None:
    create_request = CollectionJobCreateRequest.model_validate(
        {
            "monitor_uuid": "monitor-1",
            "collector_type": "monitor_diagnostics",
            "parameters": {"include_health": True},
            "reason": "Investigate heartbeat drift",
        }
    )
    claim = CollectionJobClaimResponse.model_validate(
        {
            "available": True,
            "job": {
                "job_id": "job-1",
                "monitor_uuid": "monitor-1",
                "monitor_id": "example/poundcake",
                "collector_type": "monitor_diagnostics",
                "status": "leased",
                "parameters": {"include_health": True},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        }
    )
    completion = CollectionJobCompleteRequest.model_validate(
        {
            "status": "succeeded",
            "result": {"summary": "ok"},
        }
    )

    assert create_request.collector_type == "monitor_diagnostics"
    assert claim.available is True
    assert claim.job is not None
    assert claim.job.job_id == "job-1"
    assert completion.status == "succeeded"
