#!/bin/sh
# PoundCake UI entrypoint script
# Substitutes API_URL in nginx config template and starts nginx

set -e

# Default API URL if not provided
API_URL="${API_URL:-http://poundcake:8080}"

# Substitute only API_URL in the nginx config template
# Using envsubst with explicit variable list to avoid replacing nginx variables
envsubst '${API_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

echo "PoundCake UI starting with API_URL=${API_URL}"

# Execute the main command (nginx)
exec "$@"
