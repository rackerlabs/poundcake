"""Helpers for ordered execution segments within a dish."""

from __future__ import annotations

from typing import Any

PENDING_EXECUTION_STATUSES = {"pending", "queued", "processing", "running", None}


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_step_order_from_task_key(task_key: str | None) -> int | None:
    if not isinstance(task_key, str):
        return None
    if not task_key.startswith("step_"):
        return None
    remainder = task_key[len("step_") :]
    prefix = remainder.split("_", 1)[0]
    if prefix.isdigit():
        return int(prefix)
    return None


def build_recipe_step_order_map(dish: dict[str, Any]) -> dict[int, int]:
    raw_recipe = dish.get("recipe")
    recipe = raw_recipe if isinstance(raw_recipe, dict) else {}
    raw_recipe_ingredients = recipe.get("recipe_ingredients")
    recipe_ingredients = raw_recipe_ingredients if isinstance(raw_recipe_ingredients, list) else []
    step_orders: dict[int, int] = {}
    for item in recipe_ingredients:
        if not isinstance(item, dict):
            continue
        ri_id = _coerce_int(item.get("id"))
        step_order = _coerce_int(item.get("step_order"))
        if ri_id is None or step_order is None:
            continue
        step_orders[ri_id] = step_order
    return step_orders


def sort_ingredients_for_execution(
    dish: dict[str, Any], ingredients: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    step_orders = build_recipe_step_order_map(dish)

    def _sort_key(item: dict[str, Any]) -> tuple[int, str, str, int]:
        recipe_ingredient_id = _coerce_int(item.get("recipe_ingredient_id"))
        task_key = str(item.get("task_key") or "")
        step_order = (
            step_orders.get(recipe_ingredient_id) if recipe_ingredient_id is not None else None
        )
        if step_order is None:
            step_order = _parse_step_order_from_task_key(task_key)
        if step_order is None:
            step_order = 1_000_000
        created_at = str(item.get("created_at") or "")
        item_id = _coerce_int(item.get("id")) or 0
        return (step_order, task_key, created_at, item_id)

    return sorted(
        [item for item in ingredients if isinstance(item, dict)],
        key=_sort_key,
    )


def next_pending_execution_segment(
    dish: dict[str, Any], ingredients: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]] | None:
    ordered = sort_ingredients_for_execution(dish, ingredients)
    first_pending_index: int | None = None
    segment_engine: str | None = None

    for idx, item in enumerate(ordered):
        if item.get("execution_status") not in PENDING_EXECUTION_STATUSES:
            continue
        engine = str(item.get("execution_engine") or "").strip().lower()
        if engine not in {"stackstorm", "bakery"}:
            continue
        first_pending_index = idx
        segment_engine = engine
        break

    if first_pending_index is None or segment_engine is None:
        return None

    segment: list[dict[str, Any]] = []
    for item in ordered[first_pending_index:]:
        if item.get("execution_status") not in PENDING_EXECUTION_STATUSES:
            break
        engine = str(item.get("execution_engine") or "").strip().lower()
        if engine != segment_engine:
            break
        segment.append(item)

    if not segment:
        return None
    return segment_engine, segment


def has_pending_execution(dish: dict[str, Any], ingredients: list[dict[str, Any]]) -> bool:
    return next_pending_execution_segment(dish, ingredients) is not None
