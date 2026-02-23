# CLI Notes

## PoundCake CLI

Run the PoundCake CLI from the repo root:

```bash
python3 -m cli.main --help
python3 -m cli.main orders list --url http://localhost:8000
python3 -m cli.main rules list --url http://localhost:8000
```

If API auth is enabled, pass the internal API key:

```bash
python3 -m cli.main --url http://localhost:8000 --api-key "$POUNDCAKE_API_KEY" orders list
```

## StackStorm CLI

The `st2client` container provides StackStorm CLI access:

```bash
docker compose -f docker/docker-compose.yml exec st2client st2 action list
docker compose -f docker/docker-compose.yml exec st2client st2 execution list -n 5
```
