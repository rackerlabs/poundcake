# PoundCake UI Docker Image
#
# This Dockerfile builds the container image for PoundCake UI, which is deployed
# via the Helm chart. The image is published to GitHub Container Registry.
#
# Build: docker build -t ghcr.io/aedan/poundcake-ui:VERSION -f ui/Dockerfile .
# Push:  docker push ghcr.io/aedan/poundcake-ui:VERSION

FROM nginx:alpine

# Copy static files
COPY ui/static /usr/share/nginx/html

# Copy nginx configuration as template (uses ${API_URL} placeholder)
COPY ui/nginx/nginx.conf /etc/nginx/templates/default.conf.template

# Copy and set up entrypoint script
COPY ui/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Default API URL - will be overridden by environment variable in Kubernetes
ENV API_URL=http://poundcake:8080

# Expose port
EXPOSE 80

# Labels
LABEL org.opencontainers.image.title="PoundCake UI" \
      org.opencontainers.image.description="Web UI for PoundCake auto-remediation framework" \
      org.opencontainers.image.authors="Jake Briggs" \
      org.opencontainers.image.source="https://github.com/aedan/poundCake"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

# Use custom entrypoint to substitute API_URL in nginx config
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
