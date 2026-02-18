# Deployment

## Helm (Kubernetes)

Preferred installer:

```bash
./bin/install-poundcake.sh
```

Wrapper script (equivalent):

```bash
./install/install-helm.sh
```

Bakery-only mode:

```bash
./bin/install-poundcake.sh --mode bakery-only
```

Interactive Bakery Rackspace Core credential setup (works in full or bakery-only mode):

```bash
./bin/install-poundcake.sh --interactive-bakery-creds
```

Non-interactive Bakery Rackspace Core credential setup:

```bash
./bin/install-poundcake.sh \
  --bakery-rackspace-url "https://10.12.223.241" \
  --bakery-rackspace-username "poundcake" \
  --bakery-rackspace-password "<password>"
```

Notes:
- The installer creates/updates secret `bakery-rackspace-core` in the target namespace.
- The secret name can be overridden with `--bakery-rackspace-secret-name`.
- When Bakery credentials are provided, installer sets:
  - `bakery.enabled=true`
  - `bakery.rackspaceCore.existingSecret=<secret-name>`

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

By default, install scripts source chart versions from:
- `/etc/genestack/helm-chart-versions.yaml`

And overrides from:
- `/etc/genestack/helm-configs/global_overrides/*.yaml`
- `/etc/genestack/helm-configs/poundcake/*.yaml`
- `/etc/genestack/helm-configs/stackstorm/*.yaml` (full mode)

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
