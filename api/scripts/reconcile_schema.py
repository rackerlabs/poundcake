#!/usr/bin/env python3
"""Idempotent schema reconciliation for already-stamped databases.

This covers alpha-era baseline migration edits where a database may already be
at Alembic head but still miss newer columns/indexes added to the baseline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

script_dir = Path(__file__).parent
api_dir = script_dir.parent
project_root = api_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from api.core.logging import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)


def _sync_database_url_from_env() -> str:
    url = os.getenv("POUNDCAKE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("POUNDCAKE_DATABASE_URL is not set")
    if "+aiomysql" in url:
        return url.replace("+aiomysql", "+pymysql")
    return url


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
            LIMIT 1
            """),
        {"table_name": table_name},
    ).first()
    return row is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            LIMIT 1
            """),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _index_exists(conn, table_name: str, index_name: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND INDEX_NAME = :index_name
            LIMIT 1
            """),
        {"table_name": table_name, "index_name": index_name},
    ).first()
    return row is not None


def _apply_table_reconciliation(conn, table_name: str, ddl_statements: list[str]) -> None:
    if not _table_exists(conn, table_name):
        logger.warning(
            "Skipping reconciliation for missing table",
            extra={"table_name": table_name, "req_id": "SYSTEM-DB-RECONCILE"},
        )
        return

    for ddl in ddl_statements:
        logger.info(
            "Applying schema reconciliation DDL",
            extra={"table_name": table_name, "ddl": ddl, "req_id": "SYSTEM-DB-RECONCILE"},
        )
        conn.execute(text(ddl))


def reconcile_schema() -> None:
    db_url = _sync_database_url_from_env()
    engine = create_engine(db_url, future=True)

    try:
        with engine.begin() as conn:
            orders_ddl: list[str] = []

            if not _column_exists(conn, "orders", "bakery_ticket_state"):
                orders_ddl.append(
                    "ALTER TABLE orders ADD COLUMN bakery_ticket_state VARCHAR(32) NULL"
                )
            if not _column_exists(conn, "orders", "bakery_permanent_failure"):
                orders_ddl.append(
                    "ALTER TABLE orders ADD COLUMN bakery_permanent_failure BOOLEAN NOT NULL DEFAULT 0"
                )
            if not _column_exists(conn, "orders", "bakery_last_error"):
                orders_ddl.append("ALTER TABLE orders ADD COLUMN bakery_last_error TEXT NULL")

            if not _index_exists(conn, "orders", "ix_orders_bakery_ticket_state"):
                orders_ddl.append(
                    "ALTER TABLE orders ADD INDEX ix_orders_bakery_ticket_state (bakery_ticket_state)"
                )
            if not _index_exists(conn, "orders", "ix_orders_bakery_permanent_failure"):
                orders_ddl.append(
                    "ALTER TABLE orders ADD INDEX ix_orders_bakery_permanent_failure (bakery_permanent_failure)"
                )

            _apply_table_reconciliation(conn, "orders", orders_ddl)

            suppression_ddl: list[str] = []
            if not _column_exists(conn, "suppression_summaries", "total_cleared"):
                suppression_ddl.append(
                    "ALTER TABLE suppression_summaries ADD COLUMN total_cleared INTEGER NOT NULL DEFAULT 0"
                )
            if not _column_exists(conn, "suppression_summaries", "total_still_firing"):
                suppression_ddl.append(
                    "ALTER TABLE suppression_summaries ADD COLUMN total_still_firing INTEGER NOT NULL DEFAULT 0"
                )
            if not _column_exists(conn, "suppression_summaries", "still_firing_alerts_json"):
                suppression_ddl.append(
                    "ALTER TABLE suppression_summaries ADD COLUMN still_firing_alerts_json JSON NULL"
                )

            _apply_table_reconciliation(conn, "suppression_summaries", suppression_ddl)

            logger.info(
                "Schema reconciliation complete",
                extra={"req_id": "SYSTEM-DB-RECONCILE"},
            )
    finally:
        engine.dispose()


def main() -> None:
    logger.info(
        "Starting schema reconciliation",
        extra={"req_id": "SYSTEM-DB-RECONCILE"},
    )
    reconcile_schema()


if __name__ == "__main__":
    main()
