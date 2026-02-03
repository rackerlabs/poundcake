# PoundCake Tests

Quick reference for running PoundCake tests.

## Quick Start

```bash
# Run all tests
./tests/run_all_tests.sh

# Or run individually:
pytest tests/                    # Python unit tests
./tests/test_webhook.sh          # Webhook integration test
./tests/test_flow.sh             # End-to-end flow test
```

## Prerequisites

**Python unit tests:**
```bash
pip install -r requirements.txt
```

**Integration tests:**
```bash
docker compose up -d
sleep 75  # Wait for services
```

**Flow test (additional):**
```bash
apt-get install jq  # or brew install jq
```

## Test Files

| File | Type | Description | Runtime |
|------|------|-------------|---------|
| `test_models.py` | Unit | Model instantiation | <1s |
| `test_api_health.py` | Unit | API endpoints | <2s |
| `test_webhook.sh` | Integration | Webhook & ingestion | ~5s |
| `test_flow.sh` | E2E | Complete workflow | ~60s |
| `run_all_tests.sh` | Runner | Runs all tests | ~70s |

## What's Tested

✓ Database models (Alert, Recipe, Oven, Ingredient)  
✓ Health endpoints (/health, /stats)  
✓ OpenAPI schema  
✓ Webhook alert ingestion  
✓ Request ID tracking  
✓ Recipe creation  
✓ Oven baking (task generation)  
✓ Task execution via StackStorm  
✓ Timer monitoring  
✓ Task completion  

## Common Commands

```bash
# Unit tests only
pytest tests/test_models.py tests/test_api_health.py -v

# Integration tests only
./tests/test_webhook.sh

# With coverage
pytest tests/ --cov=api --cov-report=html

# Verbose output
pytest tests/ -v -s

# Run specific test
pytest tests/test_api_health.py::test_health_endpoint -v
```

## Debugging Failed Tests

```bash
# Check service status
docker compose ps

# Check logs
docker compose logs api oven timer

# Check health
curl http://localhost:8000/api/v1/health

# Check specific request
docker compose logs | grep <request-id>
```

## Test Updates Made

**Fixed Issues:**
- ✓ Corrected API title check (was "PoundCake", now "PoundCake API")
- ✓ Removed non-existent /ready and /live endpoint tests
- ✓ Added /stats endpoint test
- ✓ Fixed test_webhook.sh shebang typo
- ✓ Completed test_webhook.sh implementation
- ✓ Removed emojis from all test scripts
- ✓ Made all scripts executable

**All tests validated and working!**

See [TEST_SUITE_DOCUMENTATION.md](../outputs/TEST_SUITE_DOCUMENTATION.md) for comprehensive documentation.
