# Deployment

PoundCake deploys as a standalone monitoring control plane. Bakery is no longer installed from
this repo; deploy it separately from [rackerlabs/bakery](https://github.com/rackerlabs/bakery) and
point PoundCake at it with `bakery.client.*` values.

Auth provider and RBAC setup live in [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).

## Supported Model

- This repo installs PoundCake API, UI, workers, StackStorm, and supporting infra.
- Remote communications are handled by a separately deployed Bakery instance.
- PoundCake does not share Bakery’s normal HMAC secret anymore.
- Bakery issues a bootstrap credential for the PoundCake monitor ID, and PoundCake stores the
  Bakery-issued per-monitor secret locally after registration.
- Runtime configuration belongs in values files and Kubernetes secrets, not installer flags.

## Canonical Paths

- PoundCake override directory: `/etc/genestack/helm-configs/poundcake/`
- Bakery override directory: `/etc/genestack/helm-configs/bakery/`
- Global overrides: `/etc/genestack/helm-configs/global_overrides/`
- Shared chart version file: `/etc/genestack/helm-chart-versions.yaml`
- PoundCake installer wrapper: [install/install-poundcake-helm.sh](/Users/aedan/Documents/GitHub/poundcake/install/install-poundcake-helm.sh)
- Standalone Bakery repo: [rackerlabs/bakery](https://github.com/rackerlabs/bakery)

Recommended override layout:

- `00-pull-secret-overrides.yaml`
- `10-main-overrides.yaml`
- `20-auth-overrides.yaml`
- `30-git-sync-overrides.yaml`

Before deploying, update the `poundcake` chart entry in `/etc/genestack/helm-chart-versions.yaml`.
If Bakery is being rolled out or upgraded in the same environment, update the `bakery` entry there
as well.

## Minimum PoundCake Override Shape

`10-main-overrides.yaml`

```yaml
gateway:
  enabled: true
  gatewayName: "flex-gateway"
  gatewayNamespace: "envoy-gateway"
  listener:
    name: "poundcake-https"
    hostname: "<poundcake-public-url-host>"
    port: 443
    protocol: "HTTPS"
    tlsSecretName: "poundcake-gw-tls-secret"
    allowedNamespaces: "All"
    updateIfExists: true
  hostnames:
    - "<poundcake-public-url-host>"
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
    baseUrl: "https://<bakery-public-url-host>"
    auth:
      existingSecret: bakery-monitor-bootstrap
```

Optional examples:

- Put `poundcakeImage.pullSecrets` in `00-pull-secret-overrides.yaml` when private GHCR pulls are required.
- Put non-secret Auth0 or Azure values in `20-auth-overrides.yaml`.
- Put non-secret Git sync values in `30-git-sync-overrides.yaml`.

## Bakery Bootstrap Secret

The monitor ID is auto-derived by the chart as `<namespace>/<release>`. Create the PoundCake-side
secret in the PoundCake namespace with the bootstrap credential returned by Bakery plus a local
encryption key for the stored per-monitor secret:

```bash
export POUNDCAKE_BAKERY_BOOTSTRAP_KEY_ID="bootstrap"
export POUNDCAKE_BAKERY_BOOTSTRAP_KEY="<value returned by Bakery admin bootstrap endpoint>"
export POUNDCAKE_BAKERY_MONITOR_ENCRYPTION_KEY="$(openssl rand -base64 32)"

kubectl -n rackspace create secret generic bakery-monitor-bootstrap \
  --from-literal=bootstrap-key-id="${POUNDCAKE_BAKERY_BOOTSTRAP_KEY_ID}" \
  --from-literal=bootstrap-key="${POUNDCAKE_BAKERY_BOOTSTRAP_KEY}" \
  --from-literal=monitor-encryption-key="${POUNDCAKE_BAKERY_MONITOR_ENCRYPTION_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Use the standalone Bakery repo docs for the Bakery-side auth secret, bootstrap endpoint, and remote
publication flow:

- [bakery/docs/DEPLOY.md](https://github.com/rackerlabs/bakery/blob/main/docs/DEPLOY.md)
- [bakery/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](https://github.com/rackerlabs/bakery/blob/main/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md)

## Install PoundCake

Install PoundCake from this repo only:

```bash
./install/install-poundcake-helm.sh
```

## Verify

Wait for the PoundCake rollout:

```bash
kubectl -n rackspace rollout status deploy/poundcake-api --timeout=300s
kubectl -n rackspace rollout status deploy/poundcake-ui --timeout=300s
```

Confirm PoundCake is wired for remote Bakery:

```bash
helm get values poundcake -n rackspace -o yaml
kubectl -n rackspace get secret bakery-monitor-bootstrap
kubectl -n rackspace exec deploy/poundcake-api -- printenv | grep '^POUNDCAKE_BAKERY_'
curl -fsS https://<poundcake-public-url-host>/api/v1/health
```

Things to confirm:

- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl` points at the external Bakery URL
- `bakery.client.auth.existingSecret` matches the bootstrap secret name
- `POUNDCAKE_BAKERY_MONITOR_ID` defaults to `<namespace>/<release>`
- if multiple PoundCake environments share one Bakery instance, set a unique explicit monitor ID per environment
- `POUNDCAKE_BAKERY_ENABLED=true`

Confirm PoundCake persisted monitor state locally:

```bash
kubectl -n rackspace exec deploy/poundcake-mariadb -- \
  mariadb -u"$(kubectl -n rackspace get secret poundcake-secrets -o jsonpath='{.data.DB_USER}' | base64 -d)" \
  -p"$(kubectl -n rackspace get secret poundcake-secrets -o jsonpath='{.data.DB_PASSWORD}' | base64 -d)" \
  "$(kubectl -n rackspace get secret poundcake-secrets -o jsonpath='{.data.DB_NAME}' | base64 -d)" \
  -N -e "SELECT monitor_id, monitor_uuid, last_heartbeat_status, last_heartbeat_at FROM bakery_monitor_state;"
```

## Post-Install Bootstrap

After PoundCake is healthy:

- retrieve the generated PoundCake admin credentials
- sign in to PoundCake
- configure the global communications policy
- point Alertmanager at PoundCake's authenticated webhook endpoint

Example secret reads:

```bash
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.username}' | base64 -d; echo
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.password}' | base64 -d; echo
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.internal-api-key}' | base64 -d; echo
```

## Live Validation

Keep Bakery in dry-run for normal deployments. For live provider validation, temporarily set
`bakery.config.ticketingDryRun: false` on the Bakery side, redeploy Bakery, run the validation,
then return Bakery to dry-run and redeploy it again.

Recommended validation sequence:

1. Send the PVC-expand validation firing webhook through PoundCake’s authenticated webhook endpoint.
2. Wait for firing remediation to finish.
3. Send the matching resolved webhook with the same fingerprint.
4. Confirm the PoundCake order timeline shows successful Bakery operations and capture the external
   provider ticket number.
5. Scale `deploy/poundcake-api` to zero and wait longer than 5 missed 30-second heartbeats.
6. Confirm Bakery marks the PoundCake monitor unreachable and opens the outage ticket.
7. Scale `deploy/poundcake-api` back to one replica and confirm heartbeats resume.

For the remote Bakery side of the split, continue in the standalone Bakery repo docs rather than
this repo.
