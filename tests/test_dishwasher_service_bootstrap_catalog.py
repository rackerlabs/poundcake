from __future__ import annotations

from types import SimpleNamespace
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
        "upsert_bootstrap_ingredient_catalogs",
        AsyncMock(
            return_value={
                "created": 2,
                "updated": 1,
                "skipped": 0,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/ingredients",
                "files_scanned": 28,
            }
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "refresh_bootstrap_recipe_catalog_from_remote",
        lambda **_kwargs: {
            "enabled": True,
            "refreshed": True,
            "files_scanned": 4,
            "rules_discovered": 3,
            "generated": 0,
            "errors": 0,
            "error_messages": [],
            "source": "/app/bootstrap/recipes",
            "repo_url": "https://github.com/example/monitoring-rules.git",
            "branch": "main",
            "path": "alerts",
        },
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
                "conflicts": 0,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/recipes",
            }
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_ingredients_dir="catalogs",
            bootstrap_ingredients_file="",
            bootstrap_recipes_dir="recipes",
            bootstrap_remote_sync_enabled=True,
            bootstrap_rules_repo_url="https://github.com/example/monitoring-rules.git",
            bootstrap_rules_branch="main",
            bootstrap_rules_path="alerts",
        ),
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
    assert stats["bootstrap_catalog"]["ingredients"]["files_scanned"] == 28
    assert stats["bootstrap_catalog"]["recipes"]["created"] == 3
    assert stats["bootstrap_catalog"]["remote_recipes"]["refreshed"] is True
    assert stats["bootstrap_marked"] is True
    assert marker.exists()


