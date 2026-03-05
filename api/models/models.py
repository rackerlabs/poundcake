#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database models for PoundCake."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

# We use the explicit MariaDB/MySQL JSON type to ensure the dialect handles serialization properly
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON
from api.core.database import Base


def get_utc_now():
    """Helper for timezone-aware UTC, as utcnow is deprecated."""
    return datetime.now(timezone.utc)


class RecipeIngredient(Base):
    """
    The 'Assembly Line' - links Ingredients to Recipes in a specific order.
    """

    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False)

    # Determines the position in the ST2 Orquesta workflow
    step_order: Mapped[int] = mapped_column(default=1, nullable=False)

    # Logic gates for Orquesta (e.g., "on-success", "on-failure")
    on_success: Mapped[str | None] = mapped_column(String(50), default="continue")
    # Parallel grouping (same depth implies parallel tasks)
    parallel_group: Mapped[int] = mapped_column(default=0, nullable=False)
    # Depth in the task graph (for parallel/linear ordering)
    depth: Mapped[int] = mapped_column(default=0, nullable=False)
    # Optional per-step execution parameter overrides.
    execution_parameters_override: Mapped[dict[str, Any] | None] = mapped_column(
        MYSQL_JSON, nullable=True
    )
    # Controls when this step is eligible to run in the order lifecycle.
    run_phase: Mapped[str] = mapped_column(String(16), default="both", nullable=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="recipe_ingredients")
    ingredient: Mapped["Ingredient"] = relationship()

    __table_args__ = (Index("idx_recipe_ingredient_order", "recipe_id", "step_order"),)


class Recipe(Base):
    """
    Workflow templates and metadata
    """

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        order_by="RecipeIngredient.step_order",
        cascade="all, delete-orphan",
    )
    dishes: Mapped[list["Dish"]] = relationship("Dish", back_populates="recipe")

    @hybrid_property
    def total_expected_duration_sec(self):
        """Automatically sums the duration of all ingredients in this recipe."""
        return sum(
            ri.ingredient.expected_duration_sec
            for ri in self.recipe_ingredients
            if ri.ingredient is not None
        )


class Ingredient(Base):
    """
    Atomic execution definitions.
    """

    __tablename__ = "ingredients"
    __table_args__ = (
        UniqueConstraint(
            "execution_engine", "execution_target", name="ux_ingredients_engine_target"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    execution_target: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    task_key_template: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_engine: Mapped[str] = mapped_column(String(50), default="undefined", nullable=False)
    execution_purpose: Mapped[str] = mapped_column(String(32), default="utility", nullable=False)

    execution_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    execution_payload: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    execution_parameters: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Backward-compat aliases for one release cycle.
    @property
    def action_id(self) -> str | None:
        return self.execution_id

    @action_id.setter
    def action_id(self, value: str | None) -> None:
        self.execution_id = value

    @property
    def ingredient_kind(self) -> str:
        return self.execution_purpose

    @ingredient_kind.setter
    def ingredient_kind(self, value: str) -> None:
        self.execution_purpose = value


class Dish(Base):
    """
    Execution instances - Tracks the actual run of a recipe.
    """

    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Traceability ID from Middleware (X-Request-Id)
    req_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Engine execution reference for this run
    execution_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False)

    processing_status: Mapped[str] = mapped_column(
        String(50), default="new", nullable=False, index=True
    )
    execution_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Snapshot of the expected duration at the time of the order
    expected_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Calculation: completed_at - started_at
    actual_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Full output payload from ST2
    result: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    # Relationships
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="dishes")
    order: Mapped["Order | None"] = relationship("Order", back_populates="dishes")
    dish_ingredients: Mapped[list["DishIngredient"]] = relationship(
        "DishIngredient",
        back_populates="dish",
        cascade="all, delete-orphan",
    )


class DishIngredient(Base):
    """
    Execution instances for individual recipe tasks within a Dish.
    """

    __tablename__ = "dish_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), nullable=False, index=True)
    recipe_ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("recipe_ingredients.id"), nullable=True
    )

    task_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    execution_engine: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    execution_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    execution_payload: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    execution_parameters: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    execution_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    result: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    dish: Mapped["Dish"] = relationship("Dish", back_populates="dish_ingredients")
    recipe_ingredient: Mapped["RecipeIngredient | None"] = relationship("RecipeIngredient")


class Order(Base):
    """
    The Webhook/Alert trigger (Old Alerts)
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    req_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alert_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(
        String(50), default="new", nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    alert_group_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    instance: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    counter: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    bakery_ticket_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    bakery_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    bakery_ticket_state: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    bakery_permanent_failure: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    bakery_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    bakery_comms_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fingerprint_when_active: Mapped[str | None] = mapped_column(
        String(255),
        Computed("IF(is_active = 1, fingerprint, NULL)", persisted=True),
        nullable=True,
    )

    labels: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False)
    annotations: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    dishes: Mapped[list["Dish"]] = relationship("Dish", back_populates="order")


class AlertSuppression(Base):
    """Maintenance window for suppressing webhook alerts."""

    __tablename__ = "alert_suppressions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="matchers")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary_ticket_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    matchers: Mapped[list["AlertSuppressionMatcher"]] = relationship(
        "AlertSuppressionMatcher",
        back_populates="suppression",
        cascade="all, delete-orphan",
    )

    suppressed_events: Mapped[list["SuppressedEvent"]] = relationship(
        "SuppressedEvent",
        back_populates="suppression",
        cascade="all, delete-orphan",
    )

    summary: Mapped["SuppressionSummary | None"] = relationship(
        "SuppressionSummary",
        back_populates="suppression",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "idx_alert_suppressions_active_lookup",
            "enabled",
            "starts_at",
            "ends_at",
            "canceled_at",
        ),
    )


class AlertSuppressionMatcher(Base):
    """Label matcher row for suppression matching rules."""

    __tablename__ = "alert_suppression_matchers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    suppression_id: Mapped[int] = mapped_column(
        ForeignKey("alert_suppressions.id"),
        nullable=False,
        index=True,
    )
    label_key: Mapped[str] = mapped_column(String(255), nullable=False)
    operator: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)

    suppression: Mapped["AlertSuppression"] = relationship(
        "AlertSuppression", back_populates="matchers"
    )


class SuppressedEvent(Base):
    """Individual alert event captured by suppression windows."""

    __tablename__ = "suppressed_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    suppression_id: Mapped[int] = mapped_column(
        ForeignKey("alert_suppressions.id"),
        nullable=False,
        index=True,
    )
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    alertname: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    severity: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    labels_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False)
    annotations_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="firing")
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    req_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)

    suppression: Mapped["AlertSuppression"] = relationship(
        "AlertSuppression",
        back_populates="suppressed_events",
    )

    __table_args__ = (
        Index("idx_suppressed_events_suppression_received_at", "suppression_id", "received_at"),
        Index("idx_suppressed_events_fingerprint", "fingerprint"),
    )


class SuppressionSummary(Base):
    """Aggregated suppression window summary and Bakery ticket refs."""

    __tablename__ = "suppression_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    suppression_id: Mapped[int] = mapped_column(
        ForeignKey("alert_suppressions.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    total_suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cleared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_still_firing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    by_alertname_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    by_severity_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True)
    still_firing_alerts_json: Mapped[dict[str, Any] | None] = mapped_column(
        MYSQL_JSON, nullable=True
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bakery_ticket_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    bakery_create_operation_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    bakery_close_operation_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    summary_close_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    suppression: Mapped["AlertSuppression"] = relationship(
        "AlertSuppression", back_populates="summary"
    )
