from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.services import dishwasher_service


class _SessionContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_sync_stackstorm_includes_bootstrap_catalog_stats_when_marked(
    monkeypatch, tmp_path
) -> None:
    mock_db = AsyncMock()
    monkeypatch.setattr(dishwasher_service, "SessionLocal", lambda: _SessionContext(mock_db))
    monkeypatch.setattr(
        dishwasher_service,
        "get_action_manager",
        lambda: type(
            "Manager",
            (),
            {
                "list_non_orquesta_actions": AsyncMock(return_value=[]),
                "list_orquesta_actions": AsyncMock(return_value=[]),
            },
        )(),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_ingredients",
        AsyncMock(return_value={"created": 0, "updated": 0, "pruned": 0}),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_recipes",
        AsyncMock(return_value={"created": 0, "updated": 0}),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_bootstrap_bakery_ingredients",
        AsyncMock(
            return_value={
                "created": 2,
                "updated": 1,
                "skipped": 0,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/ingredients/bakery.yaml",
            }
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_bootstrap_recipe_catalog",
        AsyncMock(
            return_value={
                "created": 3,
                "updated": 2,
                "skipped": 1,
                "processed": 6,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/recipes",
            }
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "bootstrap_ingredients_file": "catalog.yaml",
                "bootstrap_recipes_dir": "recipes",
            },
        )(),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "ensure_fallback_recipe",
        AsyncMock(return_value=None),
    )

    marker = tmp_path / "bootstrap.done"
    monkeypatch.setattr(dishwasher_service, "BOOTSTRAP_DONE_FILE", str(marker))

    stats = await dishwasher_service.sync_stackstorm(mark_bootstrap=True)

    assert stats["ingredients"] == {"created": 0, "updated": 0, "pruned": 0}
    assert stats["recipes"] == {"created": 0, "updated": 0}
    assert stats["bootstrap_catalog"]["ingredients"]["created"] == 2
    assert stats["bootstrap_catalog"]["recipes"]["created"] == 3
    assert stats["bootstrap_marked"] is True
    assert marker.exists()


@pytest.mark.asyncio
async def test_sync_stackstorm_skips_bootstrap_catalog_when_not_marked(monkeypatch) -> None:
    mock_db = AsyncMock()
    monkeypatch.setattr(dishwasher_service, "SessionLocal", lambda: _SessionContext(mock_db))
    monkeypatch.setattr(
        dishwasher_service,
        "get_action_manager",
        lambda: type(
            "Manager",
            (),
            {
                "list_non_orquesta_actions": AsyncMock(return_value=[]),
                "list_orquesta_actions": AsyncMock(return_value=[]),
            },
        )(),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_ingredients",
        AsyncMock(return_value={"created": 0, "updated": 0, "pruned": 0}),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_recipes",
        AsyncMock(return_value={"created": 0, "updated": 0}),
    )
    upsert_ingredients_catalog = AsyncMock()
    upsert_recipes_catalog = AsyncMock()
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_bootstrap_bakery_ingredients",
        upsert_ingredients_catalog,
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_bootstrap_recipe_catalog",
        upsert_recipes_catalog,
    )

    stats = await dishwasher_service.sync_stackstorm(mark_bootstrap=False)

    assert stats["bootstrap_catalog"]["ingredients"]["created"] == 0
    assert stats["bootstrap_catalog"]["ingredients"]["errors"] == 0
    assert stats["bootstrap_catalog"]["recipes"]["created"] == 0
    assert stats["bootstrap_catalog"]["recipes"]["errors"] == 0
    assert "bootstrap_marked" not in stats
    upsert_ingredients_catalog.assert_not_called()
    upsert_recipes_catalog.assert_not_called()
