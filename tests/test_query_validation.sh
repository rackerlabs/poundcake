#!/bin/bash
#
# Test script for query parameter validation
#

API_URL="http://localhost:8000/api/v1"

echo "============================================"
echo "  Query Parameter Validation Tests"
echo "============================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_count=0
pass_count=0
fail_count=0

run_test() {
    local name="$1"
    local url="$2"
    local expected_status="$3"

    test_count=$((test_count + 1))

    echo "Test $test_count: $name"
    echo "  URL: $url"

    response=$(curl -s -w "\n%{http_code}" "$url")
    status_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    echo "  Expected: $expected_status"
    echo "  Got: $status_code"

    if [ "$status_code" == "$expected_status" ]; then
        echo -e "  ${GREEN}✓ PASS${NC}"
        pass_count=$((pass_count + 1))
    else
        echo -e "  ${RED}✗ FAIL${NC}"
        echo "  Response: $body"
        fail_count=$((fail_count + 1))
    fi
    echo ""
}

echo "=== VALID REQUESTS (Should Return 200 OK) ==="
echo ""

run_test \
    "Valid processing_status" \
    "$API_URL/ovens?processing_status=pending" \
    "200"

run_test \
    "Valid limit" \
    "$API_URL/ovens?limit=50" \
    "200"

run_test \
    "Valid offset" \
    "$API_URL/ovens?offset=10" \
    "200"

run_test \
    "Valid alert_status" \
    "$API_URL/alerts?alert_status=firing" \
    "200"

run_test \
    "Valid enabled (true)" \
    "$API_URL/recipes/?enabled=true" \
    "200"

run_test \
    "Valid enabled (false)" \
    "$API_URL/recipes/?enabled=false" \
    "200"

run_test \
    "Multiple valid params" \
    "$API_URL/ovens?processing_status=processing&limit=20&offset=5" \
    "200"

echo "=== INVALID REQUESTS (Should Return 400 Bad Request) ==="
echo ""

run_test \
    "Invalid processing_status" \
    "$API_URL/ovens?processing_status=invalid" \
    "400"

run_test \
    "Invalid processing_status (typo)" \
    "$API_URL/ovens?processing_status=prosessing" \
    "400"

run_test \
    "Invalid limit (too high)" \
    "$API_URL/ovens?limit=999999" \
    "400"

run_test \
    "Invalid limit (zero)" \
    "$API_URL/ovens?limit=0" \
    "400"

run_test \
    "Invalid limit (negative)" \
    "$API_URL/ovens?limit=-1" \
    "400"

run_test \
    "Invalid offset (negative)" \
    "$API_URL/ovens?offset=-1" \
    "400"

run_test \
    "Invalid alert_status" \
    "$API_URL/alerts?alert_status=active" \
    "400"

run_test \
    "Invalid enabled (not boolean)" \
    "$API_URL/recipes/?enabled=yes" \
    "400"

run_test \
    "Invalid alert_id (zero)" \
    "$API_URL/ovens?alert_id=0" \
    "400"

run_test \
    "Invalid alert_id (negative)" \
    "$API_URL/ovens?alert_id=-5" \
    "400"

echo "============================================"
echo "  Test Summary"
echo "============================================"
echo "Total Tests: $test_count"
echo -e "${GREEN}Passed: $pass_count${NC}"
echo -e "${RED}Failed: $fail_count${NC}"
echo ""

if [ $fail_count -eq 0 ]; then
    echo -e "${GREEN}[OK] All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}[ERROR] Some tests failed${NC}"
    exit 1
fi
