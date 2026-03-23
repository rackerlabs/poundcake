"""Tests for recipe workflow editing APIs."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models.models import Ingredient, Recipe, RecipeIngredient


class ScalarResult:
    def __init__(self, first=None, all_=None):
        self._first = first
        self._all = all_ or []

    def scalars(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all

    def unique(self):
        return self


class _BeginContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _TrackingBeginContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db._in_begin_context = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.db._in_begin_context = False
        return None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db():
    with patch("api.core.database.SessionLocal") as mock_session:
        db = AsyncMock()
        db.add = Mock()
        db.begin = Mock(return_value=_BeginContext())
        db.flush = AsyncMock(return_value=None)
        db.refresh = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield db


def _make_recipe() -> Recipe:
    now = datetime.now(timezone.utc)
    recipe = Recipe(
        id=9,
        name="node-filesystem-workflow",
        description="Disk response",
        enabled=True,
        clear_timeout_sec=300,
        created_at=now,
        updated_at=now,
        deleted=False,
        deleted_at=None,
    )
    recipe.recipe_ingredients = [
        RecipeIngredient(
            id=1,
            recipe_id=recipe.id,
            ingredient_id=11,
            step_order=1,
            on_success="continue",
            parallel_group=0,
            depth=0,
            execution_parameters_override=None,
            run_phase="firing",
            run_condition="always",
        )
    ]
    return recipe


def _make_ingredient(ingredient_id: int, target: str) -> Ingredient:
    now = datetime.now(timezone.utc)
    return Ingredient(
        id=ingredient_id,
        execution_target=target,
        destination_target="ops-alerts" if target == "teams" else "",
        task_key_template=f"{target}.dispatch",
        execution_engine="bakery" if target == "teams" else "stackstorm",
        execution_purpose="comms" if target == "teams" else "remediation",
        execution_id=None,
        execution_payload=None,
        execution_parameters={"operation": "notify"} if target == "teams" else {},
        is_default=False,
        is_blocking=True,
        expected_duration_sec=60,
        timeout_duration_sec=300,
        retry_count=0,
        retry_delay=5,
        on_failure="stop",
        created_at=now,
        updated_at=now,
        deleted=False,
        deleted_at=None,
    )


def test_recipe_update_replaces_workflow_steps(client, mock_db):
    recipe = _make_recipe()
    ingredient_one = _make_ingredient(11, "teams")
    ingredient_two = _make_ingredient(12, "rackspace_core")
    global_route = SimpleNamespace(
        id="global-primary",
        label="Primary teams route",
        execution_target="teams",
        destination_target="ops-alerts",
        provider_config={},
        enabled=True,
        position=1,
    )

    def _add(obj):
        if isinstance(obj, RecipeIngredient):
            recipe.recipe_ingredients.append(obj)

    async def _flush():
        for index, item in enumerate(recipe.recipe_ingredients, start=1):
            if not item.id:
                item.id = index + 100

    mock_db.add = Mock(side_effect=_add)
    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=recipe),
            ScalarResult(all_=[ingredient_one, ingredient_two]),
            ScalarResult(first=recipe),
        ]
    )

    with (
        patch("api.api.recipes.global_policy_configured", new=AsyncMock(return_value=True)),
        patch(
            "api.api.recipes.get_global_policy_routes", new=AsyncMock(return_value=[global_route])
        ),
        patch("api.api.recipes.delete_recipe_ingredients_safely", new=AsyncMock(return_value=None)),
    ):
        response = client.put(
            "/api/v1/recipes/9",
            json={
                "description": "Updated workflow",
                "recipe_ingredients": [
                    {
                        "ingredient_id": 12,
                        "step_order": 1,
                        "on_success": "continue",
                        "parallel_group": 0,
                        "depth": 0,
                        "execution_parameters_override": {"operation": "open"},
                        "run_phase": "firing",
                        "run_condition": "always",
                    },
                    {
                        "ingredient_id": 11,
                        "step_order": 2,
                        "on_success": "continue",
                        "parallel_group": 0,
                        "depth": 0,
                        "execution_parameters_override": {"operation": "notify"},
                        "run_phase": "resolving",
                        "run_condition": "resolved_after_success",
                    },
                ],
            },
        )

    assert response.status_code == 200
    assert recipe.description == "Updated workflow"
    assert [item.ingredient_id for item in recipe.recipe_ingredients] == [12, 11]
    assert recipe.recipe_ingredients[1].run_phase == "resolving"
    assert response.json()["communications"]["effective_source"] == "global"


def test_recipe_update_applies_default_step_fields_when_optionals_are_omitted(client, mock_db):
    recipe = _make_recipe()
    ingredient = _make_ingredient(12, "core.noop")
    global_route = SimpleNamespace(
        id="global-primary",
        label="Primary teams route",
        execution_target="teams",
        destination_target="ops-alerts",
        provider_config={},
        enabled=True,
        position=1,
    )

    def _add(obj):
        if isinstance(obj, RecipeIngredient):
            recipe.recipe_ingredients.append(obj)

    async def _flush():
        for index, item in enumerate(recipe.recipe_ingredients, start=1):
            if not item.id:
                item.id = index + 100

    mock_db.add = Mock(side_effect=_add)
    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=recipe),
            ScalarResult(all_=[ingredient]),
            ScalarResult(first=recipe),
        ]
    )

    with (
        patch("api.api.recipes.global_policy_configured", new=AsyncMock(return_value=True)),
        patch(
            "api.api.recipes.get_global_policy_routes", new=AsyncMock(return_value=[global_route])
        ),
        patch("api.api.recipes.delete_recipe_ingredients_safely", new=AsyncMock(return_value=None)),
    ):
        response = client.patch(
            "/api/v1/recipes/9",
            json={
                "recipe_ingredients": [
                    {
                        "ingredient_id": 12,
                        "step_order": 1,
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert len(recipe.recipe_ingredients) == 1
    step = recipe.recipe_ingredients[0]
    assert step.ingredient_id == 12
    assert step.on_success == "continue"
    assert step.parallel_group == 0
    assert step.depth == 0
    assert step.execution_parameters_override is None
    assert step.run_phase == "both"
    assert step.run_condition == "always"
    assert response.json()["communications"]["effective_source"] == "global"


def test_recipe_update_returns_404_when_workflow_references_missing_action(client, mock_db):
    recipe = _make_recipe()
    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=recipe),
            ScalarResult(all_=[]),
        ]
    )

    response = client.patch(
        "/api/v1/recipes/9",
        json={
            "recipe_ingredients": [
                {
                    "ingredient_id": 999,
                    "step_order": 1,
                    "on_success": "continue",
                    "parallel_group": 0,
                    "depth": 0,
                    "execution_parameters_override": None,
                    "run_phase": "firing",
                    "run_condition": "always",
                }
            ]
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Missing ingredients: [999]"


def test_recipe_create_enabled_without_global_or_local_communications_returns_400(client, mock_db):
    ingredient = _make_ingredient(12, "rackspace_core")
    mock_db.execute = AsyncMock(return_value=ScalarResult(all_=[ingredient]))

    with patch("api.api.recipes.global_policy_configured", new=AsyncMock(return_value=False)):
        response = client.post(
            "/api/v1/recipes/",
            json={
                "name": "filesystem-response",
                "description": "Example workflow",
                "enabled": True,
                "clear_timeout_sec": 300,
                "communications": {"mode": "inherit", "routes": []},
                "recipe_ingredients": [
                    {
                        "ingredient_id": 12,
                        "step_order": 1,
                        "on_success": "continue",
                        "parallel_group": 0,
                        "depth": 0,
                        "execution_parameters_override": None,
                        "run_phase": "firing",
                        "run_condition": "always",
                    }
                ],
            },
        )

    assert response.status_code == 400
    assert "global communications policy" in response.json()["detail"]


def test_recipe_create_validates_ingredients_inside_transaction(client, mock_db):
    mock_db.begin = Mock(return_value=_TrackingBeginContext(mock_db))
    created_recipe: dict[str, Recipe] = {}
    queued_steps: list[RecipeIngredient] = []

    def _add(obj):
        if isinstance(obj, Recipe) and obj.id is None:
            created_recipe["recipe"] = obj
        if isinstance(obj, RecipeIngredient):
            queued_steps.append(obj)

    async def _flush():
        recipe_obj = created_recipe.get("recipe")
        if recipe_obj is not None and recipe_obj.id is None:
            recipe_obj.id = 42

    mock_db.add = Mock(side_effect=_add)
    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=None),
            ScalarResult(first=SimpleNamespace(id=42, name="filesystem-response")),
        ]
    )

    async def _validate_ingredients(db, *, step_specs):
        assert getattr(db, "_in_begin_context", False) is True
        assert step_specs[0]["ingredient_id"] == 12

    serialized_recipe = {
        "id": 42,
        "name": "filesystem-response",
        "description": "Example workflow",
        "enabled": True,
        "clear_timeout_sec": 300,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "deleted": False,
        "deleted_at": None,
        "recipe_ingredients": [],
        "communications": {
            "mode": "local",
            "effective_source": "local",
            "routes": [
                {
                    "id": "route-1",
                    "label": "Rackspace Core",
                    "execution_target": "rackspace_core",
                    "destination_target": "",
                    "provider_config": {"account_number": "1781738"},
                    "enabled": True,
                    "position": 1,
                }
            ],
        },
    }

    with (
        patch("api.api.recipes._validate_ingredient_ids", new=_validate_ingredients),
        patch("api.api.recipes._validate_effective_communications", new=AsyncMock()),
        patch(
            "api.api.recipes.build_recipe_local_policy_step_specs",
            return_value=([], []),
        ),
        patch("api.api.recipes._serialize_recipe", new=AsyncMock(return_value=serialized_recipe)),
    ):
        response = client.post(
            "/api/v1/recipes/",
            json={
                "name": "filesystem-response",
                "description": "Example workflow",
                "enabled": True,
                "clear_timeout_sec": 300,
                "communications": {
                    "mode": "local",
                    "routes": [
                        {
                            "label": "Rackspace Core",
                            "execution_target": "rackspace_core",
                            "destination_target": "",
                            "provider_config": {"account_number": "1781738"},
                            "enabled": True,
                            "position": 1,
                        }
                    ],
                },
                "recipe_ingredients": [
                    {
                        "ingredient_id": 12,
                        "step_order": 1,
                        "on_success": "continue",
                        "parallel_group": 0,
                        "depth": 0,
                        "execution_parameters_override": None,
                        "run_phase": "firing",
                        "run_condition": "always",
                    }
                ],
            },
        )

    assert response.status_code == 201
    assert response.json()["id"] == 42
    assert len(queued_steps) == 1
    assert queued_steps[0].recipe_id == 42
    assert queued_steps[0].ingredient_id == 12


def test_recipe_create_local_communications_use_created_managed_ingredient_ids(client, mock_db):
    mock_db.begin = Mock(return_value=_TrackingBeginContext(mock_db))
    created_recipe: dict[str, Recipe] = {}
    created_managed_ingredients: list[Ingredient] = []
    queued_steps: list[RecipeIngredient] = []

    def _add(obj):
        if isinstance(obj, Recipe) and obj.id is None:
            created_recipe["recipe"] = obj
        elif isinstance(obj, Ingredient):
            created_managed_ingredients.append(obj)
        elif isinstance(obj, RecipeIngredient):
            queued_steps.append(obj)

    async def _flush():
        recipe_obj = created_recipe.get("recipe")
        if recipe_obj is not None and recipe_obj.id is None:
            recipe_obj.id = 42
        next_id = 200
        for ingredient in created_managed_ingredients:
            if ingredient.id is None:
                ingredient.id = next_id
                next_id += 1

    mock_db.add = Mock(side_effect=_add)
    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=None),
            ScalarResult(first=SimpleNamespace(id=42, name="filesystem-response")),
        ]
    )

    managed_spec = {
        "execution_target": "rackspace_core",
        "destination_target": "",
        "task_key_template": "pcmcomms.recipe.42.route-1.open",
        "execution_engine": "bakery",
        "execution_purpose": "comms",
        "execution_payload": {"context": {"source": "poundcake"}},
        "execution_parameters": {"operation": "open"},
        "is_default": False,
        "is_blocking": False,
        "expected_duration_sec": 15,
        "timeout_duration_sec": 120,
        "retry_count": 1,
        "retry_delay": 5,
        "on_failure": "continue",
        "step_order": 1010,
        "run_phase": "firing",
        "run_condition": "always",
        "on_success": "continue",
        "parallel_group": 0,
        "depth": 0,
        "execution_parameters_override": None,
    }

    serialized_recipe = {
        "id": 42,
        "name": "filesystem-response",
        "description": "Example workflow",
        "enabled": True,
        "clear_timeout_sec": 300,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "deleted": False,
        "deleted_at": None,
        "recipe_ingredients": [],
        "communications": {
            "mode": "local",
            "effective_source": "local",
            "routes": [],
        },
    }

    with (
        patch("api.api.recipes._validate_ingredient_ids", new=AsyncMock()),
        patch("api.api.recipes._validate_effective_communications", new=AsyncMock()),
        patch(
            "api.api.recipes.build_recipe_local_policy_step_specs",
            return_value=([], [managed_spec]),
        ),
        patch("api.api.recipes._serialize_recipe", new=AsyncMock(return_value=serialized_recipe)),
    ):
        response = client.post(
            "/api/v1/recipes/",
            json={
                "name": "filesystem-response",
                "description": "Example workflow",
                "enabled": True,
                "clear_timeout_sec": 300,
                "communications": {
                    "mode": "local",
                    "routes": [
                        {
                            "label": "Rackspace Core",
                            "execution_target": "rackspace_core",
                            "destination_target": "",
                            "provider_config": {"account_number": "1781738"},
                            "enabled": True,
                            "position": 1,
                        }
                    ],
                },
                "recipe_ingredients": [
                    {
                        "ingredient_id": 12,
                        "step_order": 1,
                        "on_success": "continue",
                        "parallel_group": 0,
                        "depth": 0,
                        "execution_parameters_override": None,
                        "run_phase": "firing",
                        "run_condition": "always",
                    }
                ],
            },
        )

    assert response.status_code == 201
    assert len(created_managed_ingredients) == 1
    assert len(queued_steps) == 2
    assert [item.ingredient_id for item in queued_steps] == [12, 200]
    assert queued_steps[1].step_order == 1010


def test_recipe_update_local_communications_use_created_managed_ingredient_ids(client, mock_db):
    recipe = _make_recipe()
    created_managed_ingredients: list[Ingredient] = []

    def _add(obj):
        if isinstance(obj, Ingredient):
            created_managed_ingredients.append(obj)
        elif isinstance(obj, RecipeIngredient):
            recipe.recipe_ingredients.append(obj)

    async def _flush():
        next_id = 300
        for ingredient in created_managed_ingredients:
            if ingredient.id is None:
                ingredient.id = next_id
                next_id += 1

    mock_db.add = Mock(side_effect=_add)
    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=recipe),
            ScalarResult(first=recipe),
        ]
    )

    managed_spec = {
        "execution_target": "discord",
        "destination_target": "",
        "task_key_template": "pcmcomms.recipe.9.route-1.notify",
        "execution_engine": "bakery",
        "execution_purpose": "comms",
        "execution_payload": {"context": {"source": "poundcake"}},
        "execution_parameters": {"operation": "notify"},
        "is_default": False,
        "is_blocking": False,
        "expected_duration_sec": 15,
        "timeout_duration_sec": 120,
        "retry_count": 1,
        "retry_delay": 5,
        "on_failure": "continue",
        "step_order": 1010,
        "run_phase": "firing",
        "run_condition": "always",
        "on_success": "continue",
        "parallel_group": 0,
        "depth": 0,
        "execution_parameters_override": None,
    }

    serialized_recipe = {
        "id": 9,
        "name": "node-filesystem-workflow",
        "description": "Disk response",
        "enabled": True,
        "clear_timeout_sec": 300,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "deleted": False,
        "deleted_at": None,
        "recipe_ingredients": [],
        "communications": {
            "mode": "local",
            "effective_source": "local",
            "routes": [],
        },
    }

    with (
        patch("api.api.recipes._validate_effective_communications", new=AsyncMock()),
        patch("api.api.recipes.delete_recipe_ingredients_safely", new=AsyncMock(return_value=None)),
        patch(
            "api.api.recipes.build_recipe_local_policy_step_specs",
            return_value=([], [managed_spec]),
        ),
        patch("api.api.recipes._serialize_recipe", new=AsyncMock(return_value=serialized_recipe)),
    ):
        response = client.patch(
            "/api/v1/recipes/9",
            json={
                "communications": {
                    "mode": "local",
                    "routes": [
                        {
                            "label": "Discord",
                            "execution_target": "discord",
                            "destination_target": "",
                            "provider_config": {},
                            "enabled": True,
                            "position": 1,
                        }
                    ],
                }
            },
        )

    assert response.status_code == 200
    assert len(created_managed_ingredients) == 1
    assert len(recipe.recipe_ingredients) == 2
    assert [item.ingredient_id for item in recipe.recipe_ingredients] == [11, 300]
    assert recipe.recipe_ingredients[1].step_order == 1010
