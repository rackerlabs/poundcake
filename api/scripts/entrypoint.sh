#!/bin/bash
set -e

# Move to the directory where alembic.ini lives (likely /app or /app/api)
cd /app

echo "--- Starting PoundCake Orchestration ---"

# 1. Run Migrations
echo "Running database migrations..."
# Using 'python -m alembic' is often more reliable for pathing
python3 -m alembic upgrade head

echo "--- Migrations Successful. Launching API ---"

# 2. Start the Application
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