@pytest.mark.asyncio
async def test_sync_stackstorm_refreshes_remote_bootstrap_catalog_on_periodic_runs(
    monkeypatch,
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
    upsert_ingredients_catalog = AsyncMock(
        return_value={
            "created": 1,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "error_messages": [],
            "source": "/app/bootstrap/ingredients",
            "files_scanned": 1,
        }
    )
    upsert_recipes_catalog = AsyncMock(
        return_value={
            "created": 0,
            "updated": 1,
            "skipped": 0,
            "processed": 1,
            "conflicts": 0,
            "errors": 0,
            "error_messages": [],
            "source": "/app/bootstrap/recipes",
        }
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_bootstrap_ingredient_catalogs",
        upsert_ingredients_catalog,
    )
    monkeypatch.setattr(
        dishwasher_service,
        "upsert_bootstrap_recipe_catalog",
        upsert_recipes_catalog,
    )
    monkeypatch.setattr(
        dishwasher_service,
        "refresh_bootstrap_recipe_catalog_from_remote",
        lambda **_kwargs: {
            "enabled": True,
            "refreshed": True,
            "files_scanned": 6,
            "rules_discovered": 4,
            "generated": 0,
            "errors": 0,
            "error_messages": [],
            "source": "/app/bootstrap/recipes",
            "repo_url": "https://github.com/example/monitoring-rules.git",
            "branch": "main",
            "path": "alerts",
        },
    )
    monkeypatch.setattr(
        dishwasher_service,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_ingredients_dir="catalogs",
            bootstrap_ingredients_file="",
            bootstrap_recipes_dir="recipes",
            bootstrap_remote_sync_enabled=True,
            bootstrap_rules_repo_url="https://github.com/example/monitoring-rules.git",
            bootstrap_rules_branch="main",
            bootstrap_rules_path="alerts",
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "ensure_fallback_recipe",
        AsyncMock(return_value=None),
    )

    stats = await dishwasher_service.sync_stackstorm(mark_bootstrap=False)

    assert stats["bootstrap_catalog"]["ingredients"]["created"] == 1
    assert stats["bootstrap_catalog"]["recipes"]["updated"] == 1
    assert stats["bootstrap_catalog"]["remote_recipes"]["generated"] == 0
    assert "bootstrap_marked" not in stats
    upsert_ingredients_catalog.assert_called_once()
    upsert_recipes_catalog.assert_called_once()


@pytest.mark.asyncio
async def test_sync_stackstorm_preserves_periodic_recipes_when_remote_refresh_fails(
    monkeypatch,
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
        "upsert_bootstrap_ingredient_catalogs",
        AsyncMock(
            return_value={
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/ingredients",
                "files_scanned": 1,
            }
        ),
    )
    recipe_catalog = AsyncMock(
        return_value={
            "created": 0,
            "updated": 0,
            "skipped": 1,
            "processed": 1,
            "conflicts": 0,
            "errors": 0,
            "error_messages": [],
            "source": "/app/bootstrap/recipes",
        }
    )
    monkeypatch.setattr(dishwasher_service, "upsert_bootstrap_recipe_catalog", recipe_catalog)
    monkeypatch.setattr(
        dishwasher_service,
        "refresh_bootstrap_recipe_catalog_from_remote",
        lambda **_kwargs: (_ for _ in ()).throw(
            dishwasher_service.BootstrapRemoteRecipeSyncError("boom")
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_ingredients_dir="catalogs",
            bootstrap_ingredients_file="",
            bootstrap_recipes_dir="recipes",
            bootstrap_remote_sync_enabled=True,
            bootstrap_rules_repo_url="https://github.com/example/monitoring-rules.git",
            bootstrap_rules_branch="main",
            bootstrap_rules_path="alerts",
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "ensure_fallback_recipe",
        AsyncMock(return_value=None),
    )

    stats = await dishwasher_service.sync_stackstorm(mark_bootstrap=False)

    assert stats["bootstrap_catalog"]["remote_recipes"]["errors"] == 1
    assert stats["bootstrap_catalog"]["recipes"]["processed"] == 1
    recipe_catalog.assert_called_once()


@pytest.mark.asyncio
async def test_sync_stackstorm_fails_bootstrap_when_remote_refresh_fails(monkeypatch) -> None:
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
        "upsert_bootstrap_ingredient_catalogs",
        AsyncMock(
            return_value={
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/ingredients",
                "files_scanned": 1,
            }
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "refresh_bootstrap_recipe_catalog_from_remote",
        lambda **_kwargs: (_ for _ in ()).throw(
            dishwasher_service.BootstrapRemoteRecipeSyncError("boom")
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_ingredients_dir="catalogs",
            bootstrap_ingredients_file="",
            bootstrap_recipes_dir="recipes",
            bootstrap_remote_sync_enabled=True,
            bootstrap_rules_repo_url="https://github.com/example/monitoring-rules.git",
            bootstrap_rules_branch="main",
            bootstrap_rules_path="alerts",
        ),
    )

    with pytest.raises(dishwasher_service.BootstrapRemoteRecipeSyncError):
        await dishwasher_service.sync_stackstorm(mark_bootstrap=True)


@pytest.mark.asyncio
async def test_sync_stackstorm_skips_remote_refresh_without_repo_url(monkeypatch) -> None:
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
        "upsert_bootstrap_ingredient_catalogs",
        AsyncMock(
            return_value={
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 0,
                "error_messages": [],
                "source": "/app/bootstrap/ingredients",
                "files_scanned": 0,
            }
        ),
    )
    refresh_remote = AsyncMock()
    monkeypatch.setattr(
        dishwasher_service,
        "refresh_bootstrap_recipe_catalog_from_remote",
        refresh_remote,
    )
    recipe_catalog = AsyncMock(
        return_value={
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "processed": 0,
            "conflicts": 0,
            "errors": 0,
            "error_messages": [],
            "source": "/app/bootstrap/recipes",
        }
    )
    monkeypatch.setattr(dishwasher_service, "upsert_bootstrap_recipe_catalog", recipe_catalog)
    monkeypatch.setattr(
        dishwasher_service,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_ingredients_dir="catalogs",
            bootstrap_ingredients_file="",
            bootstrap_recipes_dir="recipes",
            bootstrap_remote_sync_enabled=True,
            bootstrap_rules_repo_url="",
            bootstrap_rules_branch="main",
            bootstrap_rules_path="alerts",
        ),
    )
    monkeypatch.setattr(
        dishwasher_service,
        "ensure_fallback_recipe",
        AsyncMock(return_value=None),
    )

    stats = await dishwasher_service.sync_stackstorm(mark_bootstrap=False)

    assert stats["bootstrap_catalog"]["remote_recipes"]["enabled"] is False
    assert stats["bootstrap_catalog"]["remote_recipes"]["refreshed"] is False
    refresh_remote.assert_not_called()
    recipe_catalog.assert_not_called()
