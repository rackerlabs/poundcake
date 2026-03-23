from __future__ import annotations

from api.services.bakery_payloads import deep_merge_payload, resolve_bakery_payload


def test_resolve_bakery_payload_deep_merges_nested_objects() -> None:
    resolved = resolve_bakery_payload(
        {
            "template": {
                "comment": "base",
                "context": {
                    "labels": {"team": "storage"},
                    "annotations": {"runbook_url": "https://example/runbook"},
                },
            },
            "context": {"labels": {"service": "disk"}},
        },
        runtime_overlay={"context": {"labels": {"cluster": "prod"}}},
    )

    assert resolved["context"]["labels"] == {
        "team": "storage",
        "service": "disk",
        "cluster": "prod",
    }
    assert resolved["context"]["annotations"] == {"runbook_url": "https://example/runbook"}


def test_resolve_bakery_payload_replaces_scalars_and_lists() -> None:
    resolved = resolve_bakery_payload(
        {
            "template": {
                "message": "template message",
                "context": {"labels": ["storage", "infra"]},
            },
            "message": "default override",
        },
        runtime_overlay={"context": {"labels": ["prod"]}},
    )

    assert resolved["message"] == "default override"
    assert resolved["context"]["labels"] == ["prod"]


def test_resolve_bakery_payload_removes_template_key() -> None:
    resolved = resolve_bakery_payload({"template": {"comment": "hello"}})

    assert resolved == {"comment": "hello"}
    assert "template" not in resolved


def test_deep_merge_payload_replaces_non_dict_values() -> None:
    merged = deep_merge_payload({"context": {"labels": {"a": 1}}, "list": [1]}, {"context": 2, "list": [2]})

    assert merged == {"context": 2, "list": [2]}
