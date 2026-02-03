#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Initialize database with new Recipe/Oven/Alert schema."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.core.database import Base, engine
from api.models.models import (
    Recipe,
    Ingredient,  # noqa: F401 - Required for Base.metadata.create_all()
    Oven,  # noqa: F401 - Required for Base.metadata.create_all()
    Alert,  # noqa: F401 - Required for Base.metadata.create_all()
)
from api.core.logging import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


def init_database() -> None:
    """Initialize database tables."""
    try:
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created successfully")

        # Print table info
        tables = Base.metadata.tables.keys()
        logger.info(f"Created tables: {', '.join(tables)}")

    except Exception as e:
        logger.error(f"✗ Failed to create database tables: {e}", exc_info=True)
        sys.exit(1)


def seed_default_recipes() -> None:
    """Seed database with default recipes and their ingredients."""
    from sqlalchemy.orm import Session
    from api.core.database import SessionLocal
    from api.models.models import Ingredient

    db: Session = SessionLocal()

    try:
        # Check if recipes already exist
        existing_count = db.query(Recipe).count()
        if existing_count > 0:
            logger.info(f"Database already has {existing_count} recipes, skipping seed")
            return

        logger.info("Seeding default recipes...")

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
        
        logger.info(f"✓ Seeded default recipe with {len(default_ingredients)} ingredients")

    except Exception as e:
        logger.error(f"✗ Failed to seed recipes: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("PoundCake v2.0 Database Initialization")
    logger.info("=" * 60)

    # Initialize tables
    init_database()

    # Seed default recipes
    seed_default_recipes()

    logger.info("=" * 60)
    logger.info("Database initialization complete!")
    logger.info("=" * 60)
