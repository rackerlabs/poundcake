#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database configuration and session management."""

import time
from typing import AsyncGenerator

from api.core.logging import get_logger
from api.core.config import settings
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = get_logger(__name__)


def get_sync_database_url() -> str:
    """Return a sync DB URL for tooling like Alembic."""
    url = settings.database_url
    if "+aiomysql" in url:
        return url.replace("+aiomysql", "+pymysql")
    return url


def get_async_database_url() -> str:
    """Return an async DB URL for the runtime engine."""
    url = settings.database_url
    if "+pymysql" in url:
        return url.replace("+pymysql", "+aiomysql")
    return url


# Create async engine
engine = create_async_engine(
    get_async_database_url(),
    echo=settings.database_echo,
    pool_pre_ping=True,  # Validates connections before using them
    pool_size=10,
    max_overflow=20,
)

SessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency for FastAPI."""
    async with SessionLocal() as db:
        yield db


def init_db() -> None:
    """Initialize database using Alembic migrations with retry logic."""
    from alembic.config import Config
    from alembic import command
    import os

    # Get the directory containing this file
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini_path = os.path.join(current_dir, "alembic.ini")

    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", get_sync_database_url())

    max_retries = 10
    retry_interval = 5

    for i in range(max_retries):
        try:
            logger.info(
                "Attempting to run database migrations",
                extra={"attempt": i + 1, "max_attempts": max_retries},
            )
            command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations applied successfully.")
            return
        except Exception as e:
            if i < max_retries - 1:
                logger.warning(
                    "Database migration failed; retrying",
                    extra={
                        "attempt": i + 1,
                        "max_attempts": max_retries,
                        "retry_interval": retry_interval,
                        "error": str(e),
                    },
                )
                time.sleep(retry_interval)
            else:
                logger.error(
                    "Could not apply database migrations after maximum retries",
                    extra={"max_attempts": max_retries, "error": str(e)},
                )
                raise e
