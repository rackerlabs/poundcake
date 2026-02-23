# Deployment

## Helm (Kubernetes)

Canonical installer:

```bash
./helm/bin/install-poundcake-with-env.sh
```

Install helper wrapper:

```bash
./install/install-poundcake-helm.sh
```

Optional environment defaults for fork/private registry/local chart workflows:

```bash
source /Users/chris.breu/code/poundcake/install/set-env-helper.sh
```

Install modes:

```bash
./helm/bin/install-poundcake-with-env.sh --mode full
./helm/bin/install-poundcake-with-env.sh --mode bakery-only
```

Validation mode:

```bash
./helm/bin/install-poundcake-with-env.sh --validate
```

Bakery image override (optional):

```bash
export POUNDCAKE_BAKERY_IMAGE_REPO="ghcr.io/<owner>/poundcake-bakery"
export POUNDCAKE_BAKERY_IMAGE_TAG="<tag>"
./helm/bin/install-poundcake-with-env.sh --mode bakery-only
```

Notes:
- `install-poundcake-with-env.sh` is the canonical implementation.
- `--mode bakery-only` sets `deployment.mode=bakery-only` and `bakery.enabled=true`.
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
- `/etc/genestack/helm-configs/stackstorm/*.yaml` (full mode)

StackStorm default profile (via `/Users/chris.breu/code/poundcake/helm/stackstorm/values-external-services.yaml`):
- Enabled by default (1 pod each unless overridden): `st2api`, `st2auth`, `st2actionrunner`, `st2rulesengine`, `st2workflowengine`, `st2scheduler`, `st2notifier`, and StackStorm-owned `mongodb`, `rabbitmq`, `redis`.
- Disabled by default: `st2stream`, `st2web`, `st2chatops`, `st2garbagecollector`, `st2timersengine`, `st2sensorcontainer`.
- To customize: add override files under `/etc/genestack/helm-configs/stackstorm/*.yaml` to re-enable optional services or increase replicas.

## Docker Compose (Local)

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

When auth is enabled, inbound `/api/v1/webhook` requests must send `X-Internal-API-Key`.

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
