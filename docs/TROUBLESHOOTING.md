# Troubleshooting

## API not ready

Check logs:

```bash
docker compose logs -f api
```

## StackStorm API key errors

Delete and regenerate:

```bash
rm -f config/st2_api_key
docker compose restart st2client
```

## Dishes stuck in processing

Check timer logs:

```bash
docker compose logs -f timer
```

Confirm StackStorm execution exists:

```bash
docker compose exec st2client st2 execution get <execution_id>
```

## No dishes created

Check prep-chef logs:

```bash
docker compose logs -f prep-chef
```

## No workflow execution

Check chef logs:

```bash
docker compose logs -f chef
```
