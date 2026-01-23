"""Pytest configuration and fixtures for PoundCake tests."""

import pytest
import os


@pytest.fixture
def base_url():
    """Provide base URL for integration tests.
    
    Integration tests are skipped unless POUNDCAKE_TEST_URL is set.
    """
    url = os.getenv("POUNDCAKE_TEST_URL")
    if not url:
        pytest.skip("Integration tests require POUNDCAKE_TEST_URL environment variable")
    return url


# Mark all tests in test_preheat.py as integration tests
def pytest_collection_modifyitems(items):
    """Add integration marker to tests that require running server."""
    for item in items:
        if "test_preheat" in item.nodeid:
            item.add_marker(pytest.mark.integration)
