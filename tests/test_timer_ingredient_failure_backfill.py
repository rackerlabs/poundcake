"""Regression tests for ingredient status backfill on workflow failure."""

from __future__ import annotations

import pytest

import kitchen.timer as timer


class _Resp:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def test_mark_pending_ingredients_failed_backfills_only_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bulk_payloads: list[dict] = []

    ingredients = [
        {
            "recipe_ingredient_id": 1,
            "task_key": "step_1_local",
            "execution_status": "pending",
            "completed_at": None,
        },
        {
            "recipe_ingredient_id": 2,
            "task_key": "step_2_local",
            "execution_status": "succeeded",
            "completed_at": "2026-03-02T00:00:00+00:00",
        },
        {
            "recipe_ingredient_id": 3,
            "task_key": "step_3_local",
            "execution_status": "failed",
            "completed_at": "2026-03-02T00:00:00+00:00",
        },
    ]

    def _request(method: str, url: str, **kwargs):
        if method == "GET" and str(url).endswith("/dishes/2/ingredients"):
            return _Resp(200, ingredients)
        if method == "POST" and str(url).endswith("/dishes/2/ingredients/bulk"):
            bulk_payloads.append(kwargs.get("json") or {})
            return _Resp(200, {"updated": 1})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)

    timer._mark_pending_ingredients_failed(2, "REQ-2", "missing workflow file")

    assert len(bulk_payloads) == 1
    items = bulk_payloads[0]["items"]
    assert len(items) == 1
    assert items[0]["recipe_ingredient_id"] == 1
    assert items[0]["task_key"] == "step_1_local"
    assert items[0]["execution_status"] == "failed"
    assert items[0]["error_message"] == "missing workflow file"
    assert items[0]["completed_at"]


def test_mark_pending_ingredients_failed_skips_when_no_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_bulk = False

    ingredients = [
        {
            "recipe_ingredient_id": 2,
            "task_key": "step_2_local",
            "execution_status": "succeeded",
            "completed_at": "2026-03-02T00:00:00+00:00",
        }
    ]

    def _request(method: str, url: str, **kwargs):
        nonlocal called_bulk
        if method == "GET" and str(url).endswith("/dishes/3/ingredients"):
            return _Resp(200, ingredients)
        if method == "POST" and str(url).endswith("/dishes/3/ingredients/bulk"):
            called_bulk = True
            return _Resp(200, {"updated": 0})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(timer, "request_with_retry_sync", _request)

    timer._mark_pending_ingredients_failed(3, "REQ-3", "failure")

    assert called_bulk is False
