"""Middleware for request ID tracking and API call logging."""
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from api.core.logging import get_logger
from api.core.database import SessionLocal
from api.models.models import APICall

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID to all requests and log ALL calls to database."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add request ID."""
        
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Store request ID in request state for access in route handlers
        request.state.request_id = request_id
        
        # Add request ID to response headers
        start_time = time.time()
        
        # Log ALL requests to database (including GET)
        api_call = None
        try:
            # Read request body for non-GET requests
            body_json = None
            if request.method != "GET":
                body = await request.body()
                # Parse body as JSON if possible
                try:
                    import json
                    body_json = json.loads(body) if body else None
                except:
                    body_json = None
            
            # Create API call record for ALL requests
            db = SessionLocal()
            try:
                api_call = APICall(
                    request_id=request_id,
                    method=request.method,
                    path=str(request.url.path),
                    headers=dict(request.headers),
                    query_params=dict(request.query_params),
                    body=body_json,
                    client_host=request.client.host if request.client else None,
                )
                db.add(api_call)
                db.commit()
                db.refresh(api_call)
                
                # Store API call ID in request state
                request.state.api_call_id = api_call.id
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error logging API call to database: {e}", exc_info=True)
        
        # Process request
        response = await call_next(request)
        
        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Processing-Time-Ms"] = str(processing_time_ms)
        
        # Update API call record with response information
        if api_call:
            try:
                db = SessionLocal()
                try:
                    api_call = db.query(APICall).filter(APICall.id == api_call.id).first()
                    if api_call:
                        api_call.status_code = response.status_code
                        api_call.processing_time_ms = processing_time_ms
                        api_call.completed_at = None  # Will be updated when response is sent
                        db.commit()
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error updating API call record: {e}", exc_info=True)
        
        # Log request
        logger.info(
            f"Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": str(request.url.path),
                "status_code": response.status_code,
                "processing_time_ms": processing_time_ms,
            }
        )
        
        return response


def get_request_id(request: Request) -> str:
    """Get request ID from request state."""
    return getattr(request.state, "request_id", "unknown")


def get_api_call_id(request: Request) -> int | None:
    """Get API call ID from request state."""
    return getattr(request.state, "api_call_id", None)
