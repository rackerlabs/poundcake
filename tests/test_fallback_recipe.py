from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.services.communications_policy import CommunicationRoute
from api.services.fallback_recipe import ensure_fallback_recipe


@pytest.mark.asyncio
async def test_ensure_fallback_recipe_syncs_global_policy_routes() -> None:
    db = AsyncMock()
    routes = [
        CommunicationRoute(
            id="route-1",
            label="Primary teams route",
            execution_target="teams",
            destination_target="ops-alerts",
            provider_config={},
            enabled=True,
            position=1,
        )
    ]
    fallback_recipe = SimpleNamespace(id=22, name="fallback-recipe", enabled=True)

    with (
        patch(
            "api.services.fallback_recipe.get_global_policy_routes",
            new=AsyncMock(return_value=routes),
        ) as get_routes,
        patch(
            "api.services.fallback_recipe.sync_fallback_policy_recipe",
            new=AsyncMock(return_value=fallback_recipe),
        ) as sync_fallback,
    ):
        result = await ensure_fallback_recipe(db, req_id="REQ-FALLBACK")

    assert result is fallback_recipe
    get_routes.assert_awaited_once_with(db)
    sync_fallback.assert_awaited_once()
    await_args = sync_fallback.await_args
    assert await_args is not None
    assert await_args.args[0] is db
    assert await_args.kwargs["routes"] == routes


@pytest.mark.asyncio
async def test_ensure_fallback_recipe_allows_empty_global_policy() -> None:
    db = AsyncMock()
    disabled_recipe = SimpleNamespace(id=22, name="fallback-recipe", enabled=False)

    with (
        patch(
            "api.services.fallback_recipe.get_global_policy_routes",
            new=AsyncMock(return_value=[]),
        ) as get_routes,
        patch(
            "api.services.fallback_recipe.sync_fallback_policy_recipe",
            new=AsyncMock(return_value=disabled_recipe),
        ) as sync_fallback,
    ):
        result = await ensure_fallback_recipe(db, req_id="REQ-EMPTY")

    assert result is disabled_recipe
    get_routes.assert_awaited_once_with(db)
    sync_fallback.assert_awaited_once()
    await_args = sync_fallback.await_args
    assert await_args is not None
    assert await_args.kwargs["routes"] == []
