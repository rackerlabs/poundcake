#!/usr/bin/env python3
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Database migration management script using alembic."""

import sys
import os
from alembic.config import Config
from alembic import command

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.core.database import get_sync_database_url


def get_alembic_config():
    """Get Alembic configuration."""
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(current_dir, "alembic.ini")

    config = Config(alembic_ini)
    config.set_main_option("sqlalchemy.url", get_sync_database_url())

    return config


def upgrade(revision="head"):
    """Upgrade database to a specific revision.

    Args:
        revision: Target revision (default: "head" for latest)
    """
    config = get_alembic_config()
    print(f"Upgrading database to revision: {revision}")
    command.upgrade(config, revision)
    print("OK: Database upgrade complete")


def downgrade(revision="-1"):
    """Downgrade database to a specific revision.

    Args:
        revision: Target revision (default: "-1" for one step back)
    """
    config = get_alembic_config()
    print(f"Downgrading database to revision: {revision}")
    command.downgrade(config, revision)
    print("OK: Database downgrade complete")


def current():
    """Show current database revision."""
    config = get_alembic_config()
    print("Current database revision:")
    command.current(config)


def history():
    """Show migration history."""
    config = get_alembic_config()
    print("Migration history:")
    command.history(config)


def show_help():
    """Show help message."""
    print("""
PoundCake Database Migration Manager

Usage: python api/migrate.py <command> [args]

Commands:
    upgrade [revision]      Upgrade to a revision (default: head)
    downgrade [revision]    Downgrade to a revision (default: -1)
    current                 Show current revision
    history                 Show migration history
    help                    Show this help message

Alpha migration policy:
    PoundCake uses a single full-schema baseline revision for fresh installs.
    Do not create chained Alembic revisions or use stamp for normal workflows.
    Schema changes should be folded into the baseline migration file instead.

Examples:
    python api/migrate.py upgrade
    python api/migrate.py upgrade +1
    python api/migrate.py downgrade
    python api/migrate.py downgrade -2
    python api/migrate.py current
    python api/migrate.py history
    """)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    command_name = sys.argv[1].lower()

    try:
        if command_name == "upgrade":
            revision = sys.argv[2] if len(sys.argv) > 2 else "head"
            upgrade(revision)

        elif command_name == "downgrade":
            revision = sys.argv[2] if len(sys.argv) > 2 else "-1"
            downgrade(revision)

        elif command_name == "current":
            current()

        elif command_name == "history":
            history()

        elif command_name in ["help", "-h", "--help"]:
            show_help()

        else:
            print(f"Error: Unknown command: {command_name}")
            show_help()
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
