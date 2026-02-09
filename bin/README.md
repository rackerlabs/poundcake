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
1. Installs Git pre-push hook (if not already installed) to run checks automatically before every push
2. Checks Python version (requires 3.11+)
3. Creates/activates virtual environment at `.venv`
4. Installs PoundCake with dev dependencies
5. Runs pytest with coverage
6. Runs ruff linting (checks: api, kitchen, cli, tests, alembic)
7. Runs black formatting check (checks: api, kitchen, cli, tests, alembic)
8. Runs mypy type checking (checks: api, kitchen, cli)

**Requirements:**
- Python 3.11 or higher
- No other dependencies needed (script installs everything)

**Virtual Environment:**
The script creates a `.venv` directory in the project root if it doesn't exist.
This directory is already in `.gitignore` and will not be committed.

**Pre-Push Hook:**
The first time you run `testall.sh`, it automatically installs a Git pre-push hook that will run all checks before every `git push`. This prevents broken code from being pushed to GitHub.

To bypass the pre-push hook in emergencies: `git push --no-verify`

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
