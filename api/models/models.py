#  ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database models for PoundCake."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship

# We use the explicit MariaDB/MySQL JSON type to ensure the dialect handles serialization properly
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON
from api.core.database import Base


def get_utc_now():
    """Helper for timezone-aware UTC, as utcnow is deprecated."""
    return datetime.now(timezone.utc)


class Recipe(Base):
    """Recipe - matches alert.group_name to define response workflow."""

    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    # MariaDB prefers explicit defaults; we use get_utc_now to avoid deprecation warnings
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    ingredients = relationship("Ingredient", back_populates="recipe", cascade="all, delete-orphan")
    ovens = relationship("Oven", back_populates="recipe")


class Ingredient(Base):
    """Ingredient - individual task in a recipe."""

    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    task_id = Column(String(100), nullable=False, index=True)
    task_name = Column(String(255), nullable=False)
    task_order = Column(Integer, nullable=False)
    is_blocking = Column(Boolean, default=True, nullable=False)
    st2_action = Column(String(255), nullable=False)
    # Use MYSQL_JSON to ensure MariaDB LONGTEXT mapping is handled cleanly
    parameters = Column(MYSQL_JSON, nullable=True)
    expected_time_to_completion = Column(Integer, nullable=False)
    timeout = Column(Integer, default=300, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    retry_delay = Column(Integer, default=5, nullable=False)
    on_failure = Column(String(50), default="stop", nullable=False)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    recipe = relationship("Recipe", back_populates="ingredients")
    ovens = relationship("Oven", back_populates="ingredient")

    __table_args__ = (Index("idx_recipe_order", "recipe_id", "task_order"),)


class Oven(Base):
    """Oven - tracks individual ingredient execution."""

    __tablename__ = "ovens"

    id = Column(Integer, primary_key=True, index=True)
    req_id = Column(String(100), nullable=False, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    processing_status = Column(String(50), default="new", nullable=False, index=True)
    task_order = Column(Integer, nullable=False, index=True)
    is_blocking = Column(Boolean, default=True, nullable=False)
    action_id = Column(String(255), nullable=True, index=True)
    st2_status = Column(String(50), nullable=True)
    expected_duration = Column(Integer, nullable=True)
    actual_duration = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    action_result = Column(MYSQL_JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_attempt = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    recipe = relationship("Recipe", back_populates="ovens")
    ingredient = relationship("Ingredient", back_populates="ovens")
    alert = relationship("Alert", back_populates="ovens")

    __table_args__ = (Index("idx_oven_task_order", "recipe_id", "task_order"),)


class Alert(Base):
    """Alert - stores and tracks alert auto-remediation status."""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    req_id = Column(String(100), nullable=False, index=True)
    fingerprint = Column(String(255), nullable=False, index=True)
    alert_status = Column(String(50), nullable=False, index=True)
    processing_status = Column(String(50), default="new", nullable=False, index=True)
    alert_name = Column(String(255), nullable=False, index=True)
    group_name = Column(String(255), nullable=True, index=True)
    severity = Column(String(50), nullable=True, index=True)
    instance = Column(String(255), nullable=True, index=True)
    prometheus = Column(String(255), nullable=True)
    labels = Column(MYSQL_JSON, nullable=False)
    annotations = Column(MYSQL_JSON, nullable=True)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=True)
    generator_url = Column(Text, nullable=True)
    counter = Column(Integer, default=1, nullable=False)
    ticket_number = Column(String(100), nullable=True, index=True)
    raw_data = Column(MYSQL_JSON, nullable=True)
    created_at = Column(DateTime, default=get_utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    ovens = relationship("Oven", back_populates="alert")
