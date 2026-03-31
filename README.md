# PoundCake

PoundCake is the monitoring and remediation control plane. It receives Alertmanager webhooks,
plans remediation work, runs StackStorm-backed workflows, and manages communication state through a
remote Bakery deployment.

## Architecture

- PoundCake API, workers, UI, and StackStorm stay in this repo.
- Bakery now lives in its own repo: [rackerlabs/bakery](https://github.com/rackerlabs/bakery).
- PoundCake talks to Bakery through a monitor registration, route-sync, heartbeat, and per-monitor
  HMAC client contract in `api/services/bakery_client.py`, `api/services/bakery_monitor.py`, and
  `shared/bakery_contract.py`.

## Local Validation

```bash
./.venv/bin/pre-commit run --all-files
./.venv/bin/mypy api kitchen cli
helm lint ./helm
helm unittest ./helm --file 'tests/unittest/*_test.yaml'
./.venv/bin/pytest -m 'not integration' tests/ -v --cov=api --cov-report=xml
```

## Deployment

PoundCake now installs only PoundCake:

```bash
./install/install-poundcake-helm.sh
```

If you need communications, deploy Bakery separately from its standalone repo and point PoundCake at
it with `bakery.client.*` values:

```yaml
bakery:
  config:
    activeProvider: rackspace_core
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-monitor-bootstrap
```

The corresponding Bakery deployment and install flow live in
[rackerlabs/bakery](https://github.com/rackerlabs/bakery).
