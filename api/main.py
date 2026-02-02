#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Main FastAPI Entrypoint for PoundCake (Helm-Ready)."""

import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.core.config import settings
from api.core.database import init_db
from api.core.middleware import PreHeatMiddleware
from api.api.health import router as health_router
from api.api.stackstorm import router as st2_bridge_router
from api.api.recipes import router as recipes_router
from api.api.ovens import router as ovens_router
from api.api.routes import router as alerts_router
from api.api.prometheus import router as prometheus_router
from api.api.auth import router as auth_router

# Configure logging based on Helm-injected settings
logging.basicConfig(level=getattr(logging, settings.log_level.upper()))
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # init_db() is removed from here
    logger.info("PoundCake API is starting up...")
    yield
    logger.info("Powering down PoundCake...")

app = FastAPI(
    title="PoundCake API",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None
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
app.include_router(prometheus_router, prefix="/api/v1/prometheus", tags=["prometheus"])

# 2. Security / Authentication
app.include_router(auth_router, prefix="/api/v1/auth", tags=["security"])

# 3. Infrastructure & Automation
app.include_router(st2_bridge_router, prefix="/api/v1/stackstorm", tags=["infrastructure"])

# 4. Business Logic
app.include_router(recipes_router, prefix="/api/v1/recipes", tags=["logic"])
app.include_router(ovens_router, prefix="/api/v1/ovens", tags=["executor"])

# 5. Alert Ingestion (webhook)
app.include_router(alerts_router, prefix="/api/v1/alerts", tags=["ingestion"])

@app.get("/")
async def root():
    return {"status": "online", "component": "poundcake-api"}

# Local development entrypoint
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.debug
    )
