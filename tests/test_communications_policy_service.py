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


@pytest.mark.asyncio
async def test_sync_fallback_policy_recipe_noops_when_enabled_routes_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = communications_policy.normalize_routes(
        [
            {
                "id": "route-a",
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
    recipe = SimpleNamespace(
        name="fallback-recipe",
        description="existing",
        enabled=True,
        deleted=False,
        deleted_at=None,
        updated_at=None,
        recipe_ingredients=[],
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(first=recipe))
    db.add = Mock()
    db.flush = AsyncMock()

    replace_steps = AsyncMock()
    monkeypatch.setattr(communications_policy, "replace_recipe_communication_steps", replace_steps)
    monkeypatch.setattr(
        communications_policy,
        "get_recipe_local_routes",
        lambda _recipe: routes,
    )

    result = await communications_policy.sync_fallback_policy_recipe(db, routes=routes)

    assert result is recipe
    replace_steps.assert_not_awaited()


def test_normalize_routes_preserves_provider_config_for_required_targets() -> None:
    routes = communications_policy.normalize_routes(
        [
            {
                "label": "Primary Core",
                "execution_target": "rackspace_core",
                "destination_target": "primary",
                "provider_config": {
                    "account_number": "1234567",
                    "queue": "Example Support",
                    "subcategory": "Monitoring",
                },
                "enabled": True,
                "position": 1,
            }
        ]
    )

    assert routes[0].provider_config["account_number"] == "1234567"


def test_build_recipe_local_policy_step_specs_accepts_pre_normalized_routes() -> None:
    normalized = communications_policy.normalize_routes(
        [
            {
                "label": "Primary Core",
                "execution_target": "rackspace_core",
                "destination_target": "",
                "provider_config": {
                    "account_number": "1234567",
                    "queue": "Example Support",
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


def test_build_fallback_policy_step_specs_notifies_on_clear_without_closing() -> None:
    normalized = communications_policy.normalize_routes(
        [
            {
                "label": "Primary Core",
                "execution_target": "rackspace_core",
                "destination_target": "",
                "provider_config": {
                    "account_number": "1234567",
                    "queue": "Example Support",
                },
                "enabled": True,
                "position": 1,
            }
        ]
    )

    step_specs = communications_policy._build_route_step_specs(
        routes=normalized,
        scope="fallback",
        owner_key="fallback",
        fallback=True,
    )

    assert [item["execution_parameters"]["operation"] for item in step_specs] == ["open", "notify"]
    assert step_specs[1]["run_condition"] == "resolved_after_no_remediation"
    assert "fallback_notify" in step_specs[1]["task_key_template"]
    assert (
        step_specs[1]["execution_payload"]["context"]["semantic_text"]["detail"]
        == "Leaving the communication open for human investigation."
    )


def test_should_seed_route_step_skips_legacy_no_remediation_close() -> None:
    ingredient = SimpleNamespace(
        execution_parameters={"operation": "close"},
        execution_payload={},
        execution_target="rackspace_core",
        destination_target="",
    )
    recipe_ingredient = SimpleNamespace(
        ingredient=ingredient,
        run_condition="resolved_after_no_remediation",
    )

    assert (
        communications_policy.should_seed_route_step(
            recipe_ingredient=recipe_ingredient,
            order=SimpleNamespace(communications=[]),
        )
        is False
    )


def test_get_recipe_local_routes_hydrates_legacy_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        communications_policy,
        "get_settings",
        lambda: SimpleNamespace(
            catch_all_recipe_name="fallback-recipe",
            rackspace_core_default_queue="Example Support",
            rackspace_core_default_subcategory="Monitoring",
        ),
    )

    ingredient = SimpleNamespace(
        execution_engine="bakery",
        execution_purpose="comms",
        execution_target="rackspace_core",
        destination_target="primary",
        task_key_template="legacy.core",
        execution_payload={"context": {"coreAccountID": "1234567"}},
    )
    recipe_step = SimpleNamespace(ingredient=ingredient)
    recipe = SimpleNamespace(recipe_ingredients=[recipe_step], name="filesystem-response")

    routes = communications_policy.get_recipe_local_routes(recipe)

    assert routes[0].provider_config["account_number"] == "1234567"
    assert routes[0].provider_config["queue"] == "Example Support"
