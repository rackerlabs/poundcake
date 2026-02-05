#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database configuration and session management."""

import time
from api.core.logging import get_logger
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from api.core.config import settings

logger = get_logger(__name__)

# Create engine
engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,  # Validates connections before using them
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Database session dependency for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database using Alembic migrations with retry logic."""
    from alembic.config import Config
    from alembic import command
    import os

    # Get the directory containing this file
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini_path = os.path.join(current_dir, "alembic.ini")

    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    engine.dispose()

    max_retries = 10
    retry_interval = 5

    for i in range(max_retries):
        try:
            logger.info(f"Attempting to run database migrations (Attempt {i+1}/{max_retries})...")
            command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations applied successfully.")
            return
        except Exception as e:
            if i < max_retries - 1:
                logger.warning(f"Database migration failed: {e}. Retrying in {retry_interval}s...")
                time.sleep(retry_interval)
            else:
                logger.error("Could not apply database migrations after maximum retries.")
                raise e
