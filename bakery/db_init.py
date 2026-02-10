#!/usr/bin/env python3
"""Database initialization script for Bakery."""

import sys
import time
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from bakery.config import settings
from bakery.database import Base

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


def create_tables() -> bool:
    """
    Create all database tables.

    Returns:
        True if tables were created successfully, False otherwise
    """
    try:
        logger.info("Creating database tables")
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        return True
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))
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

    # Create tables
    if not create_tables():
        logger.error("Database initialization failed: could not create tables")
        return 1

    logger.info("Bakery database initialization completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
