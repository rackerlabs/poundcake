#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Unit tests for orders and dishes API routes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models.models import Dish, DishIngredient, Order, Recipe


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


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    with patch("api.core.database.SessionLocal") as mock_session:
        mock_db = AsyncMock()
        mock_db.begin = Mock(return_value=_BeginContext())
        mock_db.add = Mock(return_value=None)
        mock_db.execute = AsyncMock(return_value=ScalarResult(first=None, all_=[]))
        mock_db.refresh = AsyncMock(return_value=None)
        mock_db.flush = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_db


def _make_order(order_id: int = 1, status: str = "new") -> Order:
    now = datetime.now(timezone.utc)
    order = Order(
        id=order_id,
        req_id="REQ-1",
        fingerprint="fp-1",
        alert_status="firing",
        processing_status=status,
        is_active=True,
        remediation_outcome="pending",
        clear_timeout_sec=None,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="group",
        severity="high",
        instance="host1",
        counter=1,
        bakery_ticket_state=None,
        bakery_permanent_failure=False,
        bakery_last_error=None,
        labels={"alertname": "Test"},
        annotations={},
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )
    order.communications = []
    return order


def _make_dish(dish_id: int = 1, status: str = "new", run_phase: str = "firing") -> Dish:
    now = datetime.now(timezone.utc)
    return Dish(
        id=dish_id,
        req_id="REQ-1",
        order_id=1,
        recipe_id=1,
        run_phase=run_phase,
        processing_status=status,
        expected_duration_sec=10,
        actual_duration_sec=None,
        execution_status=None,
        execution_ref=None,
        started_at=None,
        completed_at=None,
        result=None,
        error_message=None,
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )


def _make_dish_ingredient(ingredient_id: int = 1) -> DishIngredient:
    now = datetime.now(timezone.utc)
    return DishIngredient(
        id=ingredient_id,
        dish_id=1,
        recipe_ingredient_id=None,
        execution_target="core.local",
        destination_target="",
        execution_ref="st2-1",
        execution_status="succeeded",
        started_at=now,
        completed_at=now,
        canceled_at=None,
        result={},
        error_message=None,
        deleted=False,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )


def _make_recipe(recipe_id: int = 1, name: str = "group") -> Recipe:
    now = datetime.now(timezone.utc)
    return Recipe(
        id=recipe_id,
        name=name,
        description=None,
        enabled=True,
        clear_timeout_sec=None,
        created_at=now,
        updated_at=now,
        deleted=False,
        deleted_at=None,
    )


def _make_recipe_step(
    *,
    ri_id: int,
    ingredient_id: int,
    run_phase: str = "both",
    step_order: int = 1,
    engine: str = "stackstorm",
    purpose: str = "remediation",
):
    ingredient = SimpleNamespace(
        id=ingredient_id,
        execution_engine=engine,
        execution_purpose=purpose,
        execution_target="core.local" if engine == "stackstorm" else "rackspace_core",
        destination_target="",
        task_key_template="local" if engine == "stackstorm" else "core",
        execution_payload=None,
        execution_parameters={},
    )
    return SimpleNamespace(
        id=ri_id,
        ingredient_id=ingredient_id,
        ingredient=ingredient,
        step_order=step_order,
        run_phase=run_phase,
        execution_parameters_override=None,
    )


def test_orders_list__when_filtered_by_processing_status__returns_matching_rows(
    client, mock_db_session
):
    order = _make_order()
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(all_=[order]))

    response = client.get("/api/v1/orders?processing_status=new")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == order.id


def test_order_get__when_missing__returns_404(client, mock_db_session):
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=None))

    response = client.get("/api/v1/orders/999")
    assert response.status_code == 404


def test_order_create__ignores_fingerprint_when_active__persists_bakery_comms(
    client, mock_db_session
):
    mock_db_session.add = Mock()

    async def _refresh(order):
        now = datetime.now(timezone.utc)
        order.id = 42
        order.created_at = now
        order.updated_at = now

    mock_db_session.refresh = AsyncMock(side_effect=_refresh)

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "req_id": "REQ-NEW",
        "fingerprint": "fp-new",
        "alert_status": "firing",
        "alert_group_name": "group-new",
        "labels": {"alertname": "Test"},
        "starts_at": now,
        "bakery_comms_id": "comms-123",
        "fingerprint_when_active": "client-supplied-ignored",
    }

    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["bakery_comms_id"] == "comms-123"
    assert body["fingerprint_when_active"] is None

    created_order = mock_db_session.add.call_args.args[0]
    assert created_order.bakery_comms_id == "comms-123"
    assert created_order.fingerprint_when_active is None


