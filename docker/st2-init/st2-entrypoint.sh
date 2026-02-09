#!/bin/bash
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# StackStorm Service Entrypoint with Runtime Config Templating
# This script substitutes environment variables into st2.conf before starting the service

set -e

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Setup Environment Paths (CRITICAL for Service Discovery)
export PYTHONPATH=$PYTHONPATH:/opt/stackstorm/st2/lib/python3.10/site-packages
export PATH=$PATH:/opt/stackstorm/st2/bin

# Make ST2_API_KEY available in interactive shells if the key file exists
if [ -f "/app/config/st2_api_key" ]; then
    if ! grep -q "export ST2_API_KEY=" /root/.bashrc 2>/dev/null; then
        echo "export ST2_API_KEY=\$(cat /app/config/st2_api_key)" >> /root/.bashrc
    fi
fi

# Install envsubst if not available
if ! command -v envsubst &> /dev/null; then
    log "envsubst not found, installing gettext-base..."
    apt-get update -qq && apt-get install -y -qq gettext-base > /dev/null 2>&1
    log "[OK] envsubst installed"
fi

# Check if template exists
if [ ! -f "/etc/st2/st2.conf.template" ]; then
    log "ERROR: /etc/st2/st2.conf.template not found"
    exit 1
fi

# Check required environment variables
if [ -z "$MONGO_PASSWORD" ]; then
    log "ERROR: MONGO_PASSWORD environment variable not set"
    exit 1
fi

if [ -z "$RABBITMQ_PASSWORD" ]; then
    log "ERROR: RABBITMQ_PASSWORD environment variable not set"
    exit 1
fi

log "Templating st2.conf with environment variables..."

# Use envsubst to replace ${MONGO_PASSWORD} and ${RABBITMQ_PASSWORD}
envsubst '${MONGO_PASSWORD} ${RABBITMQ_PASSWORD}' < /etc/st2/st2.conf.template > /etc/st2/st2.conf

# Verify the file was created
if [ ! -f "/etc/st2/st2.conf" ]; then
    log "ERROR: Failed to create /etc/st2/st2.conf"
    exit 1
fi

# Register Content
log "Registering StackStorm content and setting up virtualenvs..."
st2-register-content --register-all --register-setup-virtualenvs --config-file /etc/st2/st2.conf

if [ $? -eq 0 ]; then
    log "[OK] Content registration successful"
    log "Packs directory:"
    ls -la /opt/stackstorm/packs/ 2>/dev/null | head -10 || log "Could not list packs"
else
    log "[ERROR] Content registration failed!"
    log "This service may not function correctly without registered content."
    # Don't exit - let the service start and show errors for debugging
fi

# Start the Service
log "[OK] Initialization complete. Starting: $@"
exec "$@"
