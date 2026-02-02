#!/bin/bash
# StackStorm Service Entrypoint with Runtime Config Templating
# This script substitutes environment variables into st2.conf before starting the service

set -e

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

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

log "✓ st2.conf generated successfully"

# Execute the command passed to this script (the actual ST2 service)
log "Starting StackStorm service: $@"
exec "$@"
