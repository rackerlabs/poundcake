#!/bin/bash
# ____                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
# PoundCake Local Testing Script
#
# This script mirrors the GitHub Actions workflow checks locally.
# It creates a virtual environment if needed and runs all tests,
# linting, formatting, and type checking.
#
# Usage: ./bin/testall.sh

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get to project root
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                PoundCake Local Test Suite                     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to print section headers
print_section() {
    echo ""
    echo -e "${BLUE}▶ $1${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Function to print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print error
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check if Python 3.11+ is available
print_section "Checking Python version"
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    print_error "Python 3.11+ is required (found $PYTHON_VERSION)"
    exit 1
fi

print_success "Python $PYTHON_VERSION detected"

# Check/Create virtual environment
VENV_DIR="$PROJECT_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
    print_section "Creating virtual environment"
    python3 -m venv "$VENV_DIR"
    print_success "Virtual environment created at $VENV_DIR"
else
    print_section "Using existing virtual environment"
    print_success "Found virtual environment at $VENV_DIR"
fi

# Activate virtual environment
print_section "Activating virtual environment"
source "$VENV_DIR/bin/activate"
print_success "Virtual environment activated"

# Upgrade pip
print_section "Upgrading pip"
pip install --quiet --upgrade pip setuptools wheel
print_success "pip upgraded"

# Install dependencies
print_section "Installing dependencies"
echo "Installing PoundCake with dev dependencies..."
pip install --quiet -e ".[dev]"
print_success "Dependencies installed"

# Run tests
print_section "Running tests with pytest"
if pytest tests/ -v --cov=api --cov-report=xml --cov-report=term; then
    print_success "All tests passed"
else
    print_error "Tests failed"
    exit 1
fi

# Run linting with ruff
print_section "Running linting with ruff"
if ruff check api tests; then
    print_success "Ruff linting passed"
else
    print_error "Ruff linting failed"
    exit 1
fi

# Run formatting check with black
print_section "Running formatting check with black"
if black --check api tests; then
    print_success "Black formatting check passed"
else
    print_error "Black formatting check failed"
    print_warning "Run 'black api tests' to fix formatting"
    exit 1
fi

# Run type checking with mypy
print_section "Running type checking with mypy"
if mypy api; then
    print_success "Type checking passed"
else
    print_error "Type checking failed"
    exit 1
fi

# Summary
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  ✓ All checks passed!                         ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Your code is ready to push to GitHub.${NC}"
echo ""
