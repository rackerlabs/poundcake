# Deployment

Auth provider and RBAC setup is documented in [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).
Use that guide for enabling local superuser, Active Directory, and Auth0 together, plus post-deploy access binding.

## Choose Your Install Path

- Same namespace or cluster: install Bakery first, then install PoundCake. The PoundCake installer auto-discovers the co-located Bakery URL and shared DB host.
- Different namespaces or clusters: install Bakery in its own environment, expose it at an HTTPS URL, then install PoundCake with `--remote-bakery-url` and a shared HMAC key. Start with [REMOTE_BAKERY_QUICKSTART.md](REMOTE_BAKERY_QUICKSTART.md).
- Docker Compose: local development only. It is not the primary installer path for deploying Bakery and PoundCake into Kubernetes environments.

## Split-Environment Summary

If Bakery and PoundCake will run in different namespaces or clusters, the installer-driven flow is:

1. Install Bakery first and set `POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY` explicitly.
2. Expose Bakery at a URL the PoundCake environment can reach.
3. Install PoundCake with `--remote-bakery-url` and the same HMAC key.
4. Verify Bakery health, the HMAC secret in each environment, and PoundCake rollout.

The full end-to-end walkthrough is in [REMOTE_BAKERY_QUICKSTART.md](REMOTE_BAKERY_QUICKSTART.md).

## Helm (Kubernetes)

Two install commands are supported:

```bash
./install/install-bakery-helm.sh
./install/install-poundcake-helm.sh
```

Canonical binaries:

```bash
./helm/bin/install-bakery.sh
./helm/bin/install-poundcake.sh
```

Bakery secret behavior:
- The Bakery installer verifies `bakery-rackspace-core` in the target namespace.
- If missing, it prompts for Rackspace Core URL/username/password and creates the secret.
- Existing secret updates require `--update-bakery-secret`.
- Rackspace Core credential values in chart overrides are disabled; use `bakery.rackspaceCore.existingSecret`.
- Bakery-only installs deploy Bakery API, Bakery worker, and Bakery DB init job by default.

Clean Bakery deploy prerequisites:
- Use a pinned Bakery image tag (do not rely on mutable `latest` in production).
- Ensure GHCR image pulls can authenticate.
  - Option A: let installer create pull secret (`POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true`) and provide `HELM_REGISTRY_USERNAME` + `HELM_REGISTRY_PASSWORD`.
  - Option B: reuse an existing pull secret in target namespace with `POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false`, `POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true`, `POUNDCAKE_IMAGE_PULL_SECRET_NAME=<secret>`.

Non-interactive Bakery secret create/update:

```bash
./helm/bin/install-bakery.sh \
  --bakery-rackspace-secret-name bakery-rackspace-core \
  --bakery-rackspace-url https://ws.core.rackspace.com \
  --bakery-rackspace-username poundcake \
  --bakery-rackspace-password '<password>'
```

```bash
./helm/bin/install-bakery.sh \
  --update-bakery-secret \
  --bakery-rackspace-url https://ws.core.rackspace.com \
  --bakery-rackspace-username poundcake \
  --bakery-rackspace-password '<new-password>'
```

Bakery install with image refs pinned in values/override files and an existing pull secret:

```bash
POUNDCAKE_CREATE_IMAGE_PULL_SECRET=false \
POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true \
POUNDCAKE_IMAGE_PULL_SECRET_NAME=ghcr-creds \
./helm/bin/install-bakery.sh
```

Image repositories/tags/digests must be configured in Helm values or override files such as `/etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml`, not installer env vars.

Optional environment defaults for fork/private registry/local chart workflows:

```bash
source /Users/chris.breu/code/poundcake/install/set-env-helper.sh
```

Validation mode:

```bash
./helm/bin/install-poundcake.sh --validate
```

Same-namespace co-location order:

```bash
# 1) Install Bakery first (creates operator-backed MariaDB server for Bakery)
./install/install-bakery-helm.sh

# 2) Install PoundCake second (auto-discovers Bakery URL + shared DB server in that namespace)
./install/install-poundcake-helm.sh
```

Shared DB behavior:
- One MariaDB server can be shared when Bakery and PoundCake are co-located.
- Bakery and PoundCake use separate database/schema ownership and separate user credentials.
- PoundCake shared mode uses `database.mode=shared_operator` with `database.sharedOperator.serverName=<bakery-db-server>`.

External Bakery (not co-located) path:

```bash
./install/install-poundcake-helm.sh \
  --remote-bakery-url https://bakery.example.com \
  --remote-bakery-auth-mode hmac \
  --remote-bakery-hmac-key '<shared-hmac-key>'
```

Recommended approach for different environments:

- Set `POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY` explicitly when installing Bakery.
- Use the same key with `--remote-bakery-hmac-key` when installing PoundCake.
- See [REMOTE_BAKERY_QUICKSTART.md](REMOTE_BAKERY_QUICKSTART.md) for the full end-to-end flow.

Notes:
- `install-poundcake-helm.sh` does not support `--target`.
- `install-bakery-helm.sh` is Bakery-only.
- Co-located install flow is now HMAC-secret aware:
  - `install-bakery-helm.sh` creates/reuses a Bakery HMAC secret and wires `bakery.auth.existingSecret` + `bakery.client.auth.existingSecret`.
  - `install-poundcake-helm.sh` auto-discovers that secret and sets `bakery.client.auth.existingSecret`.
