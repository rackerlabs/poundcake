# PoundCake - Complete Deployment Guide

## Quick Start

```bash
# 1. Extract
# tar -xzf poundcake-complete.tar.gz
# cd poundcake-complete

# 2. Configure environment
cp .env.example .env
# Edit .env with your settings

# 3. Start everything
docker compose up -d

# 4. Check health
docker compose ps

# 5. (Optional) Run database migrations manually if needed
# docker exec poundcake-api python api/migrate.py upgrade

# 6. Create your first recipe
curl -X POST http://localhost:8000/api/v1/recipes/ \
  -H "Content-Type: application/json" \
  -d @examples/recipe-hostdown.json
```

## Architecture

```
Webhook → API → pre_heat → Creates Ovens (status="new")
                               ↓
Prep Chef → bakes ovens for new alerts
                               ↓
Chef → starts StackStorm executions (respects is_blocking)
                               ↓
Timer → monitors & completes
                               ↓
Alert Status → complete
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| poundcake-api | 8000 | Main API |
| poundcake-prep-chef | - | Dispatcher (alerts → ovens) |
| poundcake-chef | - | Executor (ovens → ST2 actions) |
| poundcake-timer | - | Monitors completions |
| stackstorm-api | 9101 | StackStorm API |
| mariadb | 3306 | Database |
| stackstorm-mongodb | 27017 | StackStorm data |

## Function-Level Logging

All services log with function names:

```bash
# View timer logs
docker logs poundcake-timer | grep "update_oven"

# View chef logs
docker logs poundcake-chef | grep "Cooking action"

# View all logs
docker compose logs -f
```

## Reading Logs

PoundCake logs are structured so you can trace a request end‑to‑end with `req_id`.

```bash
# Grab the req_id from a webhook response
curl -i -X POST http://localhost:8000/api/v1/webhook -H "Content-Type: application/json" -d @payload.json

# Follow that req_id across services
docker compose logs -f api prep-chef chef timer | grep "<REQ_ID>"
```

## Configuration

Edit `.env`:
```bash
MYSQL_PASSWORD=secure_password
ST2_API_KEY=your_st2_api_key
TIMER_INTERVAL=10
OVEN_INTERVAL=5
OVEN_POLL_INTERVAL=5
```

## Monitoring

```bash
# Check health
curl http://localhost:8000/api/v1/health

# View processing ovens
curl http://localhost:8000/api/v1/ovens?processing_status=processing | jq

# View alerts
curl http://localhost:8000/api/v1/alerts?processing_status=processing | jq
```

## Key Features

[OK] Ingredients table with is_blocking logic
[OK] Function-level logging across all services
[OK] Expected vs actual time tracking (SLA)
[OK] Recipe-based automation (alert.group_name matching)
[OK] Complete StackStorm integration

---

Ready for production.
