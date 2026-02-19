#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Unit tests for Prometheus rule payload normalization."""

from api.services.prometheus_rule_manager import normalize_rule_data


def test_normalize_rule_data_maps_order_to_alert_and_strips_unknown_fields() -> None:
    payload = {
        "order": "HighCPUUsage",
        "expr": "up == 0",
        "for": "5m",
        "labels": {"severity": "critical"},
        "annotations": {"summary": "test"},
        "query": "should-be-ignored-when-expr-present",
        "unexpected": "drop-me",
    }

    normalized = normalize_rule_data("HighCPUUsage", payload)

    assert normalized["alert"] == "HighCPUUsage"
    assert normalized["expr"] == "up == 0"
    assert normalized["for"] == "5m"
    assert normalized["labels"] == {"severity": "critical"}
    assert normalized["annotations"] == {"summary": "test"}
    assert "order" not in normalized
    assert "query" not in normalized
    assert "unexpected" not in normalized


def test_normalize_rule_data_sets_alert_when_missing() -> None:
    payload = {"expr": "up == 0"}

    normalized = normalize_rule_data("NodeDown", payload)

    assert normalized["alert"] == "NodeDown"
    assert normalized["expr"] == "up == 0"


def test_normalize_rule_data_preserves_record_rules() -> None:
    payload = {"record": "job:http_requests:sum", "expr": "sum(rate(http_requests_total[5m]))"}

    normalized = normalize_rule_data("IgnoredForRecord", payload)

    assert normalized["record"] == "job:http_requests:sum"
    assert "alert" not in normalized
