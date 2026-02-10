#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Basic API health tests for PoundCake."""

import pytest
from unittest.mock import patch, Mock, AsyncMock
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
        mock_db = AsyncMock()
        mock_result = Mock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session.return_value.__aenter__.return_value = mock_db
        mock_session.return_value.__aexit__.return_value = AsyncMock(return_value=None)
        yield mock_db


@pytest.fixture(autouse=True)
def mock_stackstorm():
    """Mock StackStorm API calls for all tests."""
    with patch("api.services.stackstorm_service.get_stackstorm_client") as mock_client:
        client = Mock()
        client.health_check = AsyncMock(return_value=True)
        mock_client.return_value = client
        yield mock_client


def test_health_endpoint_structure(client):
    """Test health endpoint returns expected structure."""
    response = client.get("/api/v1/health")
    data = response.json()

    # Check all required top-level fields
    required_fields = ["status", "version", "instance_id", "timestamp", "components"]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"

    # Check components structure
    assert isinstance(data["components"], dict), "components should be a dictionary"
    expected_components = ["database", "stackstorm", "mongodb", "rabbitmq", "redis"]
    for component in expected_components:
        assert component in data["components"], f"Missing component: {component}"
        # Each component should have status and message
        assert "status" in data["components"][component], f"{component} missing status"
        assert "message" in data["components"][component], f"{component} missing message"


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
