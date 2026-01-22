#!/bin/bash
set -e

# PoundCake Local Testing Script
# Runs all the same checks that GitHub Actions runs on push

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/venv"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🧪 Running PoundCake pre-push tests...${NC}"
echo ""

# Check if virtualenv exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}❌ Virtualenv not found at $VENV_DIR${NC}"
    echo "   Run: ./scripts/setup-dev-env.sh"
    exit 1
fi

# Activate virtualenv
source "$VENV_DIR/bin/activate"

# Change to project root
cd "$PROJECT_ROOT"

# Track failures
FAILED=0

# Test 1: Ruff linting
echo -e "${BLUE}[1/4] Running ruff check...${NC}"
if ruff check api tests; then
    echo -e "${GREEN}✓ Ruff check passed${NC}"
else
    echo -e "${RED}✗ Ruff check failed${NC}"
    FAILED=1
fi
echo ""

# Test 2: Black formatting
echo -e "${BLUE}[2/4] Running black format check...${NC}"
if black --check api tests; then
    echo -e "${GREEN}✓ Black formatting passed${NC}"
else
    echo -e "${RED}✗ Black formatting failed${NC}"
    echo -e "${YELLOW}   Tip: Run 'black api tests' to auto-format${NC}"
    FAILED=1
fi
echo ""

# Test 3: MyPy type checking
echo -e "${BLUE}[3/4] Running mypy type check...${NC}"
if mypy api; then
    echo -e "${GREEN}✓ MyPy type checking passed${NC}"
else
    echo -e "${RED}✗ MyPy type checking failed${NC}"
    FAILED=1
fi
echo ""

# Test 4: Pytest
echo -e "${BLUE}[4/4] Running pytest...${NC}"
if pytest tests/ -v --cov=api --cov-report=term-missing; then
    echo -e "${GREEN}✓ Pytest passed${NC}"
else
    echo -e "${RED}✗ Pytest failed${NC}"
    FAILED=1
fi
echo ""

# Summary
echo "================================"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed! Safe to push.${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed. Fix errors before pushing.${NC}"
    exit 1
fi