def test_order_update__when_terminal_status__sets_inactive(client, mock_db_session):
    order = _make_order(status="processing")
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=order))

    payload = {"processing_status": "complete"}
    response = client.put("/api/v1/orders/1", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["processing_status"] == "complete"
    assert body["is_active"] is False


def test_order_update__ignores_fingerprint_when_active__updates_bakery_comms(
    client, mock_db_session
):
    order = _make_order(status="processing")
    order.fingerprint_when_active = "db-generated"
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=order))

    payload = {
        "bakery_comms_id": "comms-456",
        "fingerprint_when_active": "client-supplied-ignored",
    }
    response = client.put("/api/v1/orders/1", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["bakery_comms_id"] == "comms-456"
    assert body["fingerprint_when_active"] == "db-generated"
    assert order.bakery_comms_id == "comms-456"
    assert order.fingerprint_when_active == "db-generated"


def test_order_update__terminal_to_terminal_transition__returns_409(client, mock_db_session):
    order = _make_order(status="complete")
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(first=order))

    payload = {"processing_status": "failed"}
    response = client.put("/api/v1/orders/1", json=payload)

    assert response.status_code == 409


def test_dishes_list__when_filtered_by_processing_status__returns_matching_rows(
    client, mock_db_session
):
    dish = _make_dish()
    mock_db_session.execute = AsyncMock(return_value=ScalarResult(all_=[dish]))

    response = client.get("/api/v1/dishes?processing_status=new")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == dish.id


def test_dish_claim__when_not_claimable__returns_409(client, mock_db_session):
    mock_db_session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))

    response = client.post("/api/v1/dishes/1/claim")
    assert response.status_code == 409


def test_dish_claim__when_claimable__returns_dish(client, mock_db_session):
    dish = _make_dish(status="processing")
    update_result = SimpleNamespace(rowcount=1)
    select_result = ScalarResult(first=dish)
    mock_db_session.execute = AsyncMock(side_effect=[update_result, select_result])

    response = client.post("/api/v1/dishes/1/claim")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == dish.id


def test_dish_update__when_firing_complete__moves_order_to_waiting_clear(client, mock_db_session):
    dish = _make_dish(status="processing")
    order = _make_order(status="processing")
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    response = client.put("/api/v1/dishes/1", json={"processing_status": "complete"})
    assert response.status_code == 200
    assert order.processing_status == "waiting_clear"
    assert order.is_active is True
    assert order.remediation_outcome == "succeeded"
    assert order.auto_close_eligible is True


@pytest.mark.parametrize(
    ("dish_terminal_status", "expected_order_status", "expected_outcome", "expected_auto_close"),
    [
        ("complete", "waiting_clear", "succeeded", True),
        ("failed", "escalation", "failed", False),
        ("canceled", "escalation", "failed", False),
    ],
)
def test_dish_update__firing_terminal__transitions_to_waiting_clear_or_escalation(
    client,
    mock_db_session,
    dish_terminal_status: str,
    expected_order_status: str,
    expected_outcome: str,
    expected_auto_close: bool,
):
    dish = _make_dish(status="processing", run_phase="firing")
    order = _make_order(status="processing")
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    response = client.put("/api/v1/dishes/1", json={"processing_status": dish_terminal_status})

    assert response.status_code == 200
    assert order.processing_status == expected_order_status
    assert order.is_active is True
    assert order.remediation_outcome == expected_outcome
    assert order.auto_close_eligible is expected_auto_close


@pytest.mark.parametrize(
    ("dish_terminal_status", "expected_order_status"),
    [("complete", "complete"), ("failed", "failed"), ("canceled", "failed")],
)
def test_dish_update__resolving_terminal__sets_order_terminal(
    client, mock_db_session, dish_terminal_status: str, expected_order_status: str
):
    dish = _make_dish(status="processing", run_phase="resolving")
    order = _make_order(status="resolving")
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    response = client.put("/api/v1/dishes/1", json={"processing_status": dish_terminal_status})

    assert response.status_code == 200
    assert order.processing_status == expected_order_status
    assert order.is_active is False


def test_dish_update__catch_all_recipe_terminal__keeps_order_active(client, mock_db_session):
    dish = _make_dish(status="processing")
    dish.recipe = _make_recipe(name="fallback-recipe")
    order = _make_order(status="processing")
    order.remediation_outcome = "none"
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    with (
        patch(
            "api.api.dishes.get_settings",
            return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
        ),
        patch("api.api.dishes._sync_bakery_for_terminal_dish", new=AsyncMock()),
    ):
        response = client.put("/api/v1/dishes/1", json={"processing_status": "complete"})

    assert response.status_code == 200
    assert order.processing_status == "waiting_clear"
    assert order.is_active is True
    assert order.auto_close_eligible is False


