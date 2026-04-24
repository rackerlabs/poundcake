"""Idempotent schema repairs for alpha baseline changes."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table, create_engine, inspect

from api.core.database import Base, get_sync_database_url
from api.core.logging import get_logger, setup_logging
from api.models.models import (
    ReleaseUpdateNotification,
    ReleaseUpdateNotificationDelivery,
)

setup_logging()
logger = get_logger(__name__)

RELEASE_UPDATE_TABLES: tuple[Table, ...] = (
    cast(Table, ReleaseUpdateNotification.__table__),
    cast(Table, ReleaseUpdateNotificationDelivery.__table__),
)
RELEASE_UPDATE_TABLE_NAMES = tuple(table.name for table in RELEASE_UPDATE_TABLES)


def ensure_release_update_tables(database_url: str | None = None) -> list[str]:
    """Create release update advisory tables missing from existing alpha installs."""
    engine = create_engine(database_url or get_sync_database_url())
    with engine.begin() as conn:
        existing_tables = set(inspect(conn).get_table_names())
        missing = [name for name in RELEASE_UPDATE_TABLE_NAMES if name not in existing_tables]
        if not missing:
            logger.info("Release update advisory tables already exist")
            return []
        Base.metadata.create_all(bind=conn, tables=list(RELEASE_UPDATE_TABLES))
        logger.info("Created release update advisory tables", extra={"tables": missing})
        return missing


def main() -> None:
    ensure_release_update_tables()


if __name__ == "__main__":
    main()
