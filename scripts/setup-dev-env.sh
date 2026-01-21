#!/bin/bash
set -e

# PoundCake Development Environment Setup
# Creates a virtualenv with all dependencies needed for local testing

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/venv"

echo "🔧 Setting up PoundCake development environment..."
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]); then
    echo "❌ Error: Python 3.11 or higher is required (found Python $PYTHON_VERSION)"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION detected"
echo ""

# Remove existing venv if present
if [ -d "$VENV_DIR" ]; then
    echo "⚠️  Existing virtualenv found at $VENV_DIR"
    read -p "   Remove and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "   Removing old virtualenv..."
        rm -rf "$VENV_DIR"
    else
        echo "   Keeping existing virtualenv. Install will update packages."
    fi
fi

# Create virtualenv
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtualenv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtualenv
echo "🔌 Activating virtualenv..."
source "$VENV_DIR/bin/activate"

# Upgrade pip, setuptools, wheel
echo "⬆️  Upgrading pip, setuptools, and wheel..."
pip install --upgrade pip setuptools wheel

# Install project with dev dependencies
echo "📚 Installing PoundCake with dev dependencies..."
cd "$PROJECT_ROOT"
pip install -e ".[dev]"

echo ""
echo "✅ Development environment setup complete!"
echo ""
echo "To activate the environment, run:"
echo "   source venv/bin/activate"
echo ""
echo "To run tests locally before pushing:"
echo "   ./scripts/test-local.sh"
echo ""
