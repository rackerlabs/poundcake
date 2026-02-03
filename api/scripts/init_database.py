#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Initialize database with new Recipe/Oven/Alert schema."""

import sys
import os
from pathlib import Path

# Add parent directory to path for direct execution
script_dir = Path(__file__).parent
api_dir = script_dir.parent
sys.path.insert(0, str(api_dir))

# Also add the parent of api_dir for api.* imports
if str(api_dir.parent) not in sys.path:
    sys.path.insert(0, str(api_dir.parent))

from core.database import Base, engine, SessionLocal
from models.models import (
    Recipe,
    Ingredient,  # noqa: F401 - Required for Base.metadata.create_all()
    Oven,  # noqa: F401 - Required for Base.metadata.create_all()
    Alert,  # noqa: F401 - Required for Base.metadata.create_all()
)
from core.logging import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


def init_database() -> None:
    """Initialize database tables."""
    logger.info(
        "init_database: Creating database tables",
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
    
    try:
        Base.metadata.create_all(bind=engine)
        
        tables = list(Base.metadata.tables.keys())
        logger.info(
            "init_database: Database tables created successfully",
            extra={"req_id": "SYSTEM-DB-INIT", "table_count": len(tables), "tables": tables}
        )

    except Exception as e:
        logger.error(
            "init_database: Failed to create database tables",
            extra={"req_id": "SYSTEM-DB-INIT", "error": str(e)},
            exc_info=True
        )
        sys.exit(1)


def seed_default_recipes() -> None:
    """Seed database with default recipes and their ingredients."""
    logger.info(
        "seed_default_recipes: Starting",
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
    
    db = SessionLocal()

    try:
        # Check if recipes already exist
        existing_count = db.query(Recipe).count()
        if existing_count > 0:
            logger.info(
                "seed_default_recipes: Recipes already exist, skipping",
                extra={"req_id": "SYSTEM-DB-INIT", "existing_count": existing_count}
            )
            return

        # Default recipe with ingredients
        default_recipe = Recipe(
            name="default",
            description="Default recipe for unmatched alerts",
            enabled=True
        )
        
        # Add default ingredients
        default_ingredients = [
            Ingredient(
                task_id="log_alert",
                task_name="Log Alert Information",
                task_order=1,
                is_blocking=True,
                st2_action="core.echo",
                parameters={"message": "Alert received and logged"},
                expected_time_to_completion=5,
                timeout=30,
                retry_count=0,
                on_failure="continue"
            ),
            Ingredient(
                task_id="notify_team",
                task_name="Notify Team",
                task_order=2,
                is_blocking=False,
                st2_action="core.sendmail",
                parameters={"to": "ops@example.com", "subject": "Alert Notification"},
                expected_time_to_completion=10,
                timeout=60,
                retry_count=1,
                retry_delay=5,
                on_failure="continue"
            )
        ]
        
        default_recipe.ingredients = default_ingredients
        db.add(default_recipe)
        db.commit()
        
        logger.info(
            "seed_default_recipes: Default recipe created successfully",
            extra={
                "req_id": "SYSTEM-DB-INIT",
                "recipe_name": "default",
                "ingredient_count": len(default_ingredients)
            }
        )

    except Exception as e:
        logger.error(
            "seed_default_recipes: Failed to seed recipes",
            extra={"req_id": "SYSTEM-DB-INIT", "error": str(e)},
            exc_info=True
        )
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    logger.info(
        "=" * 60,
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
    logger.info(
        "PoundCake Database Initialization",
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
    logger.info(
        "=" * 60,
        extra={"req_id": "SYSTEM-DB-INIT"}
    )

    # Initialize tables
    init_database()

    # Seed default recipes
    seed_default_recipes()

    logger.info(
        "=" * 60,
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
    logger.info(
        "Database initialization complete",
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
    logger.info(
        "=" * 60,
        extra={"req_id": "SYSTEM-DB-INIT"}
    )
