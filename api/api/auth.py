#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Authentication and session management for PoundCake."""

import secrets
import base64
from datetime import datetime, timedelta
from typing import Any

from fastapi import Cookie, HTTPException, Request, status, APIRouter, Response

from api.core.config import get_settings
from api.core.logging import get_logger
from api.schemas.schemas import SessionResponse

logger = get_logger(__name__)

# Standard router definition for auth endpoints
router = APIRouter()

# In-memory session store (for single instance deployments)
# NOTE: Switch to Redis if scaling to multiple Kubernetes replicas
_sessions: dict[str, dict[str, Any]] = {}


def get_admin_credentials() -> tuple[str, str] | None:
    """Get admin credentials from Kubernetes secret or environment."""
    settings = get_settings()

    if not settings.auth_enabled:
        return None

    # 1. Attempt to load from Kubernetes (Helm/K8s Environment)
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

        v1 = client.CoreV1Api()
        secret = v1.read_namespaced_secret(
            name=settings.auth_secret_name,
            namespace=settings.auth_secret_namespace,
        )

        username = base64.b64decode(secret.data["username"]).decode("utf-8")
        password = base64.b64decode(secret.data["password"]).decode("utf-8")

        logger.info("Credentials loaded from K8s secret: %s", settings.auth_secret_name)
        return (username, password)

    except Exception as e:
        logger.debug("K8s secret fetch skipped or failed (Normal for local dev): %s", str(e))

        # 2. Fallback to environment variables (Docker Compose / Local Dev)
        if settings.auth_dev_username and settings.auth_dev_password:
            return (settings.auth_dev_username, settings.auth_dev_password)

        logger.error("No admin credentials configured in K8s or Environment!")
        return None


def create_session(username: str) -> str:
    """Create a new session and return the token."""
    settings = get_settings()
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(seconds=settings.auth_session_timeout)

    _sessions[session_token] = {
        "username": username,
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
    }

    logger.info("Session created for %s, expires at %s", username, expires_at)
    return session_token


def validate_session(session_token: str | None) -> str | None:
    """Validate token; returns username if valid, None if expired/not found."""
    if not session_token:
        return None

    session = _sessions.get(session_token)
    if not session:
        return None

    if datetime.utcnow() > session["expires_at"]:
        del _sessions[session_token]
        return None

    return session["username"]


def destroy_session(session_token: str | None) -> None:
    """Manual logout/session destruction."""
    if session_token in _sessions:
        del _sessions[session_token]
        logger.info("Session destroyed.")


def verify_credentials(username: str, password: str) -> bool:
    """Compare input against master admin credentials."""
    credentials = get_admin_credentials()
    if not credentials:
        return False

    admin_user, admin_pass = credentials
    return username == admin_user and password == admin_pass


def require_auth_if_enabled(
    request: Request, session_token: str | None = Cookie(default=None)
) -> str | None:
    """Dependency for FastAPI routes. Checks if auth is enabled and validates session."""
    settings = get_settings()

    if not settings.auth_enabled:
        return None

    # Alignment with main.py versioned routes
    public_paths = [
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/health",
        "/api/v1/auth/login",
        "/metrics",
        "/api/v1/alerts",
    ]

    if request.url.path in public_paths or request.url.path.startswith("/static/"):
        return None

    username = validate_session(session_token)
    if not username:
        if "text/html" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid session required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return username


@router.post("/auth/login", response_model=SessionResponse)
async def login(request: Request, response: Response) -> SessionResponse:
    """Simple login endpoint to set session."""
    req_id = request.state.req_id

    try:
        data = await request.json()
        username = data.get("username")
        password = data.get("password")

        logger.info("Login attempt", extra={"req_id": req_id, "username": username})

        if verify_credentials(username, password):
            token = create_session(username)
            session_data = _sessions[token]

            # Set session cookie
            response.set_cookie(
                key="session_token",
                value=token,
                httponly=True,
                samesite="lax",
                secure=False,  # Set to True if using HTTPS
                path="/",  # Make cookie available to all paths
                max_age=get_settings().auth_session_timeout,
            )

            logger.info("Login successful", extra={"req_id": req_id, "username": username})

            return SessionResponse(
                session_id=token,
                username=username,
                expires_at=session_data["expires_at"].isoformat(),
                token_type="Bearer",
            )

        logger.warning("Invalid credentials", extra={"req_id": req_id, "username": username})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Login failed", extra={"req_id": req_id, "error": str(e)}, exc_info=True)
        raise HTTPException(status_code=400, detail="Malformed request")


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    """Logout and destroy session."""
    req_id = request.state.req_id
    session_token = request.cookies.get("session_token")

    if session_token:
        username = _sessions.get(session_token, {}).get("username", "unknown")
        destroy_session(session_token)
        logger.info("User logged out", extra={"req_id": req_id, "username": username})
    else:
        logger.info("Logout attempted without session", extra={"req_id": req_id})

    # Clear the session cookie
    response.delete_cookie(key="session_token", path="/")

    return {"message": "Logged out successfully"}
