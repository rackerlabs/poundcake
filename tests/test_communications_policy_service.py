from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import api.services.communications_policy as communications_policy


class _ScalarResult:
    def __init__(self, first=None):
        self._first = first

    def unique(self):
        return self

    def scalars(self):
        return self

    def first(self):
        return self._first


def _guard_post_init_recipe_ingredients_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    original_init = communications_policy.Recipe.__init__
    original_setattr = communications_policy.Recipe.__setattr__

    def tracking_init(self, *args, **kwargs):
        object.__setattr__(
            self,
            "_recipe_ingredients_seeded_in_constructor",
            "recipe_ingredients" in kwargs,
        )
        return original_init(self, *args, **kwargs)

    def tracking_setattr(self, name, value):
        if name == "recipe_ingredients" and not getattr(
            self, "_recipe_ingredients_seeded_in_constructor", False
        ):
            raise AssertionError("recipe_ingredients must be seeded during construction")
        return original_setattr(self, name, value)

    monkeypatch.setattr(communications_policy.Recipe, "__init__", tracking_init, raising=False)
    monkeypatch.setattr(
        communications_policy.Recipe,
        "__setattr__",
        tracking_setattr,
        raising=False,
    )


@pytest.mark.asyncio
async def test_sync_global_policy_routes_first_create_seeds_empty_recipe_relationship(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _guard_post_init_recipe_ingredients_assignment(monkeypatch)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(first=None))
    db.add = Mock()
    db.flush = AsyncMock()

    replace_steps = AsyncMock()
    monkeypatch.setattr(communications_policy, "replace_recipe_communication_steps", replace_steps)

    routes = await communications_policy.sync_global_policy_routes(
        db,
        routes=[
            {
                "label": "Discord",
                "execution_target": "discord",
                "destination_target": "",
                "enabled": True,
                "position": 1,
            }
        ],
    )

    added_recipe = db.add.call_args_list[0].args[0]
    assert added_recipe.name == communications_policy.MANAGED_RECIPE_NAME_GLOBAL
    assert added_recipe.recipe_ingredients == []
    assert len(routes) == 1
    assert routes[0].execution_target == "discord"
    replace_steps.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_fallback_policy_recipe_first_create_seeds_empty_recipe_relationship(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _guard_post_init_recipe_ingredients_assignment(monkeypatch)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(first=None))
    db.add = Mock()
    db.flush = AsyncMock()

    replace_steps = AsyncMock()
    monkeypatch.setattr(communications_policy, "replace_recipe_communication_steps", replace_steps)

    recipe = await communications_policy.sync_fallback_policy_recipe(db, routes=[])

    assert recipe is not None
    assert recipe.name == "fallback-recipe"
    assert recipe.enabled is False
    assert recipe.recipe_ingredients == []
    replace_steps.assert_awaited_once_with(db, recipe=recipe, step_specs=[])


def test_normalize_routes_preserves_provider_config_for_required_targets() -> None:
    routes = communications_policy.normalize_routes(
        [
            {
                "label": "Primary Core",
                "execution_target": "rackspace_core",
                "destination_target": "primary",
                "provider_config": {
                    "account_number": "1781738",
                    "queue": "CloudBuilders Support",
                    "subcategory": "Monitoring",
                },
                "enabled": True,
                "position": 1,
            }
        ]
    )

    assert routes[0].provider_config["account_number"] == "1781738"


def test_build_recipe_local_policy_step_specs_accepts_pre_normalized_routes() -> None:
    normalized = communications_policy.normalize_routes(
        [
            {
                "label": "Primary Core",
                "execution_target": "rackspace_core",
                "destination_target": "",
                "provider_config": {
                    "account_number": "1781738",
                    "queue": "CloudBuilders Support",
                    "subcategory": "Monitoring",
                },
                "enabled": True,
                "position": 1,
            }
        ]
    )

    routes, step_specs = communications_policy.build_recipe_local_policy_step_specs(
        recipe_id=42,
        routes=normalized,
    )

    assert len(routes) == 1
    assert routes[0].execution_target == "rackspace_core"
    assert step_specs[0]["execution_target"] == "rackspace_core"
    assert step_specs[0]["execution_parameters"]["operation"] == "open"
    assert "template" in step_specs[0]["execution_payload"]
    assert step_specs[0]["execution_payload"]["template"]["context"]["provider_config"] == {
        "account_number": "1781738",
        "queue": "CloudBuilders Support",
        "subcategory": "Monitoring",
    }


def test_get_recipe_local_routes_hydrates_legacy_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        communications_policy,
        "get_settings",
        lambda: SimpleNamespace(
            catch_all_recipe_name="fallback-recipe",
            rackspace_core_default_queue="CloudBuilders Support",
            rackspace_core_default_subcategory="Monitoring",
        ),
    )

    ingredient = SimpleNamespace(
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="rackspace_core",
        destination_target="primary",
        task_key_template="legacy.core",
        execution_payload={"context": {"coreAccountID": "1781738"}},
    )
    recipe_step = SimpleNamespace(ingredient=ingredient)
    recipe = SimpleNamespace(recipe_ingredients=[recipe_step], name="filesystem-response")

    routes = communications_policy.get_recipe_local_routes(recipe)

    assert routes[0].provider_config["account_number"] == "1781738"
    assert routes[0].provider_config["queue"] == "CloudBuilders Support"
