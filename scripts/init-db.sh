#!/bin/bash
# Database Initialization Script for PoundCake
set -e

echo "========================================"
echo "Initializing PoundCake Database"
echo "========================================"

# Run the Python initialization script
docker compose exec api python /app/api/scripts/init_database.py

echo ""
echo "========================================"
echo "Database initialization complete!"
echo "========================================"
echo ""
echo "You can now restart services to apply changes:"
echo "  docker compose restart api oven timer"
