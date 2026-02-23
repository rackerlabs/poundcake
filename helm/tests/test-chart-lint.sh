#!/bin/bash
set -ex

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Chart test for values schema validation
echo "Testing values schema..."

# Validate values schema
helm show values "${CHART_DIR}" > /dev/null || exit 1

echo "Values schema validation passed!"

# Test chart linting
echo "Testing chart linting..."
helm lint "${CHART_DIR}" || exit 1

echo "Chart linting passed!"

# Test chart template rendering
echo "Testing chart template rendering..."
helm template poundcake "${CHART_DIR}" > /dev/null || exit 1

echo "Chart template rendering passed!"
