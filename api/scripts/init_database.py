#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Initialize database with new Recipe/Oven/Alert schema."""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select, func

# Add the parent of api directory to path for absolute imports
# When run from container: /app/api/scripts/init_database.py
# We need /app in sys.path so 'api.core.database' works
script_dir = Path(__file__).parent  # /app/api/scripts
api_dir = script_dir.parent  # /app/api
project_root = api_dir.parent  # /app

# Ensure project root is in path for api.* imports
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Now use absolute imports like the rest of the codebase
from api.core.database import Base, engine, SessionLocal  # noqa: E402
from api.models.models import Recipe, Ingredient, RecipeIngredient  # noqa: E402
from api.core.logging import setup_logging, get_logger  # noqa: E402

setup_logging()
logger = get_logger(__name__)


async def init_database() -> None:
    """Initialize database tables."""
    logger.info("Creating database tables", extra={"req_id": "SYSTEM-DB-INIT"})

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        tables = list(Base.metadata.tables.keys())
        logger.info(
            "Database tables created successfully",
            extra={"req_id": "SYSTEM-DB-INIT", "table_count": len(tables), "tables": tables},
        )

    except Exception as e:
        logger.error(
            "Failed to create database tables",
            extra={"req_id": "SYSTEM-DB-INIT", "error": str(e)},
            exc_info=True,
        )
        sys.exit(1)


async def seed_default_recipes() -> None:
    """Seed database with default recipes and their ingredients."""
    logger.info("Starting", extra={"req_id": "SYSTEM-DB-INIT"})

    async with SessionLocal() as db:
        try:
            # Check if recipes already exist
            result = await db.execute(select(func.count(Recipe.id)))
            existing_count = result.scalar() or 0
            if existing_count > 0:
                logger.info(
                    "Recipes already exist, skipping",
                    extra={"req_id": "SYSTEM-DB-INIT", "existing_count": existing_count},
                )
                return

            default_recipe = Recipe(
                name="default",
                description="Default recipe for unmatched orders",
                enabled=True,
            )
            db.add(default_recipe)
            await db.flush()

            default_ingredients = [
                Ingredient(
                    task_id="log_alert",
                    task_name="Log Alert Information",
                    action_id=None,  # pyright: ignore[reportCallIssue]
                    action_payload=None,
                    action_parameters=None,
                    is_blocking=True,
                    expected_duration_sec=5,
                    timeout_duration_sec=30,
                    retry_count=0,
                    retry_delay=0,
                    on_failure="continue",
                ),
                Ingredient(
                    task_id="notify_team",
                    task_name="Notify Team",
                    action_id=None,
                    action_payload=None,
                    action_parameters={"to": "ops@example.com", "subject": "Alert Notification"},
                    is_blocking=False,
                    expected_duration_sec=10,
                    timeout_duration_sec=60,
                    retry_count=1,
                    retry_delay=5,
                    on_failure="continue",
                ),
            ]

            db.add_all(default_ingredients)
            await db.flush()

            recipe_links = [
                RecipeIngredient(
                    recipe_id=default_recipe.id,
                    ingredient_id=default_ingredients[0].id,
                    step_order=1,
                    on_success="continue",
                ),
                RecipeIngredient(
                    recipe_id=default_recipe.id,
                    ingredient_id=default_ingredients[1].id,
                    step_order=2,
                    on_success="continue",
                ),
            ]

            db.add_all(recipe_links)
            await db.commit()

            logger.info(
                "Default recipe created successfully",
                extra={
                    "req_id": "SYSTEM-DB-INIT",
                    "recipe_name": "default",
                    "ingredient_count": len(default_ingredients),
                },
            )

        except Exception as e:
            logger.error(
                "Failed to seed recipes",
                extra={"req_id": "SYSTEM-DB-INIT", "error": str(e)},
                exc_info=True,
            )
            await db.rollback()


if __name__ == "__main__":
    logger.info("=" * 60, extra={"req_id": "SYSTEM-DB-INIT"})
    logger.info("PoundCake Database Initialization", extra={"req_id": "SYSTEM-DB-INIT"})
    logger.info("=" * 60, extra={"req_id": "SYSTEM-DB-INIT"})

    # Initialize tables
    asyncio.run(init_database())

    # Seed default recipes
    asyncio.run(seed_default_recipes())

    logger.info("=" * 60, extra={"req_id": "SYSTEM-DB-INIT"})
    logger.info("Database initialization complete", extra={"req_id": "SYSTEM-DB-INIT"})
    logger.info("=" * 60, extra={"req_id": "SYSTEM-DB-INIT"})
