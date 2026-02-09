#!/usr/bin/env python3
"""Bakery FastAPI application - PoundCake ticketing system integration."""

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import structlog

from bakery import __version__
from bakery.config import settings
from bakery.api.health import router as health_router
from bakery.api.messages import router as messages_router
from bakery.api.tickets import router as tickets_router


# Configure structured logging
def configure_logging() -> None:
    """Configure structured logging for Bakery."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Lifespan context manager for FastAPI application.

    Handles startup and shutdown events.
    """
    logger = structlog.get_logger()
    logger.info(
        "Bakery starting",
        version=__version__,
        environment=settings.environment,
    )
    yield
    logger.info("Bakery shutting down")


# Configure logging
configure_logging()

# Create FastAPI application
app = FastAPI(
    title="Bakery",
    description="PoundCake ticketing system integration service",
    version=__version__,
    lifespan=lifespan,
)


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler.

    Args:
        request: FastAPI request
        exc: Exception that was raised

    Returns:
        JSON error response
    """
    logger = structlog.get_logger()
    logger.error(
        "Unhandled exception",
        exc_info=exc,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.environment == "development" else None,
        },
    )


# Include routers
app.include_router(health_router, prefix=settings.api_prefix, tags=["health"])
app.include_router(messages_router, prefix=settings.api_prefix, tags=["messages"])
app.include_router(tickets_router, prefix=settings.api_prefix, tags=["tickets"])


# Root endpoint
@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint.

    Returns:
        Service information
    """
    return {
        "service": "Bakery",
        "version": __version__,
        "description": "PoundCake ticketing system integration service",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bakery.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
        reload=settings.environment == "development",
    )
