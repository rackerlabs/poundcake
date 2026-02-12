#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database models for PoundCake."""

from datetime import datetime, timezone
from typing import Any, Optional, List

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, Index, Boolean, case
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property

# We use the explicit MariaDB/MySQL JSON type to ensure the dialect handles serialization properly
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON
from api.core.database import Base


def get_utc_now() -> datetime:
    """Helper for timezone-aware UTC, as utcnow is deprecated."""
    return datetime.now(timezone.utc)


class RecipeIngredient(Base):
    """
    The 'Assembly Line' - links Ingredients to Recipes in a specific order.
    """

    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredients.id"), nullable=False
    )

    # Determines the position in the ST2 Orquesta workflow
    step_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Logic gates for Orquesta (e.g., "on-success", "on-failure")
    on_success: Mapped[str] = mapped_column(String(50), default="continue")
    # Parallel grouping (same depth implies parallel tasks)
    parallel_group: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Depth in the task graph (for parallel/linear ordering)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="recipe_ingredients")
    ingredient: Mapped["Ingredient"] = relationship("Ingredient")

    __table_args__ = (Index("idx_recipe_ingredient_order", "recipe_id", "step_order"),)


class Recipe(Base):
    """
    Workflows (ST2 runner_type: orquesta)
    """

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Store the ST2 Ref (e.g. 'my_pack.my_workflow')
    workflow_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    workflow_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)
    workflow_parameters: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    recipe_ingredients: Mapped[List["RecipeIngredient"]] = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        order_by="RecipeIngredient.step_order",
        cascade="all, delete-orphan",
    )
    dishes: Mapped[List["Dish"]] = relationship("Dish", back_populates="recipe")

    @hybrid_property
    def total_expected_duration_sec(self) -> int:
        """Automatically sums the duration of all ingredients in this recipe."""
        return sum(
            ri.ingredient.expected_duration_sec
            for ri in self.recipe_ingredients
            if ri.ingredient is not None
        )


class Ingredient(Base):
    """
    Atomic Actions (ST2 runner_type != orquesta)
    """

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)

    action_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    action_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_parameters: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)

    is_blocking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expected_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_duration_sec: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_delay: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    on_failure: Mapped[str] = mapped_column(String(50), default="stop", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Dish(Base):
    """
    Execution instances (Old Ovens) - Tracks the actual run of a recipe.
    """

    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Traceability ID from Middleware (X-Request-Id)
    req_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Unique UUID returned by StackStorm for this specific run
    workflow_execution_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )

    order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("orders.id"), nullable=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False)

    processing_status: Mapped[str] = mapped_column(
        String(50), default="new", nullable=False, index=True
    )
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Snapshot of the expected duration at the time of the order
    expected_duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Calculation: completed_at - started_at
    actual_duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Full output payload from ST2
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    # Relationships
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="dishes")
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="dishes")
    dish_ingredients: Mapped[List["DishIngredient"]] = relationship(
        "DishIngredient",
        back_populates="dish",
        cascade="all, delete-orphan",
    )


class DishIngredient(Base):
    """
    Execution instances for individual recipe tasks within a Dish.
    """

    __tablename__ = "dish_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    dish_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dishes.id"), nullable=False, index=True
    )
    recipe_ingredient_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recipe_ingredients.id"), nullable=True
    )

    task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    st2_execution_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    result: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    dish: Mapped["Dish"] = relationship("Dish", back_populates="dish_ingredients")
    recipe_ingredient: Mapped["RecipeIngredient"] = relationship("RecipeIngredient")


class Order(Base):
    """
    The Webhook/Alert trigger (Old Alerts)
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    req_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alert_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(
        String(50), default="new", nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    alert_group_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    instance: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    counter: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    labels: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False)
    annotations: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)
    raw_data: Mapped[Optional[dict[str, Any]]] = mapped_column(MYSQL_JSON, nullable=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    dishes: Mapped[List["Dish"]] = relationship("Dish", back_populates="order")

    __table_args__ = (
        # Partial unique index: only enforce uniqueness on fingerprint for active orders
        # Using CASE expression with NULL allows multiple inactive orders with same fingerprint
        # but only one active order per fingerprint
        Index(
            "ux_orders_fingerprint_active",
            "fingerprint",
            case((is_active == True, 0), else_=None),
            unique=True,
        ),
        Index("ix_orders_is_active", "is_active"),
    )
