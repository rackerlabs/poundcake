# Deployment

## Docker Compose (Local)

```bash
docker compose up -d
```

Common logs:

```bash
docker compose logs -f api prep-chef chef timer dishwasher
```

## Service Ports

| Service | Port | Notes |
|---|---|---|
| poundcake-api | 8000 | API + /docs (debug only) |
| stackstorm-api | 9101 | StackStorm API |
| rabbitmq | 5672 | StackStorm broker |
| mongodb | 27017 | StackStorm data |
| redis | 6379 | StackStorm coordination |

## Health

```bash
curl http://localhost:8000/api/v1/health
```

## StackStorm API Key

`st2client` generates `config/st2_api_key` on first boot. If the key is invalid, delete the file and restart `st2client`:

```bash
rm -f config/st2_api_key
docker compose restart st2client
```
