#!/bin/bash
set -e

# Move to the directory where alembic.ini lives
cd /app

echo "========================================="
echo "  PoundCake Orchestration Starting"
echo "========================================="

# Check if any migrations exist (excluding __init__.py and __pycache__)
MIGRATION_COUNT=$(find alembic/versions -name "*.py" ! -name "__init__*" ! -path "*/__ pycache__/*" 2>/dev/null | wc -l)

if [ "$MIGRATION_COUNT" -eq 0 ]; then
    echo "⚠️  No migrations found. Creating initial schema migration..."
    alembic revision --autogenerate -m "initial_schema"
    echo "✓ Initial migration created"
else
    echo "✓ Found $MIGRATION_COUNT existing migration(s)"
fi

# Run database migrations
echo "Running database migrations..."
python3 -m alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✓ Database migrations applied successfully"
else
    echo "✗ Database migration failed!"
    exit 1
fi

echo "========================================="
echo "  Launching PoundCake API"
echo "========================================="

# Start the Application
# --no-access-log: Disable uvicorn access logs (our middleware logs all requests)
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --no-access-log
