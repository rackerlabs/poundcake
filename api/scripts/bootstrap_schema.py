"""Bootstrap the alpha single-revision schema safely."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from api.core.config import get_settings

BASELINE_REVISION = "2026_02_03_1600"


def get_sync_database_url() -> str:
    url = get_settings().database_url
    if "+aiomysql" in url:
        return url.replace("+aiomysql", "+pymysql")
    return url


def get_alembic_config() -> Config:
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", get_sync_database_url())
    return config


def get_current_revisions(database_url: str | None = None) -> list[str]:
    engine = create_engine(database_url or get_sync_database_url())
    with engine.begin() as conn:
        inspector = sa.inspect(conn)
        if not inspector.has_table("alembic_version"):
            return []
        rows = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
    return [str(row) for row in rows]


def ensure_baseline_schema() -> None:
    revisions = get_current_revisions()
    if revisions == [BASELINE_REVISION]:
        print(f"[OK] Database already stamped at baseline revision {BASELINE_REVISION}")
        return
    if revisions:
        raise RuntimeError(
            "Unexpected Alembic revision(s): "
            + ", ".join(revisions)
            + f"; expected only {BASELINE_REVISION}"
        )

    print(f"Running database baseline migration {BASELINE_REVISION}...")
    command.upgrade(get_alembic_config(), "head")

    revisions = get_current_revisions()
    if revisions != [BASELINE_REVISION]:
        raise RuntimeError(
            "Database baseline migration finished without expected Alembic stamp; "
            f"found revisions: {revisions or 'none'}"
        )
    print(f"[OK] Database baseline schema verified at revision {BASELINE_REVISION}")


def main() -> None:
    ensure_baseline_schema()


if __name__ == "__main__":
    main()
