# CLI Notes

## PoundCake CLI

Run the PoundCake CLI from the repo root:

```bash
python3 -m cli.main --help
python3 -m cli.main --url http://localhost:8000 overview
python3 -m cli.main --url http://localhost:8000 incidents list
python3 -m cli.main --url http://localhost:8000 communications list
```

### Authentication

If API auth is enabled and you have the internal API key, pass it explicitly:

```bash
python3 -m cli.main --url http://localhost:8000 --api-key "$POUNDCAKE_API_KEY" incidents list
```

You can also store a session locally for username/password operator access:

```bash
python3 -m cli.main --url http://localhost:8000 auth login --username admin
python3 -m cli.main --url http://localhost:8000 overview
python3 -m cli.main --url http://localhost:8000 auth logout
```

Stored sessions live under `${XDG_CONFIG_HOME:-~/.config}/poundcake/session.json`.
If `--api-key` is provided, it takes precedence over any stored session.

### Canonical Commands

The CLI now uses UI-aligned nouns as the primary interface:

```bash
python3 -m cli.main overview
python3 -m cli.main incidents list
python3 -m cli.main incidents get 204
python3 -m cli.main incidents timeline 204
python3 -m cli.main communications get comm-123
python3 -m cli.main activity list --phase firing
python3 -m cli.main suppressions create \
  --name "Database maintenance" \
  --starts-at 2026-03-16T22:00:00+00:00 \
  --ends-at 2026-03-16T23:00:00+00:00 \
  --matcher-key alertname \
  --matcher-value NodeFilesystemAlmostOutOfSpace
python3 -m cli.main actions list
python3 -m cli.main workflows list
python3 -m cli.main global-communications get
python3 -m cli.main alert-rules list
```

### Workflow And Policy File Input

`workflows` and `global-communications` accept exact API request bodies from JSON or YAML files:

```bash
python3 -m cli.main workflows create --file ./examples/workflow.yaml
python3 -m cli.main workflows update 17 --file ./examples/workflow-update.yaml
python3 -m cli.main global-communications set --file ./examples/global-comms.yaml
```

Inline JSON input is also supported when you only want to supply a few steps or routes:

```bash
python3 -m cli.main workflows create \
  --name "Filesystem response" \
  --step-json '{"ingredient_id":42,"run_phase":"firing"}' \
  --route-json '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"1781738"}}'

python3 -m cli.main global-communications set \
  --route-json '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"1781738"}}' \
  --route-json '{"label":"Discord","execution_target":"discord","destination_target":"ops-alerts"}'
```

### Legacy Aliases

The older command names still work as aliases:

```bash
python3 -m cli.main orders list
python3 -m cli.main ingredients list
python3 -m cli.main recipes list
python3 -m cli.main rules list
```

Alias mapping:

- `orders` -> `incidents`
- `ingredients` -> `actions`
- `recipes` -> `workflows`
- `rules` -> `alert-rules`

## StackStorm CLI

The `st2client` container provides StackStorm CLI access:

```bash
docker compose -f docker/docker-compose.yml exec st2client st2 action list
docker compose -f docker/docker-compose.yml exec st2client st2 execution list -n 5
```
