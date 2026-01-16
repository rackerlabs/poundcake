"""Example tests for the API."""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert "app" in response.json()
    assert "version" in response.json()


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "redis" in data
    assert "celery" in data


def test_webhook_missing_alerts():
    """Test webhook with empty alerts list."""
    payload = {
        "version": "4",
        "groupKey": "test",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "webhook",
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://test",
        "alerts": []
    }
    
    response = client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_alerts"
    assert "request_id" in response.headers.get("X-Request-ID", "")


def test_request_id_header():
    """Test that request ID is added to responses."""
    response = client.get("/")
    # GET requests don't generate request IDs by default
    # but non-GET requests do
    
    payload = {
        "version": "4",
        "groupKey": "test",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "webhook",
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://test",
        "alerts": []
    }
    
    response = client.post("/api/v1/webhook", json=payload)
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


# Note: Full integration tests would require database and Redis setup
# These are basic smoke tests to verify the API structure
