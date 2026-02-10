#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Middleware for request ID tracking."""

import time
import uuid
import os
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from api.core.logging import get_logger

logger = get_logger(__name__)
INSTANCE_ID = os.getenv("POD_NAME") or os.getenv("HOSTNAME") or "local"


class PreHeatMiddleware(BaseHTTPMiddleware):
    """Pre-heat middleware to inject req_id for ALL HTTP verbs.

    This middleware performs the "pre_heat" function by:
    - Generating a unique req_id (UUID) for every incoming request
    - Injecting it into the request state for use in route handlers
    - Adding it to response headers for client tracking
    - Logging request/response timing
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and inject req_id."""

        # Pre-heat: Generate or extract req_id
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        instance_id = request.headers.get("X-Instance-ID", INSTANCE_ID)

        # Inject req_id into request state for access in route handlers
        request.state.req_id = req_id
        request.state.instance_id = instance_id

        # Track processing time
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate processing time
        latency_ms = int((time.time() - start_time) * 1000)

        # Add req_id and timing to response headers
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Latency-Ms"] = str(latency_ms)
        response.headers["X-Instance-ID"] = instance_id

        # Log request
        logger.info(
            "Request completed",
            extra={
                "req_id": req_id,
                "instance_id": instance_id,
                "method": request.method,
                "path": str(request.url.path),
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )

        return response


def get_req_id(request: Request) -> str:
    """Get req_id from request state (injected by pre_heat middleware)."""
    return getattr(request.state, "req_id", str(uuid.uuid4()))
