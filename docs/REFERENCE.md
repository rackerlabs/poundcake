# Configuration And Command Reference

This is the PoundCake-side reference for the split deployment model. PoundCake installs only
PoundCake resources; Bakery is deployed separately from
[rackerlabs/bakery](https://github.com/rackerlabs/bakery).

For guided deployment steps, use:

- [DEPLOY.md](/Users/aedan/Documents/GitHub/poundcake/docs/DEPLOY.md)
- [REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](/Users/aedan/Documents/GitHub/poundcake/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md)
- [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md)
- [CLI.md](/Users/aedan/Documents/GitHub/poundcake/docs/CLI.md)

## Install Entry Points

Supported PoundCake entry points:

- [install/install-poundcake-helm.sh](/Users/aedan/Documents/GitHub/poundcake/install/install-poundcake-helm.sh)
- [helm/bin/install-poundcake.sh](/Users/aedan/Documents/GitHub/poundcake/helm/bin/install-poundcake.sh)
- [install/set-env-helper.sh](/Users/aedan/Documents/GitHub/poundcake/install/set-env-helper.sh)

Bakery install entry points were removed from this repo. Deploy Bakery from:

- [rackerlabs/bakery](https://github.com/rackerlabs/bakery)

## Override Precedence

The PoundCake installer builds Helm input in this order:

1. Chart defaults from [helm/values.yaml](/Users/aedan/Documents/GitHub/poundcake/helm/values.yaml)
2. `POUNDCAKE_BASE_OVERRIDES` when the file exists
3. all `*.yaml` files in `POUNDCAKE_GLOBAL_OVERRIDES_DIR`, sorted
4. all `*.yaml` files in `POUNDCAKE_SERVICE_CONFIG_DIR`, sorted
5. any extra Helm args passed through the installer

Practical rules:

- keep runtime config in YAML files, not installer flags
- keep external credentials in Kubernetes secrets
- use `00-*`, `10-*`, `20-*`, `30-*` naming if you need deterministic override order
- remote Bakery is configured only with `bakery.client.*`

## Installer Environment Variables

Release and override discovery:

| Variable | Default | Purpose |
|---|---|---|
| `POUNDCAKE_RELEASE_NAME` | `poundcake` | Helm release name |
| `POUNDCAKE_NAMESPACE` | `rackspace` | Target namespace |
| `POUNDCAKE_HELM_TIMEOUT` | `120m` | Helm timeout |
| `POUNDCAKE_CHART_REPO` | unset | OCI chart source override |
| `POUNDCAKE_CHART_VERSION` | unset | Explicit OCI chart version |
| `POUNDCAKE_VERSION_FILE` | unset | Explicit chart versions file path |
| `POUNDCAKE_BASE_OVERRIDES` | `/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml` | Optional base values file |
| `POUNDCAKE_GLOBAL_OVERRIDES_DIR` | `/etc/genestack/helm-configs/global_overrides` | Global values dir |
| `POUNDCAKE_SERVICE_CONFIG_DIR` | `/etc/genestack/helm-configs/poundcake` | PoundCake values dir |

Installer behavior:

| Variable | Default | Purpose |
|---|---|---|
| `POUNDCAKE_INSTALL_DEBUG` | `false` | Same as `--debug` |
| `POUNDCAKE_HELM_VALIDATE` | `false` | Same as `--validate` |
| `POUNDCAKE_OPERATORS_MODE` | `install-missing` | Operator handling mode |
| `POUNDCAKE_HELM_WAIT` | `false` | Adds `--wait` when explicitly enabled |
| `POUNDCAKE_ALLOW_HOOK_WAIT` | `false` | Required if you intentionally force `--wait` or `--atomic` |
| `POUNDCAKE_HELM_ATOMIC` | `false` | Adds `--atomic` when explicitly enabled |
| `POUNDCAKE_HELM_CLEANUP_ON_FAIL` | `false` | Adds `--cleanup-on-fail` when explicitly enabled |

Registry and pull-secret handling:

| Variable | Default | Purpose |
|---|---|---|
| `HELM_REGISTRY_USERNAME` | unset | OCI login username and pull-secret username |
| `HELM_REGISTRY_PASSWORD` | unset | OCI login token/password |
| `POUNDCAKE_IMAGE_PULL_SECRET_NAME` | `ghcr-creds` | Pull-secret name |
| `POUNDCAKE_CREATE_IMAGE_PULL_SECRET` | `true` | Create/update the Docker registry secret |
| `POUNDCAKE_IMAGE_PULL_SECRET_EMAIL` | `noreply@local` | Email field for generated docker-registry secret |

Important installer guardrails:

- image repositories, tags, and digests must come from values files
- remote Bakery settings must come from values files
- old Bakery-local installer flags are rejected
- `--wait` and `--atomic` remain guarded because startup hooks can deadlock

## Remote Bakery Values

PoundCake keeps only the client-side Bakery settings:

```yaml
bakery:
  config:
    activeProvider: rackspace_core
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-hmac
```

Relevant keys:

| Key | Purpose |
|---|---|
| `bakery.config.activeProvider` | Active remote provider identity exposed to PoundCake |
| `bakery.client.enabled` | Enables PoundCake's remote Bakery client |
| `bakery.client.enforceRemoteBaseUrl` | Forces explicit remote URL usage |
| `bakery.client.baseUrl` | External Bakery base URL |
| `bakery.client.auth.mode` | Remote auth mode, typically HMAC |
| `bakery.client.auth.existingSecret` | Secret containing HMAC material |
| `bakery.client.requestTimeoutSeconds` | Request timeout |
| `bakery.client.maxRetries` | Retry count |
| `bakery.client.pollIntervalSeconds` | Poll interval for async Bakery operations |
| `bakery.client.pollTimeoutSeconds` | Poll timeout for async Bakery operations |

Bakery server-side values such as `bakery.gateway.*`, `bakery.database.*`, and provider secret
settings now belong in the standalone Bakery repo.

## CLI

The PoundCake CLI ships from this repo. For install details and examples, use
[CLI.md](/Users/aedan/Documents/GitHub/poundcake/docs/CLI.md).

Quick references:

- default URL: `http://localhost:8080`
- common env vars: `POUNDCAKE_URL`, `POUNDCAKE_API_KEY`
- standard command: `poundcake`

Examples:

```bash
poundcake --url https://poundcake.example.com auth providers
poundcake --url https://poundcake.example.com incidents list
poundcake --url https://poundcake.example.com communications list
```
