# PoundCake - Complete Deployment Guide

## Quick Start

```bash
# 1. Extract
tar -xzf poundcake-complete.tar.gz
cd poundcake-complete

# 2. Configure environment
cp .env.example .env
# Edit .env with your settings

# 3. Start everything
docker compose up -d

# 4. Check health
docker compose ps

# 5. Run database migrations
docker exec poundcake-api alembic upgrade head

# 6. Create your first recipe
curl -X POST http://localhost:8000/api/recipes/ \
  -H "Content-Type: application/json" \
  -d @examples/recipe-hostdown.json
```

## Architecture

```
Webhook → API → Pre-heat → Creates Ovens (status="new")
                               ↓
Oven Service → Starts ST2 Executions (respects is_blocking)
                               ↓
Timer Service → Monitors & Completes
                               ↓
Alert Status → Complete
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| poundcake-api | 8000 | Main API |
| poundcake-oven | - | Starts ST2 executions |
| poundcake-timer | - | Monitors completions |
| stackstorm-api | 9101 | StackStorm API |
| mariadb | 3306 | Database |
| mongodb | 27017 | StackStorm data |

## Function-Level Logging

All services log with function names:

```bash
# View timer logs
docker logs poundcake-timer | grep "update_oven_completion"

# View oven logs
docker logs poundcake-oven | grep "can_start_oven"

# View all logs
docker compose logs -f
```

## Configuration

Edit `.env`:
```bash
MYSQL_PASSWORD=secure_password
ST2_API_KEY=your_st2_api_key
TIMER_INTERVAL=10
OVEN_INTERVAL=5
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

✅ Ingredients table with is_blocking logic
✅ Function-level logging across all services
✅ Expected vs actual time tracking (SLA)
✅ Recipe-based automation (alert.group_name matching)
✅ Complete StackStorm integration

---

**Ready for Production!** 🎂
