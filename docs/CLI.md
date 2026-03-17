# CLI Notes

## PoundCake CLI

Full auth and RBAC setup, including how providers are enabled in Helm before they appear in the CLI, is documented in [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).

Install the CLI from the repo root:

```bash
python3 -m pip install -e .
```

Run the installed application:

```bash
poundcake --help
poundcake --url http://localhost:8000 overview
poundcake --url http://localhost:8000 incidents list
poundcake --url http://localhost:8000 communications list
```

### Authentication

List the enabled auth providers first:

```bash
poundcake --url http://localhost:8000 auth providers
```

If API auth is enabled and you have the service token, pass it explicitly:

```bash
poundcake --url http://localhost:8000 --api-key "$POUNDCAKE_AUTH_SERVICE_TOKEN" incidents list
```

For local or Active Directory logins, store a session locally:

```bash
poundcake --url http://localhost:8000 auth login --provider local --username admin
poundcake --url http://localhost:8000 auth me
poundcake --url http://localhost:8000 overview
poundcake --url http://localhost:8000 auth logout
```

For Auth0, the CLI uses the API-brokered device flow:

```bash
poundcake --url http://localhost:8000 auth login --provider auth0
```

Stored sessions live under `${XDG_CONFIG_HOME:-~/.config}/poundcake/session.json`.
If `--api-key` is provided, it takes precedence over any stored session.

The installer also provides `poundcake-cli` as an equivalent command name.

Admins can inspect observed principals and manage role bindings:

```bash
poundcake --url http://localhost:8000 auth principals list --provider auth0
poundcake --url http://localhost:8000 auth bindings list
poundcake --url http://localhost:8000 auth bindings create \
  --provider auth0 \
  --type group \
  --role operator \
  --group monitoring-operators
```

### Canonical Commands

The CLI now uses UI-aligned nouns as the primary interface:

```bash
poundcake overview
poundcake incidents list
poundcake incidents get 204
poundcake incidents timeline 204
poundcake communications get comm-123
poundcake activity list --phase firing
poundcake suppressions create \
  --name "Database maintenance" \
  --starts-at 2026-03-16T22:00:00+00:00 \
  --ends-at 2026-03-16T23:00:00+00:00 \
  --matcher-key alertname \
  --matcher-value NodeFilesystemAlmostOutOfSpace
poundcake actions list
poundcake workflows list
poundcake global-communications get
poundcake alert-rules list
```

### Workflow And Policy File Input

`workflows` and `global-communications` accept exact API request bodies from JSON or YAML files:

```bash
poundcake workflows create --file ./examples/workflow.yaml
poundcake workflows update 17 --file ./examples/workflow-update.yaml
poundcake global-communications set --file ./examples/global-comms.yaml
```

Inline JSON input is also supported when you only want to supply a few steps or routes:

```bash
poundcake workflows create \
  --name "Filesystem response" \
  --step-json '{"ingredient_id":42,"run_phase":"firing"}' \
  --route-json '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"1781738"}}'

poundcake global-communications set \
  --route-json '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"1781738"}}' \
  --route-json '{"label":"Discord","execution_target":"discord","destination_target":"ops-alerts"}'
```

### Legacy Aliases

The older command names still work as aliases:

```bash
poundcake orders list
poundcake ingredients list
poundcake recipes list
poundcake rules list
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
