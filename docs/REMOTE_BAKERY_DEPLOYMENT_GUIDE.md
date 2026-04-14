# Remote Bakery Deployment Guide

This guide covers the PoundCake side of a split deployment. Bakery itself now lives in the
standalone [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.

Use this sequence:

1. deploy Bakery from the standalone Bakery repo
2. publish Bakery at an HTTPS URL
3. create a Bakery bootstrap credential for this PoundCake monitor ID
4. create the PoundCake bootstrap secret with that credential and a local encryption key
5. configure PoundCake with `bakery.client.*` values
6. install and verify PoundCake
7. run live provider and heartbeat validation, then return Bakery to dry-run

## Canonical Operator Paths

- PoundCake repo root: `/opt/poundcake`
- Bakery repo root: `/opt/bakery`
- PoundCake overrides: `/etc/poundcake/helm-configs/poundcake/`
- Bakery overrides: `/etc/bakery/helm-configs/bakery/`
- Shared chart versions file: `/etc/poundcake/helm-chart-versions.yaml`

## Bakery Deployment Source

Deploy Bakery from the standalone repo and follow its install docs for Gateway publication,
provider secrets, Bakery-side HMAC configuration, and monitor bootstrap:

- [bakery/docs/DEPLOY.md](https://github.com/rackerlabs/bakery/blob/main/docs/DEPLOY.md)
- [bakery/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](https://github.com/rackerlabs/bakery/blob/main/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md)

Assume Bakery will be reachable at a URL such as:

```bash
export BAKERY_URL="https://bakery.example.com"
```

## PoundCake Override Example

Put the PoundCake-side remote Bakery settings in the active override file, typically
`/etc/poundcake/helm-configs/poundcake/10-main-overrides.yaml`:

```yaml
gateway:
  enabled: true
  gatewayName: "flex-gateway"
  gatewayNamespace: "envoy-gateway"
  listener:
    name: "poundcake-https"
    hostname: "<poundcake-public-hostname>"
    port: 443
    protocol: "HTTPS"
    tlsSecretName: "poundcake-gw-tls-secret"
    allowedNamespaces: "All"
    updateIfExists: true
  hostnames:
    - "<poundcake-public-hostname>"
  listeners:
    api:
      pathPrefix: /api
    ui:
      pathPrefix: /

bakery:
  config:
    activeProvider: rackspace_core
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: ${BAKERY_URL}
    auth:
      existingSecret: bakery-monitor-bootstrap
```

## Bootstrap Credential

Bakery owns the long-lived monitor identity. PoundCake uses a Bakery-issued bootstrap credential
once, registers itself with a monitor ID, then stores the returned per-monitor secret locally.

If multiple PoundCake environments point at the same Bakery, do not reuse the default
`<namespace>/<release>` identity in every cluster. Set a unique explicit monitor ID and label in
the PoundCake override file for each environment, for example:

```yaml
bakery:
  client:
    monitor:
      id: example/poundcake
      environmentLabel: example
      clusterName: example-cluster
      tags:
        - shared-bakery
        - example
```

Create the PoundCake-side secret after the Bakery admin endpoint returns the bootstrap key:

```bash
export POUNDCAKE_BAKERY_BOOTSTRAP_KEY_ID="bootstrap"
export POUNDCAKE_BAKERY_BOOTSTRAP_KEY="<value returned by Bakery admin bootstrap endpoint>"
export POUNDCAKE_BAKERY_MONITOR_ENCRYPTION_KEY="$(openssl rand -base64 32)"

kubectl -n <namespace> create secret generic bakery-monitor-bootstrap \
  --from-literal=bootstrap-key-id="${POUNDCAKE_BAKERY_BOOTSTRAP_KEY_ID}" \
  --from-literal=bootstrap-key="${POUNDCAKE_BAKERY_BOOTSTRAP_KEY}" \
  --from-literal=monitor-encryption-key="${POUNDCAKE_BAKERY_MONITOR_ENCRYPTION_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Install PoundCake

Update `/etc/poundcake/helm-chart-versions.yaml` so the `poundcake` entry matches the chart you
intend to deploy, then install PoundCake from this repo:

```bash
cd /opt/poundcake
./install/install-poundcake-helm.sh
```

Wait for rollout:

```bash
kubectl -n <namespace> rollout status deploy/poundcake-api --timeout=300s
kubectl -n <namespace> rollout status deploy/poundcake-ui --timeout=300s
```

## Verify Remote Bakery Wiring

Confirm release values:

```bash
helm get values <release-name> -n <namespace> -o yaml
```

Confirm runtime env:

```bash
kubectl -n <namespace> exec deploy/poundcake-api -- printenv | grep '^POUNDCAKE_BAKERY_'
```

Expected shape:

- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl: ${BAKERY_URL}`
- `bakery.client.auth.existingSecret: bakery-monitor-bootstrap`
- `POUNDCAKE_BAKERY_MONITOR_ID: <explicit monitor id or namespace/release default>`
- `POUNDCAKE_BAKERY_ENABLED=true`

Confirm the public PoundCake endpoint:

```bash
curl -fsS https://<poundcake-public-hostname>/api/v1/health
```

Confirm local monitor persistence:

```bash
kubectl -n <namespace> exec deploy/poundcake-mariadb -- \
  mariadb -u"$(kubectl -n <namespace> get secret poundcake-secrets -o jsonpath='{.data.DB_USER}' | base64 -d)" \
  -p"$(kubectl -n <namespace> get secret poundcake-secrets -o jsonpath='{.data.DB_PASSWORD}' | base64 -d)" \
  "$(kubectl -n <namespace> get secret poundcake-secrets -o jsonpath='{.data.DB_NAME}' | base64 -d)" \
  -N -e "SELECT monitor_id, monitor_uuid, last_heartbeat_status, last_heartbeat_at FROM bakery_monitor_state;"
```

If PoundCake still shows `POUNDCAKE_BAKERY_ENABLED=false` or an in-cluster Bakery URL, the release
was not redeployed with the remote Bakery client settings.

## Live Validation

Leave Bakery in dry-run for normal deployments. For live provider validation:

1. set Bakery `ticketingDryRun` to `false`
2. redeploy Bakery
3. run the validation below
4. set Bakery `ticketingDryRun` back to `true`
5. redeploy Bakery

Suggested validation flow:

1. Retrieve the PoundCake service token:

```bash
kubectl get secret poundcake-admin -n <namespace> -o jsonpath='{.data.internal-api-key}' | base64 -d; echo
```

2. Run the PVC-expand validation webhook through PoundCake.
   Note:
   The validation recipe and its target PVC name are runtime data. Confirm the recipe’s execution
   overrides still point at the PVC you intend to use, or create the expected PVC target before
   firing the webhook.
3. Wait for firing remediation to finish, then send the matching resolved webhook with the same
   fingerprint.
4. Verify the PoundCake order timeline shows successful Bakery operations and capture the external
   provider ticket number.
5. Scale the PoundCake API deployment to zero:

```bash
kubectl -n <namespace> scale deploy/poundcake-api --replicas=0
```

6. Wait longer than 5 missed 30-second heartbeats and verify the Bakery outage alert fired.
7. Scale the PoundCake API deployment back to one replica and confirm heartbeats resume:

```bash
kubectl -n <namespace> scale deploy/poundcake-api --replicas=1
kubectl -n <namespace> rollout status deploy/poundcake-api --timeout=300s
```
