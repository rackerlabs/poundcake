# ╔════════════════════════════════════════════════════════════════╗
#  ____                        _  ____      _         
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____ 
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# ╚════════════════════════════════════════════════════════════════╝
#
"""Basic API health tests for PoundCake."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_health_checks():
    """Mock database and StackStorm health checks."""
    with patch("api.api.health.get_db") as mock_db, \
         patch("api.api.health.requests.get") as mock_st2:
        
        # Mock database connection
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value = None
        
        # Mock StackStorm API check (returns 401 which we treat as healthy)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_st2.return_value = mock_response
        
        yield


def test_health_endpoint(client, mock_health_checks):
    """Test health endpoint returns healthy status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"
    assert "database" in data
    assert "stackstorm" in data
    assert "version" in data


def test_health_endpoint_structure(client, mock_health_checks):
    """Test health endpoint returns expected structure."""
    response = client.get("/api/v1/health")
    data = response.json()
    
    # Check all required fields
    required_fields = ["status", "version", "database", "stackstorm", "timestamp"]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


def test_root_endpoint(client):
    """Test root endpoint returns API info."""
    response = client.get("/")
    assert response.status_code == 200


def test_openapi_endpoint(client):
    """Test OpenAPI schema is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data
    assert data["info"]["title"] == "PoundCake"


def test_ready_endpoint(client, mock_health_checks):
    """Test readiness endpoint."""
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200


def test_live_endpoint(client):
    """Test liveness endpoint."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
