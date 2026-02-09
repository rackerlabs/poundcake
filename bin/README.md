# PoundCake Development Scripts

This directory contains helper scripts for development and deployment.

## Development Scripts

### `testall.sh`
Runs all tests and checks that mirror the GitHub Actions workflow.

**Usage:**
```bash
./bin/testall.sh
```

**What it does:**
1. Checks Python version (requires 3.11+)
2. Creates/activates virtual environment at `.venv`
3. Installs PoundCake with dev dependencies
4. Runs pytest with coverage
5. Runs ruff linting
6. Runs black formatting check
7. Runs mypy type checking

**Requirements:**
- Python 3.11 or higher
- No other dependencies needed (script installs everything)

**Virtual Environment:**
The script creates a `.venv` directory in the project root if it doesn't exist.
This directory is already in `.gitignore` and will not be committed.

## Installation Scripts

### `install-poundcake.sh`
Installs PoundCake using Helm.

### `install-stackstorm.sh`
Installs StackStorm using Helm.

### `install-stackstorm-deps.sh`
Installs StackStorm dependencies.

## Configuration Files

### `stackstorm-external-services-values.yaml`
Helm values for external StackStorm services.
