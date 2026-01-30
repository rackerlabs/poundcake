#!/usr/bin/env python3
#
# ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
#
# ╔════════════════════════════════════════════════════════════════╗
# ____                        _  ____      _         
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____ 
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# ╚════════════════════════════════════════════════════════════════╝
#
"""Oven scheduler - runs the alert crawler on a configurable schedule.

This script starts the oven service crawler which:
1. Periodically scans for alerts with processing_status = 'NEW'
2. Matches recipes by group_name
3. Parses task_list and creates ovens
4. Triggers execution via POST to /api/v1/alerts/process

Can be run as:
- Standalone process (python scripts/oven_scheduler.py)
- Systemd service
- Kubernetes CronJob
- Docker container with custom entrypoint
"""

import os
import sys
import signal
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.services.oven import run_oven_crawler_loop, run_oven_crawler_once
from api.core.logging import get_logger

logger = get_logger(__name__)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down oven scheduler...")
    sys.exit(0)


def main():
    """Run oven scheduler with configurable interval."""
    parser = argparse.ArgumentParser(description="PoundCake Oven Scheduler")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("OVEN_CRAWLER_INTERVAL", "60")),
        help="Seconds between crawler runs (default: 60)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (useful for cron/kubernetes cronjob)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.getenv("POUNDCAKE_API_URL", "http://localhost:8000"),
        help="PoundCake API base URL",
    )

    args = parser.parse_args()

    # Set API URL environment variable
    os.environ["POUNDCAKE_API_URL"] = args.api_url

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 70)
    logger.info("PoundCake Oven Scheduler Starting")
    logger.info("=" * 70)
    logger.info(f"API URL: {args.api_url}")

    if args.once:
        logger.info("Mode: Run once and exit")
        result = run_oven_crawler_once()
        logger.info(f"Crawler result: {result}")
        sys.exit(0)
    else:
        logger.info(f"Mode: Continuous (interval: {args.interval}s)")
        logger.info("Press Ctrl+C to stop")
        run_oven_crawler_loop(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
