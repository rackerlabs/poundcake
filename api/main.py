#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Main FastAPI Entrypoint for PoundCake (Helm-Ready)."""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.core.config import settings
from api.core.middleware import PreHeatMiddleware
from api.core.logging import setup_logging, get_logger
from api.core.http_client import close_async_http_client, close_sync_http_client
from api.api.health import router as health_router
from api.api.stackstorm import router as st2_bridge_router
from api.api.recipes import router as recipes_router
from api.api.ovens import router as ovens_router
from api.api.routes import router as alerts_router
from api.api.prometheus import router as prometheus_router
from api.api.auth import router as auth_router

# Configure logging with custom formatter that includes req_id
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # init_db() is removed from here
    logger.info("PoundCake API is starting up", extra={"req_id": "SYSTEM-STARTUP"})
    yield
    await close_async_http_client()
    close_sync_http_client()
    logger.info("Powering down PoundCake", extra={"req_id": "SYSTEM-SHUTDOWN"})


app = FastAPI(
    title="PoundCake API",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    redirect_slashes=False,  # Prevent 307 redirects for trailing slashes
)

# --- Middleware Registration ---
app.add_middleware(PreHeatMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Kubernetes / Prometheus Internal Metrics ---
@app.get("/metrics")
async def metrics():
    """Scrape endpoint for Prometheus Operator / ServiceMonitor."""
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- Route Registration ---

# 1. System & Monitoring
app.include_router(health_router, prefix="/api/v1", tags=["system"])
app.include_router(prometheus_router, prefix="/api/v1", tags=["prometheus"])

# 2. Security / Authentication
app.include_router(auth_router, prefix="/api/v1", tags=["security"])

# 3. Infrastructure & Automation
app.include_router(st2_bridge_router, prefix="/api/v1", tags=["infrastructure"])

# 4. Business Logic
app.include_router(recipes_router, prefix="/api/v1", tags=["logic"])
app.include_router(ovens_router, prefix="/api/v1", tags=["executor"])

# 5. Alert Ingestion (webhook)
app.include_router(alerts_router, prefix="/api/v1", tags=["ingestion"])


@app.get("/")
async def root():
    return {"status": "online", "component": "poundcake-api"}


# Local development entrypoint
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app", host=settings.server_host, port=settings.server_port, reload=settings.debug
    )
