# CLI Notes

The `st2client` container provides StackStorm CLI access:

```bash
docker compose -f docker/docker-compose.yml exec st2client st2 action list
docker compose -f docker/docker-compose.yml exec st2client st2 execution list -n 5
```

Use PoundCake API for workflow registration and execution:

```bash
curl -s http://localhost:8000/api/v1/cook/executions
```