@pytest.mark.parametrize("terminal_status", ["canceled", "failed"])
def test_update_dish_terminal_does_not_reactivate_terminal_order(
    client, mock_db_session, terminal_status: str
):
    dish = _make_dish(status="processing")
    order = _make_order(status=terminal_status)
    order.is_active = False
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=dish), ScalarResult(first=order)]
    )

    response = client.put("/api/v1/dishes/1", json={"processing_status": "complete"})

    assert response.status_code == 200
    assert order.processing_status == terminal_status
    assert order.is_active is False


def test_order_dispatch__without_matching_recipe__returns_skipped(client, mock_db_session):
    order = _make_order(status="new")
    mock_db_session.execute = AsyncMock(
        side_effect=[ScalarResult(first=order), ScalarResult(first=None)]
    )

    with (
        patch(
            "api.api.orders.get_settings",
            return_value=SimpleNamespace(catch_all_recipe_name=""),
        ),
        patch("api.api.orders.global_policy_configured", new=AsyncMock(return_value=False)),
    ):
        response = client.post("/api/v1/orders/1/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"


def test_order_dispatch__without_group_recipe__uses_fallback_recipe(client, mock_db_session):
    order = _make_order(status="new")
    fallback_recipe = SimpleNamespace(id=22, name="fallback-recipe", recipe_ingredients=[])

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=None),  # group recipe miss
            ScalarResult(first=fallback_recipe),  # fallback recipe hit
            ScalarResult(first=None),  # active dish lookup for phase
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with (
        patch(
            "api.api.orders.get_settings",
            return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
        ),
        patch("api.api.orders.global_policy_configured", new=AsyncMock(return_value=True)),
        patch("api.api.orders.ensure_fallback_recipe", new=AsyncMock()) as ensure_fallback,
        patch("api.api.orders.expected_duration_for_phase", new=AsyncMock(return_value=15)),
    ):
        response = client.post("/api/v1/orders/1/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["run_phase"] == "firing"
    assert body["recipe_id"] == 22
    assert body["recipe_name"] == "fallback-recipe"
    ensure_fallback.assert_awaited_once()


def test_order_dispatch__resolving_status__dispatches_resolve_phase_without_status_regression(
    client, mock_db_session
):
    order = _make_order(status="resolving")
    recipe = SimpleNamespace(id=12, name="group", recipe_ingredients=[])
    policy_recipe = SimpleNamespace(recipe_ingredients=[])

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=recipe),  # recipe hit
            ScalarResult(first=None),  # active dish lookup for phase
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with (
        patch("api.api.orders.expected_duration_for_phase", new=AsyncMock(return_value=30)),
        patch(
            "api.api.orders.get_settings", return_value=SimpleNamespace(catch_all_recipe_name="")
        ),
        patch("api.api.orders.global_policy_configured", new=AsyncMock(return_value=True)),
        patch(
            "api.api.orders.get_global_policy_recipe_for_dispatch",
            new=AsyncMock(return_value=policy_recipe),
        ),
    ):
        response = client.post("/api/v1/orders/1/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["run_phase"] == "resolving"
    assert order.processing_status == "resolving"
    assert order.is_active is True


def test_order_dispatch__resolving_stackstorm_only_recipe__without_effective_communications_skips(
    client, mock_db_session
):
    order = _make_order(status="resolving")
    group_recipe = SimpleNamespace(
        id=12,
        name="group",
        recipe_ingredients=[
            _make_recipe_step(ri_id=101, ingredient_id=201, run_phase="both", engine="stackstorm")
        ],
    )

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=group_recipe),  # group recipe hit
            ScalarResult(first=None),  # active dish lookup for phase
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with (
        patch(
            "api.api.orders.get_settings",
            return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
        ),
        patch("api.api.orders.global_policy_configured", new=AsyncMock(return_value=False)),
        patch("api.api.orders.ensure_fallback_recipe", new=AsyncMock()) as ensure_fallback,
    ):
        response = client.post("/api/v1/orders/1/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "No recipe for group"
    added = [call.args[0] for call in mock_db_session.add.call_args_list]
    seeded = [row for row in added if isinstance(row, DishIngredient)]
    assert seeded == []
    ensure_fallback.assert_not_called()


def test_order_dispatch__resolving_stackstorm_only_recipe__injects_global_policy_communications(
    client, mock_db_session
):
    order = _make_order(status="resolving")
    group_recipe = SimpleNamespace(
        id=12,
        name="group",
        recipe_ingredients=[
            _make_recipe_step(ri_id=101, ingredient_id=201, run_phase="both", engine="stackstorm")
        ],
    )
    policy_step = _make_recipe_step(
        ri_id=301,
        ingredient_id=401,
        run_phase="both",
        engine="bakery",
        purpose="comms",
    )
    policy_recipe = SimpleNamespace(recipe_ingredients=[policy_step])
    expected_duration = AsyncMock(return_value=30)

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=group_recipe),  # group recipe hit
            ScalarResult(first=None),  # active dish lookup for phase
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with (
        patch("api.api.orders.expected_duration_for_phase", new=expected_duration),
        patch(
            "api.api.orders.get_settings",
            return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
        ),
        patch("api.api.orders.global_policy_configured", new=AsyncMock(return_value=True)),
        patch(
            "api.api.orders.get_global_policy_recipe_for_dispatch",
            new=AsyncMock(return_value=policy_recipe),
        ),
        patch("api.api.orders.ensure_fallback_recipe", new=AsyncMock()) as ensure_fallback,
    ):
        response = client.post("/api/v1/orders/1/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["run_phase"] == "resolving"
    expected_duration.assert_awaited_once()
    assert expected_duration.await_args.kwargs["extra_recipe_ingredients"] == [policy_step]
    added = [call.args[0] for call in mock_db_session.add.call_args_list]
    seeded = [row for row in added if isinstance(row, DishIngredient)]
    assert len(seeded) == 1
    assert seeded[0].execution_engine == "bakery"
    assert seeded[0].recipe_ingredient_id == 301
    ensure_fallback.assert_not_called()


def test_order_dispatch__resolving_with_recipe_bakery_comms__does_not_inject_fallback(
    client, mock_db_session
):
    order = _make_order(status="resolving")
    recipe = SimpleNamespace(
        id=12,
        name="group",
        recipe_ingredients=[
            _make_recipe_step(
                ri_id=101,
                ingredient_id=201,
                run_phase="both",
                engine="bakery",
                purpose="comms",
            )
        ],
    )

    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),  # order
            ScalarResult(first=recipe),  # group recipe hit
            ScalarResult(first=None),  # active dish lookup for phase
            ScalarResult(all_=[]),  # existing dish ingredients
        ]
    )

    with (
        patch("api.api.orders.expected_duration_for_phase", new=AsyncMock(return_value=30)),
        patch(
            "api.api.orders.get_settings",
            return_value=SimpleNamespace(catch_all_recipe_name="fallback-recipe"),
        ),
        patch("api.api.orders.global_policy_configured", new=AsyncMock(return_value=False)),
        patch(
            "api.api.orders.get_global_policy_recipe_for_dispatch",
            new=AsyncMock(return_value=SimpleNamespace(recipe_ingredients=[])),
        ) as get_policy_recipe,
        patch("api.api.orders.ensure_fallback_recipe", new=AsyncMock()) as ensure_fallback,
    ):
        response = client.post("/api/v1/orders/1/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["run_phase"] == "resolving"
    added = [call.args[0] for call in mock_db_session.add.call_args_list]
    seeded = [row for row in added if isinstance(row, DishIngredient)]
    assert len(seeded) == 1
    assert seeded[0].execution_engine == "bakery"
    assert seeded[0].recipe_ingredient_id == 101
    get_policy_recipe.assert_not_awaited()
    ensure_fallback.assert_not_called()


def test_order_timeline_get__returns_events(client, mock_db_session):
    order = _make_order(status="processing")
    order.bakery_ticket_id = "ticket-1"
    order.bakery_operation_id = "op-1"
    dish = _make_dish(status="processing")
    ingredient = _make_dish_ingredient()
    mock_db_session.execute = AsyncMock(
        side_effect=[
            ScalarResult(first=order),
            ScalarResult(all_=[dish]),
            ScalarResult(all_=[ingredient]),
        ]
    )

    with patch("api.api.orders.get_operation", new=AsyncMock(return_value={"status": "running"})):
        response = client.get("/api/v1/orders/1/timeline")

    assert response.status_code == 200
    data = response.json()
    assert data["order"]["id"] == 1
    assert len(data["events"]) >= 3
    assert any(event["event_type"] == "bakery" for event in data["events"])
