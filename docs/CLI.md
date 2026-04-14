# CLI Install And Quickstart

For the full command and flag inventory, see [REFERENCE.md](REFERENCE.md).

This page keeps the short, practical CLI quickstart.

## Install

The PoundCake CLI ships inside this repo. There is not a separate published CLI package.

Python 3.11+ is required.

### Recommended Operator Install

If the repo is already checked out on a host, install the CLI from that checkout into a dedicated virtual environment.

Example using the common host checkout path:

```bash
python3 -m venv ~/.venvs/poundcake-cli
source ~/.venvs/poundcake-cli/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install /opt/poundcake
```

From the repo root, the equivalent non-editable install is:

```bash
python3 -m pip install .
```

You can also use:

```bash
make install
```

Installed commands:

- `poundcake`
- `poundcake-cli`

Use `poundcake` as the standard command name.

### Developer Install

If you are working on the repo and want CLI changes to apply without reinstalling:

```bash
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e ".[dev]"
```

Or:

```bash
make dev-install
```

### Verify The Install

```bash
poundcake --help
poundcake --url https://poundcake.example.com auth providers
```

If you installed into a dedicated virtual environment and `poundcake` is not on your shell `PATH`, either activate the virtual environment again or invoke the full path directly:

```bash
~/.venvs/poundcake-cli/bin/poundcake --help
```

### Troubleshooting

- If `pip install -e .` fails with a `build_editable` or PEP 660 error, upgrade `pip`, `setuptools`, and `wheel`, or use the non-editable install path `python3 -m pip install .`.
- If the CLI cannot reach PoundCake, pass `--url` explicitly. The default is `http://localhost:8080`, but local Docker Compose examples in this repo use `http://localhost:8000`.

## Global Options

```bash
poundcake --help
```

The most commonly used global flags are:

- `--url` / `POUNDCAKE_URL`
- `--api-key` / `POUNDCAKE_API_KEY`
- `--format json|yaml|table`
- `--verbose`

The CLI defaults to `http://localhost:8080` if `--url` is omitted. For local Docker Compose examples in this repo, use `http://localhost:8000`.

## Common Commands

```bash
poundcake --url http://localhost:8000 overview
poundcake --url http://localhost:8000 incidents list
poundcake --url http://localhost:8000 communications list
poundcake --url http://localhost:8000 alert-rules list
poundcake --url http://localhost:8000 workflows list
poundcake --url http://localhost:8000 actions list
```

## Authentication

Full auth provider enablement and RBAC setup are documented in [AUTH.md](AUTH.md).

List enabled providers:

```bash
poundcake --url http://localhost:8000 auth providers
```

If you have the internal service token or another API key, pass it explicitly:

```bash
poundcake --url http://localhost:8000 --api-key "$POUNDCAKE_AUTH_SERVICE_TOKEN" incidents list
```

Local login:

```bash
poundcake --url http://localhost:8000 auth login --provider local --username admin
poundcake --url http://localhost:8000 auth me
poundcake --url http://localhost:8000 auth logout
```

Browser/device-code providers:

```bash
poundcake --url http://localhost:8000 auth login --provider auth0
poundcake --url http://localhost:8000 auth login --provider azure_ad
```

Stored sessions live under `${XDG_CONFIG_HOME:-~/.config}/poundcake/session.json`.
If `--api-key` is supplied, it takes precedence over any stored session.

## File-Driven Commands

`workflows`, `global-communications`, and `alert-rules apply` all work well with checked-in JSON or YAML:

```bash
poundcake workflows create --file ./examples/workflow.yaml
poundcake workflows update 17 --file ./examples/workflow-update.yaml
poundcake global-communications set --file ./examples/global-comms.yaml
poundcake alert-rules apply ./examples/rule-group.yaml --source-name kube-prometheus-stack
```

Inline JSON is also supported for quick edits:

```bash
poundcake workflows create \
  --name "Filesystem response" \
  --step-json '{"ingredient_id":42,"run_phase":"firing"}' \
  --route-json '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"<rackspace-account-number>"}}'

poundcake global-communications set \
  --route-json '{"label":"Core","execution_target":"rackspace_core","provider_config":{"account_number":"<rackspace-account-number>"}}' \
  --route-json '{"label":"Discord","execution_target":"discord","destination_target":"ops-alerts"}'
```

## Legacy Aliases

The old nouns still work as aliases:

- `orders` -> `incidents`
- `ingredients` -> `actions`
- `recipes` -> `workflows`
- `rules` -> `alert-rules`

## StackStorm CLI

The local dev stack still includes a StackStorm client container:

```bash
docker compose -f docker/docker-compose.yml exec st2client st2 action list
docker compose -f docker/docker-compose.yml exec st2client st2 execution list -n 5
```
