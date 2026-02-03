#!/bin/bash
# PoundCake Test Runner
# Runs all tests with proper error handling and reporting

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

PASSED=0
FAILED=0

echo "========================================"
echo "PoundCake Test Suite"
echo "========================================"
echo ""

# Function to run a test and track results
run_test() {
    local test_name=$1
    local test_command=$2
    
    echo "[INFO] Running: $test_name"
    echo "Command: $test_command"
    echo ""
    
    if eval "$test_command"; then
        echo "[PASS] $test_name"
        echo ""
        PASSED=$((PASSED + 1))
        return 0
    else
        echo "[FAIL] $test_name"
        echo ""
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Check prerequisites
echo "Checking prerequisites..."

# Check if pytest is installed
if ! python -m pytest --version > /dev/null 2>&1; then
    echo "[WARN] pytest not found. Install with: pip install -r requirements.txt"
    echo "Skipping Python unit tests."
    SKIP_UNIT=true
else
    echo "[OK] pytest found"
    SKIP_UNIT=false
fi

# Check if services are running (for integration tests)
if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    echo "[OK] API is running"
    SKIP_INTEGRATION=false
else
    echo "[WARN] API not reachable at localhost:8000"
    echo "Skipping integration tests. Start services with: docker compose up -d"
    SKIP_INTEGRATION=true
fi

# Check if jq is installed (for flow test)
if command -v jq > /dev/null 2>&1; then
    echo "[OK] jq found"
    SKIP_FLOW=false
else
    echo "[WARN] jq not found. Install with: apt-get install jq (Ubuntu) or brew install jq (macOS)"
    echo "Skipping flow test."
    SKIP_FLOW=true
fi

echo ""
echo "========================================"
echo "Running Tests"
echo "========================================"
echo ""

# 1. Python Unit Tests
if [ "$SKIP_UNIT" = false ]; then
    echo "--- Python Unit Tests ---"
    echo ""
    
    run_test "Model Tests" "python -m pytest tests/test_models.py -v" || true
    run_test "API Health Tests" "python -m pytest tests/test_api_health.py -v" || true
    
    echo ""
fi

# 2. Integration Tests
if [ "$SKIP_INTEGRATION" = false ]; then
    echo "--- Integration Tests ---"
    echo ""
    
    run_test "Webhook Test" "./tests/test_webhook.sh" || true
    
    echo ""
fi

# 3. Flow Test
if [ "$SKIP_INTEGRATION" = false ] && [ "$SKIP_FLOW" = false ]; then
    echo "--- End-to-End Flow Test ---"
    echo ""
    
    run_test "Complete Flow Test" "./tests/test_flow.sh" || true
    
    echo ""
fi

# Summary
echo "========================================"
echo "Test Summary"
echo "========================================"
echo ""

TOTAL=$((PASSED + FAILED))

if [ $TOTAL -eq 0 ]; then
    echo "[WARN] No tests were run"
    echo ""
    echo "Possible reasons:"
    echo "  - pytest not installed: pip install -r requirements.txt"
    echo "  - Services not running: docker compose up -d"
    echo "  - jq not installed: apt-get install jq"
    exit 1
fi

echo "Total Tests: $TOTAL"
echo "Passed: $PASSED"
if [ $FAILED -gt 0 ]; then
    echo "Failed: $FAILED"
else
    echo "Failed: $FAILED"
fi
echo ""

# Exit code
if [ $FAILED -eq 0 ]; then
    echo "[OK] All tests passed!"
    exit 0
else
    echo "[FAIL] Some tests failed."
    echo ""
    echo "Debugging tips:"
    echo "  - Check service logs: docker compose logs"
    echo "  - Verify services running: docker compose ps"
    echo "  - Check API health: curl http://localhost:8000/api/v1/health"
    echo "  - Run specific test manually for details"
    exit 1
fi