- External remote Bakery can either:
  - provide `--remote-bakery-auth-secret` (or `POUNDCAKE_REMOTE_BAKERY_AUTH_SECRET`) pointing to a pre-created matching secret, or
  - provide `--remote-bakery-hmac-key` (and optional `--remote-bakery-hmac-key-id`) so the PoundCake installer creates the client secret in-cluster.
- Chart versions are sourced from `/etc/genestack/helm-chart-version.yaml` and `/etc/genestack/helm-chart-versions.yaml`.

Bakery Gateway API exposure (optional):

```yaml
bakery:
  gateway:
    enabled: true
    gatewayName: flex-gateway
    gatewayNamespace: envoy-gateway
    listener:
      name: bakery-https
      hostname: bakery.api.ord.cloudmunchers.net
      port: 443
      protocol: HTTPS
      tlsSecretName: bakery-gw-tls-secret
      allowedNamespaces: All
      updateIfExists: true
    hostnames:
      - bakery.api.ord.cloudmunchers.net
```

When enabled, the chart creates/updates:
- Gateway listener (hook job)
- HTTPRoute named `bakery-httproute`
- RBAC for Gateway/HTTPRoute management

Bakery no-send test mode (optional):

```yaml
bakery:
  config:
    ticketingDryRun: true
```

With `ticketingDryRun: true`, Bakery logs and processes requests but does not send outbound calls to external ticketing systems.

Bakery API auth (HMAC) configuration:

For typical installer-driven co-located deployments, this is managed automatically by the install scripts above.
Manual chart value wiring is only needed for custom/non-installer workflows.

```yaml
bakery:
  auth:
    enabled: true
    mode: hmac
    existingSecret: bakery-hmac
    secretKeys:
      activeKeyId: active-key-id
      activeKey: active-key
      nextKeyId: next-key-id
      nextKey: next-key
    hmac:
      timestampSkewSec: 300

  client:
    enabled: true
    baseUrl: "https://bakery.api.ord.cloudmunchers.net"
    auth:
      mode: hmac
      existingSecret: bakery-hmac
      secretKeys:
        keyId: active-key-id
        key: active-key
```

Create/update the HMAC secret:

```bash
kubectl -n <namespace> create secret generic bakery-hmac \
  --from-literal=active-key-id=<key-id> \
  --from-literal=active-key=<shared-secret> \
  --from-literal=next-key-id=<next-key-id> \
  --from-literal=next-key=<next-shared-secret> \
  --dry-run=client -o yaml | kubectl apply -f -
```

Request format expected by protected Bakery endpoints:

- `Authorization: HMAC <key_id>:<hex_signature>`
- `X-Timestamp: <unix_epoch_seconds>`
- `Idempotency-Key: <opaque-key>` (required on mutating endpoints)

Notes:
- `GET /api/v1/health` remains open (no auth required).
- Bakery verifies timestamp freshness using `bakery.auth.hmac.timestampSkewSec`.
- PoundCake uses `bakery.client.*` settings to sign outbound requests to Bakery.

PoundCake suppression behavior (optional, enabled by default):

```yaml
suppressions:
  enabled: true
  lifecycleEnabled: true
  lifecycleIntervalSeconds: 30
  lifecycleBatchLimit: 25
```

The API uses these values to enforce suppression intake/lifecycle behavior, and timer uses `suppressions.lifecycleIntervalSeconds` for lifecycle trigger cadence.

By default, install scripts source chart versions from:
- `/etc/genestack/helm-chart-versions.yaml`

And overrides from:
- `/etc/genestack/helm-configs/global_overrides/*.yaml`
- `/etc/genestack/helm-configs/poundcake/*.yaml`
- `/etc/genestack/helm-configs/stackstorm/*.yaml`

StackStorm default profile (via `/Users/chris.breu/code/poundcake/helm/stackstorm/values-external-services.yaml`):
- Enabled by default (1 pod each unless overridden): `st2api`, `st2auth`, `st2actionrunner`, `st2rulesengine`, `st2workflowengine`, `st2scheduler`, `st2notifier`, and StackStorm-owned `mongodb`, `rabbitmq`, `redis`.
- Disabled by default: `st2stream`, `st2web`, `st2chatops`, `st2garbagecollector`, `st2timersengine`, `st2sensorcontainer`.
- To customize: add override files under `/etc/genestack/helm-configs/stackstorm/*.yaml` to re-enable optional services or increase replicas.

## Docker Compose (Local Development Only)

```bash
docker compose -f docker/docker-compose.yml up -d
```

Common logs:

```bash
docker compose -f docker/docker-compose.yml logs -f api prep-chef chef timer dishwasher
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

## Alertmanager Webhook Auth (Kubernetes)

When auth is enabled, inbound `/api/v1/webhook` requests must send `X-Auth-Token`.

```bash
kubectl get secret poundcake-admin -n <namespace> -o jsonpath='{.data.internal-api-key}' | base64 -d
```

Webhook URL:

```text
http://poundcake.<namespace>.svc.cluster.local:8080/api/v1/webhook
```

## StackStorm API Key

`st2client` generates `config/st2_api_key` on first boot. If the key is invalid, delete the file and restart `st2client`:

```bash
rm -f config/st2_api_key
docker compose -f docker/docker-compose.yml restart st2client
```
