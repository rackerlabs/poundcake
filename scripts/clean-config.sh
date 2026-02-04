#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
# Clean PoundCake Configuration for Fresh Deployment
#
# Run this before deploying if you want to force a complete fresh start.
# This removes the API key file so st2client will generate a new one.

set -e

echo "========================================="
echo "  PoundCake Configuration Cleanup"
echo "========================================="
echo ""

# Remove API key file
if [ -f "config/st2_api_key" ]; then
    echo "Removing old API key file..."
    rm -f config/st2_api_key
    echo "[OK] API key file deleted"
else
    echo "[INFO] No API key file found"
fi

echo ""
echo "========================================="
echo "  Cleanup Complete!"
echo "========================================="
echo ""
echo "You can now run a fresh deployment:"
echo "  docker compose down -v"
echo "  docker compose build"
echo "  docker compose up -d"
echo ""
echo "st2client will generate a new API key automatically."
echo ""
