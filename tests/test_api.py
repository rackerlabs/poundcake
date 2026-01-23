"""Tests for the PoundCake API."""

from fastapi.testclient import TestClient
from api.main import app

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
    assert "stackstorm" in data


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
        "alerts": [],
    }

    response = client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "no_alerts"
    assert "request_id" in data


def test_request_id_generation():
    """Test that request ID is generated for webhook requests."""
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
        "alerts": [],
    }

    response = client.post("/api/v1/webhook", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "request_id" in data
    assert len(data["request_id"]) > 0


def test_stats_endpoint():
    """Test statistics endpoint."""
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_alerts" in data
    assert "total_recipes" in data
    assert "total_executions" in data


# Note: Full integration tests require database setup
# These are basic smoke tests to verify the API structure

