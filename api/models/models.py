#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database models for PoundCake."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

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

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)

    # Determines the position in the ST2 Orquesta workflow
    step_order = Column(Integer, default=1, nullable=False)

    # Logic gates for Orquesta (e.g., "on-success", "on-failure")
    on_success = Column(String(50), default="continue")
    # Parallel grouping (same depth implies parallel tasks)
    parallel_group = Column(Integer, default=0, nullable=False)
    # Depth in the task graph (for parallel/linear ordering)
    depth = Column(Integer, default=0, nullable=False)

    recipe = relationship("Recipe", back_populates="recipe_ingredients")
    ingredient = relationship("Ingredient")

    __table_args__ = (Index("idx_recipe_ingredient_order", "recipe_id", "step_order"),)


class Recipe(Base):
    """
    Workflows (ST2 runner_type: orquesta)
    """

    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)

    # Store the ST2 Ref (e.g. 'my_pack.my_workflow')
    workflow_id = Column(String(255), nullable=True)
    workflow_payload = Column(MYSQL_JSON, nullable=True)  # Orquesta JSON payload
    workflow_parameters = Column(MYSQL_JSON, nullable=True)

    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    recipe_ingredients = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        order_by="RecipeIngredient.step_order",
        cascade="all, delete-orphan",
    )
    dishes = relationship("Dish", back_populates="recipe")

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
    Atomic Actions (ST2 runner_type != orquesta)
    """

    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(100), nullable=False, index=True)  # ST2 action.ref (e.g. 'core.local')
    task_name = Column(String(255), nullable=False)

    action_id = Column(String(100), nullable=True)  # The ST2 UUID for reuse
    action_payload = Column(Text, nullable=True)
    action_parameters = Column(MYSQL_JSON, nullable=True)

    is_blocking = Column(Boolean, default=True, nullable=False)
    expected_duration_sec = Column(Integer, nullable=False)
    timeout_duration_sec = Column(Integer, default=300, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    retry_delay = Column(Integer, default=5, nullable=False)
    on_failure = Column(String(50), default="stop", nullable=False)

    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)


class Dish(Base):
    """
    Execution instances (Old Ovens) - Tracks the actual run of a recipe.
    """

    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, index=True)

    # Traceability ID from Middleware (X-Request-Id)
    req_id = Column(String(100), nullable=False, index=True)

    # Unique UUID returned by StackStorm for this specific run
    workflow_execution_id = Column(String(100), nullable=True, index=True)

    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)

    processing_status = Column(String(50), default="new", nullable=False, index=True)
    status = Column(String(50), nullable=True)  # running, succeeded, failed, etc.

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Snapshot of the expected duration at the time of the order
    expected_duration_sec = Column(Integer, nullable=True)

    # Calculation: completed_at - started_at
    actual_duration_sec = Column(Integer, nullable=True)

    # Full output payload from ST2
    result = Column(MYSQL_JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_attempt = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    # Relationships
    recipe = relationship("Recipe", back_populates="dishes")
    order = relationship("Order", back_populates="dishes")
    dish_ingredients = relationship(
        "DishIngredient",
        back_populates="dish",
        cascade="all, delete-orphan",
    )


class DishIngredient(Base):
    """
    Execution instances for individual recipe tasks within a Dish.
    """

    __tablename__ = "dish_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    recipe_ingredient_id = Column(Integer, ForeignKey("recipe_ingredients.id"), nullable=True)

    task_id = Column(String(255), nullable=True, index=True)
    st2_execution_id = Column(String(100), nullable=True, index=True)

    status = Column(String(50), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)

    result = Column(MYSQL_JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    dish = relationship("Dish", back_populates="dish_ingredients")
    recipe_ingredient = relationship("RecipeIngredient")


class Order(Base):
    """
    The Webhook/Alert trigger (Old Alerts)
    """

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    req_id = Column(String(100), nullable=False, index=True)
    fingerprint = Column(String(255), nullable=False, index=True)
    alert_status = Column(String(50), nullable=False, index=True)
    processing_status = Column(String(50), default="new", nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    alert_group_name = Column(String(255), nullable=False, index=True)
    severity = Column(String(50), nullable=True, index=True)
    instance = Column(String(255), nullable=True, index=True)
    counter = Column(Integer, default=1, nullable=False)

    labels = Column(MYSQL_JSON, nullable=False)
    annotations = Column(MYSQL_JSON, nullable=True)
    raw_data = Column(MYSQL_JSON, nullable=True)

    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=get_utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    dishes = relationship("Dish", back_populates="order")

    __table_args__ = (
        Index("ux_orders_fingerprint_active", "fingerprint", "is_active", unique=True),
        Index("ix_orders_is_active", "is_active"),
    )
