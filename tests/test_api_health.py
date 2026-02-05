#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Basic API health tests for PoundCake."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_database():
    """Mock database connection for all tests."""
    with patch("api.core.database.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__.return_value = mock_db
        mock_session.return_value.__aexit__.return_value = None
        yield mock_db


@pytest.fixture(autouse=True)
def mock_stackstorm():
    """Mock StackStorm API calls for all tests."""
    with patch(
        "api.services.stackstorm_service.StackStormClient.health_check",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_health:
        yield mock_health


def test_health_endpoint_structure(client):
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
    assert data["info"]["title"] == "PoundCake API"


def test_stats_endpoint(client):
    """Test stats endpoint returns expected structure."""
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    data = response.json()

    # Check all required fields
    required_fields = [
        "total_alerts",
        "total_recipes",
        "total_executions",
        "alerts_by_processing_status",
        "alerts_by_alert_status",
        "executions_by_status",
        "recent_alerts",
    ]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"
