#!/usr/bin/env python3
"""Database initialization script for Bakery."""

from collections.abc import Iterable
from pathlib import Path
import sys
import time
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from bakery.config import settings
from bakery.structlog_compat import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()

MANAGED_TABLES = frozenset({"messages", "ticket_requests", "mixer_configs"})
ALEMBIC_VERSION_TABLE = "alembic_version"


def wait_for_database(max_attempts: int = 30, delay_sec: int = 2) -> bool:
    """
    Wait for database to become available.

    Args:
        max_attempts: Maximum number of connection attempts
        delay_sec: Delay between attempts in seconds

    Returns:
        True if database is available, False otherwise
    """
    logger.info("Waiting for database to be ready", database=settings.database_host)

    for attempt in range(1, max_attempts + 1):
        try:
            engine = create_engine(settings.database_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database is ready", attempts=attempt)
            return True
        except OperationalError as e:
            if attempt < max_attempts:
                logger.warning(
                    "Database not ready, retrying",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(e),
                )
                time.sleep(delay_sec)
            else:
                logger.error(
                    "Database did not become ready",
                    attempts=attempt,
                    error=str(e),
                )
                return False
        except Exception as e:
            logger.error("Unexpected error connecting to database", error=str(e))
            return False

    return False


def inspect_schema_state(database_url: str) -> tuple[set[str], list[str]]:
    """Return the current Bakery table names and stored Alembic revisions."""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        table_names = set(inspect(engine).get_table_names())
        revisions: list[str] = []
        if ALEMBIC_VERSION_TABLE in table_names:
            with engine.connect() as conn:
                revisions = [
                    row[0]
                    for row in conn.execute(text("SELECT version_num FROM alembic_version"))
                    if row[0]
                ]
        return table_names, revisions
    finally:
        engine.dispose()


def determine_migration_strategy(
    existing_tables: Iterable[str],
    alembic_revisions: Iterable[str] | None = None,
) -> str:
    """
    Decide how Bakery migrations should initialize an existing database.

    Returns one of:
      - "upgrade": schema is empty or already versioned
      - "stamp": full managed schema exists but alembic_version is missing
      - "error": partial managed schema exists without alembic_version
    """
    table_names = set(existing_tables)
    stored_revisions = [revision for revision in (alembic_revisions or []) if revision]
    managed_present = MANAGED_TABLES & table_names

    if stored_revisions:
        return "upgrade"
    if not managed_present:
        return "upgrade"
    if MANAGED_TABLES.issubset(table_names):
        return "stamp"
    return "error"


def run_migrations() -> bool:
    """Run Alembic migrations for Bakery database."""
    try:
        # Prefer the in-container path used by Helm/Kubernetes.
        alembic_ini = Path("/app/bakery/alembic.ini")
        if not alembic_ini.exists():
            # Fallback for local execution from repo checkout.
            alembic_ini = Path(__file__).resolve().parent / "alembic.ini"

        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        alembic_cfg.set_main_option("script_location", str(alembic_ini.parent / "alembic"))
        existing_tables, alembic_revisions = inspect_schema_state(settings.database_url)
        strategy = determine_migration_strategy(existing_tables, alembic_revisions)

        logger.info(
            "Running Bakery database migrations",
            alembic_ini=str(alembic_ini),
            database_host=settings.database_host,
            database_name=settings.database_name,
            strategy=strategy,
            alembic_revisions=alembic_revisions,
        )

        if strategy == "stamp":
            logger.warning(
                "Bakery schema exists without Alembic version table; stamping current schema",
                existing_tables=sorted(MANAGED_TABLES),
            )
            command.stamp(alembic_cfg, "head")
            logger.info("Bakery database schema stamped successfully")
            return True

        if strategy == "error":
            logger.error(
                "Bakery schema is partially initialized without Alembic version table",
                existing_tables=sorted(MANAGED_TABLES & existing_tables),
                expected_tables=sorted(MANAGED_TABLES),
            )
            return False

        command.upgrade(alembic_cfg, "head")
        logger.info("Bakery database migrations applied successfully")
        return True
    except Exception as e:
        logger.error("Failed to apply Bakery migrations", error=str(e))
        return False


def main() -> int:
    """
    Main entry point for database initialization.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    logger.info(
        "Starting Bakery database initialization",
        database_host=settings.database_host,
        database_name=settings.database_name,
    )

    # Wait for database to be available
    if not wait_for_database():
        logger.error("Database initialization failed: database not available")
        return 1

    # Run migrations
    if not run_migrations():
        logger.error("Database initialization failed: could not apply migrations")
        return 1

    logger.info("Bakery database initialization completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
