#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
set -e

# Move to the directory where alembic.ini lives
cd /app

echo "========================================="
echo "  PoundCake Orchestration Starting"
echo "========================================="

MIGRATION_COUNT=$(find alembic/versions -name "*.py" ! -name "__init__*" ! -path "*/__ pycache__/*" 2>/dev/null | wc -l)
if [ "$MIGRATION_COUNT" -eq 0 ]; then
    echo "✗ No checked-in migrations found in /app/alembic/versions"
    exit 1
fi
echo "[OK] Found $MIGRATION_COUNT existing migration(s)"

# Run the single alpha baseline. The bootstrap wrapper allows an unstamped
# partial baseline to finish, but rejects unexpected revision chains.
echo "Running database baseline bootstrap..."
python3 -m api.scripts.bootstrap_schema

if [ $? -eq 0 ]; then
    echo "[OK] Database baseline bootstrap completed successfully"
else
    echo "✗ Database baseline bootstrap failed!"
    exit 1
fi

# Start the Application
# --no-access-log: Disable uvicorn access logs (our middleware logs all requests)
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --no-access-log
