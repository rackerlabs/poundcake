# Troubleshooting Common Issues

## API Health Is Degraded

`/api/v1/health` returns `degraded` when either MariaDB or StackStorm is unreachable.

```bash
# Check API logs
docker compose logs api -f

# Check MariaDB
docker compose logs mariadb -f

# Check StackStorm API
docker compose logs stackstorm-api -f
```

## Alerts Not Processing

Symptoms:
- Alerts appear but no ovens are created
- `processing_status` stays `new`

Checklist:
- Ensure Prep Chef is running
- Confirm recipes exist and are enabled
- Verify alert `group_name` matches `recipe.name`

```bash
# View prep-chef logs
docker compose logs prep-chef -f

# List new alerts
curl http://localhost:8000/api/v1/alerts?processing_status=new | jq

# List recipes
curl http://localhost:8000/api/v1/recipes | jq
```

Note: `group_name` defaults to `labels.alertname` from the Alertmanager payload.

## Ovens Not Executing

Symptoms:
- Ovens created but stay in `new`

```bash
# View chef logs
docker compose logs chef -f

# List new ovens
curl http://localhost:8000/api/v1/ovens?processing_status=new | jq
```

## StackStorm Execution Failures

Symptoms:
- Ovens move to `failed`
- StackStorm API errors in logs

```bash
# StackStorm API logs
docker compose logs stackstorm-api -f

# RabbitMQ and Redis
docker compose logs stackstorm-rabbitmq -f
docker compose logs stackstorm-redis -f
```

## Database Connection Issues

```bash
# MariaDB logs
docker compose logs mariadb -f

# Confirm DB URL in API container
docker compose exec api env | grep POUNDCAKE_DATABASE_URL
```

## Complete Fresh Start

```bash
# Stop everything
docker compose down

# Remove all volumes (WARNING: deletes all data)
docker compose down -v

# Rebuild and start

docker compose up -d --build

# Check health
curl http://localhost:8000/api/v1/health
```
