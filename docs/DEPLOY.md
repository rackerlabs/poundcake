# Deployment

Auth provider and RBAC setup is documented in [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).

## Install Contract

PoundCake now follows a values-first install model:

- Put non-secret runtime config in `values.yaml` or override files.
- Put external credentials in Kubernetes secrets.
- Point chart values at those secrets with `existingSecret`.
- Use the installers for operational behavior and optional secret creation only.

The installers read chart versions from `/etc/genestack/helm-chart-versions.yaml` by default.
If you update the chart, update that file before deploying.

## Assumptions

These deployment notes assume a Genestack environment:

- chart versions are sourced from `/etc/genestack/helm-chart-versions.yaml`
- active overrides live under `/etc/genestack/helm-configs/`
- PoundCake-specific overrides live under `/etc/genestack/helm-configs/poundcake/`
- global overrides live under `/etc/genestack/helm-configs/global_overrides/`
- Gateway API already has a parent Gateway named `flex-gateway` in namespace `envoy-gateway`

The examples below keep hostnames, TLS secret names, and external URLs sanitized, but they assume that Genestack layout and that pre-existing Gateway object.

## Canonical Paths

- Active override directory: `/etc/genestack/helm-configs/poundcake/`
- Split files used in the documented rebuild:
  - `/etc/genestack/helm-configs/poundcake/00-pull-secret-overrides.yaml`
  - `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`
  - `/etc/genestack/helm-configs/poundcake/20-auth-overrides.yaml`
  - `/etc/genestack/helm-configs/poundcake/30-git-sync-overrides.yaml`
- Global overrides: `/etc/genestack/helm-configs/global_overrides/*.yaml`
- Chart version file: `/etc/genestack/helm-chart-versions.yaml`

## Clean Split Install From Scratch

This is the documented fresh-install path for a split deployment with:

- Bakery in namespace `bakery`
- PoundCake in namespace `rackspace`
- a dedicated Bakery MariaDB server owned by the Bakery release
- a separate PoundCake embedded/operator-managed MariaDB server

### 1. Update The Chart Version File

The installer reads chart versions from `/etc/genestack/helm-chart-versions.yaml`.
When the chart changes, update `charts.poundcake` before you install.

Example:

```yaml
charts:
  poundcake: <chart-version>
```

Do not keep a second top-level `poundcake:` key in that file.

### 2. Rebuild The Override Directory With Clean Split Files

Recommended live file layout under `/etc/genestack/helm-configs/poundcake/`:

- `00-pull-secret-overrides.yaml`
- `10-main-overrides.yaml`
- `20-auth-overrides.yaml`
- `30-git-sync-overrides.yaml`

These are the files that actually drive the install. The documented operator flow edits `/etc/genestack/helm-configs/poundcake/` directly.

### 3. Core Install Files

`00-pull-secret-overrides.yaml`

```yaml
poundcakeImage:
  pullSecrets:
    - ghcr-creds
```

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
  hostnames:
    - "<poundcake-public-url-host>"
  listeners:
    api:
      pathPrefix: /api
    ui:
      pathPrefix: /

bakery:
  gateway:
    enabled: true
    gatewayName: "flex-gateway"
    gatewayNamespace: "envoy-gateway"
    listener:
      name: "bakery-https"
      hostname: "<bakery-public-url-host>"
      port: 443
      protocol: "HTTPS"
      tlsSecretName: "bakery-gw-tls-secret"
    hostnames:
      - "<bakery-public-url-host>"
  auth:
    existingSecret: bakery-hmac
  config:
    activeProvider: rackspace_core
    ticketingDryRun: true
  rackspaceCore:
    existingSecret: bakery-rackspace-core
    verifySsl: false
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: "https://<bakery-public-url-host>"
    auth:
      existingSecret: bakery-hmac
```

`20-auth-overrides.yaml` is optional and holds non-secret Auth0/Azure values.
`30-git-sync-overrides.yaml` is optional and holds non-secret Git sync values.

The `bakery.gateway.*` block is required for a fresh split install. It is what tells the Bakery release which Gateway to attach to, which listener section to use or create, which hostname to publish, and which TLS secret should terminate the external Bakery endpoint.

In the Genestack case documented here, the parent Gateway is assumed to be:

- name: `flex-gateway`
- namespace: `envoy-gateway`
- listener naming convention: `<service>-https`
- TLS secret naming convention: `<service>-gw-tls-secret`
- examples used here: `poundcake-https` and `bakery-https`

### 4. Create The Required Secrets

Required split-install secrets:

- `ghcr-creds` in `bakery`
- `ghcr-creds` in `rackspace`
- `bakery-rackspace-core` in `bakery`
- `bakery-hmac` in `bakery`
- `bakery-hmac` in `rackspace`

Optional parity-layer secrets:

- `poundcake-auth0-ui` in `rackspace`
- `poundcake-azure-ui` in `rackspace`
- `poundcake-git` in `rackspace`

Create the shared HMAC secret in both namespaces with the same key material:

```bash
export SHARED_BAKERY_HMAC_KEY="$(openssl rand -base64 32)"

kubectl -n bakery create secret generic bakery-hmac \
  --from-literal=active-key-id=active \
  --from-literal=active-key="${SHARED_BAKERY_HMAC_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n rackspace create secret generic bakery-hmac \
  --from-literal=active-key-id=active \
  --from-literal=active-key="${SHARED_BAKERY_HMAC_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

The Bakery installer can create the Bakery-side auth secret in its own namespace, but in a split install the two namespaces must share the exact same key material. Creating `bakery-hmac` manually in both namespaces avoids mismatched keys.

Example provider secret creation:

```bash
kubectl -n bakery create secret generic bakery-rackspace-core \
  --from-literal=rackspace-core-url='<rackspace-core-url>' \
  --from-literal=rackspace-core-username='<rackspace-core-username>' \
  --from-literal=rackspace-core-password='<rackspace-core-password>'
```

### 5. Install Bakery First

```bash
export POUNDCAKE_NAMESPACE="bakery"
./install/install-bakery-helm.sh \
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<rackspace-core-password>'
```

If `bakery-rackspace-core` does not already exist, `./install/install-bakery-helm.sh` will prompt for the Rackspace Core URL, username, and password when run interactively. For non-interactive runs, pass the `--bakery-rackspace-*` flags explicitly.

### 6. Verify Bakery Is Published Through Gateway API

The previous override steps already provide the Bakery Gateway settings. During the Bakery install, the chart should publish Bakery at the configured external URL.

This step verifies that the Gateway listener, HTTPRoute attachment, and external HTTPS endpoint are all working before installing PoundCake.

Checks to run:

```bash
kubectl -n envoy-gateway get gateway flex-gateway
kubectl -n bakery get httproute
kubectl -n bakery get httproute <bakery-httproute-name> -o yaml
curl -fsS https://<bakery-public-url-host>/api/v1/health
```

What to confirm:

- the target Gateway exists as `flex-gateway` in namespace `envoy-gateway`
- the Bakery listener name/hostname/TLS values match the override file
- the Bakery `HTTPRoute` has an accepted parent in `.status.parents[*].conditions`
- the external HTTPS health check works before PoundCake is installed

If the Bakery `HTTPRoute` is not accepted, stop there and fix Gateway/listener/TLS issues first. PoundCake remote mode only works once the published Bakery URL is live.

### 7. Install PoundCake Second

```bash
./install/install-poundcake-helm.sh
```

### 8. Verify The Split Deployment

```bash
helm list -n bakery
helm list -n rackspace
curl -fsS https://<bakery-public-url-host>/api/v1/health
curl -fsS https://<poundcake-public-url-host>/api/v1/health
helm get values poundcake -n rackspace -o yaml
```

Expected PoundCake release values include:

- `poundcakeImage.pullSecrets`
- `gateway.enabled: true`
- `gateway.listener.name: poundcake-https`
- `gateway.listener.tlsSecretName: poundcake-gw-tls-secret`
- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl: https://<bakery-public-url-host>`
- `bakery.client.auth.existingSecret: bakery-hmac`

### 9. Connect Supporting Components And Complete Bootstrap

After the Helm releases are healthy, complete the application bootstrap and surrounding integrations so the environment is fully functional:

- retrieve the generated PoundCake admin credentials
- sign in to PoundCake
- configure the global communications policy so fallback and shared communications can route to Rackspace Core
- point Alertmanager at PoundCake and authenticate the webhook calls with the PoundCake internal API key

Get the default local admin credentials and service token from the generated secret:

```bash
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.username}' | base64 -d; echo
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.password}' | base64 -d; echo
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.internal-api-key}' | base64 -d; echo
```

You can set the global communications policy in either the UI or the CLI.

UI path:

1. Open `https://<poundcake-public-url-host>/login`.
2. Sign in with the generated local admin credentials.
3. Go to `Configuration -> Global Communications`.
4. Add and save a Rackspace Core route with:

```yaml
label: "Rackspace Core"
execution_target: "rackspace_core"
provider_config:
  account_number: "<rackspace-account-number>"
```

CLI path:

```bash
poundcake --url https://<poundcake-public-url-host> auth login --provider local --username admin

poundcake --url https://<poundcake-public-url-host> global-communications set \
  --route-json '{"label":"Rackspace Core","execution_target":"rackspace_core","provider_config":{"account_number":"<rackspace-account-number>"}}'
```

The `auth login` command will prompt for the password you retrieved from `poundcake-admin`.

Alertmanager integration is configured in the Prometheus environment, not in the PoundCake UI or CLI. Alertmanager must post alerts to PoundCake and authenticate the webhook call with the `internal-api-key`.

The in-cluster webhook URL for the default `poundcake` release is:

```text
http://poundcake-api.rackspace.svc.cluster.local:8000/api/v1/webhook
```

Prometheus Operator `AlertmanagerConfig` example:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: poundcake
  namespace: <prometheus-namespace>
spec:
  route:
    receiver: poundcake
    groupBy:
      - alertname
      - group_name
  receivers:
    - name: poundcake
      webhookConfigs:
        - url: http://poundcake-api.rackspace.svc.cluster.local:8000/api/v1/webhook
          sendResolved: true
          httpConfig:
            authorization:
              type: Bearer
              credentials:
                name: poundcake-admin
                key: internal-api-key
```

PoundCake accepts either `Authorization: Bearer <internal-api-key>` or `X-Auth-Token: <internal-api-key>` for internal service calls. The Prometheus Operator path above matches the working integration used on `ord-deployer`.

### 10. Run A Temporary Live Validation Window

This step is optional, but it is the cleanest way to prove the full path with real alerts, remediation, and ticket close behavior.

1. Create a temporary override file such as `/etc/genestack/helm-configs/poundcake/90-live-core-validation-overrides.yaml`:

```yaml
bakery:
  config:
    ticketingDryRun: false
```

2. Reinstall the Bakery release so the worker picks up the live setting:

```bash
export POUNDCAKE_NAMESPACE="bakery"
./install/install-bakery-helm.sh \
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<rackspace-core-password>'
```

3. Verify the worker is live:

```bash
kubectl -n bakery exec deploy/bakery-poundcake-bakery-worker -- env | grep '^TICKETING_DRY_RUN='
```

Expected:

```text
TICKETING_DRY_RUN=false
```

4. Create a disposable validation flow:

- a temporary recipe whose name matches the alert `group_name`
- two `core.local` remediation steps that inspect the PVC and patch it from `1Gi` to `2Gi`
- a temporary `PrometheusRule` that fires when the PVC exceeds 90%
- a temporary `AlertmanagerConfig` route with short `groupWait` and `groupInterval` values that posts to `/api/v1/webhook`

Sanitized receiver example:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: <temp-route-name>
  namespace: <poundcake-namespace>
  labels:
    release: kube-prometheus-stack
spec:
  route:
    receiver: poundcake-webhook-only
    groupBy:
      - alertname
      - group_name
    groupWait: 5s
    groupInterval: 5s
    repeatInterval: 1m
    matchers:
      - name: group_name
        value: <temp-group-name>
        matchType: '='
  receivers:
    - name: poundcake-webhook-only
      webhookConfigs:
        - url: http://poundcake-api.<poundcake-namespace>.svc.cluster.local:8000/api/v1/webhook
          sendResolved: true
          maxAlerts: 0
          httpConfig:
            authorization:
              type: Bearer
              credentials:
                name: poundcake-admin
                key: internal-api-key
```

5. Verify the full end-to-end behavior:

- the order is created from the Prometheus alert
- the remediation dish succeeds
- the PVC request and capacity both reach `2Gi`
- the Prometheus ratio drops below threshold and the alert resolves
- the Rackspace Core communication route ends `succeeded`
- the final remote state is `confirmed_solved`

Useful checks:

```bash
curl -fsS -b <admin-cookie-file> https://<poundcake-public-url-host>/api/v1/orders/<order-id>
curl -fsS -b <admin-cookie-file> https://<poundcake-public-url-host>/api/v1/orders/<order-id>/timeline
kubectl -n <poundcake-namespace> get pvc <temp-pvc-name> -o json
```

6. Close the validation window immediately afterward:

- delete the temporary recipe, PVC, writer pod, `PrometheusRule`, and `AlertmanagerConfig`
- remove `90-live-core-validation-overrides.yaml`
- reinstall Bakery to restore `ticketingDryRun: true`

Verification after restore:

```bash
kubectl -n bakery exec deploy/bakery-poundcake-bakery-worker -- env | grep '^TICKETING_DRY_RUN='
```

## Supported Installers

```bash
./install/install-bakery-helm.sh
./install/install-poundcake-helm.sh
```

Canonical binaries:

```bash
./helm/bin/install-bakery.sh
./helm/bin/install-poundcake.sh
```

Installer responsibilities:

- `install-bakery-helm.sh` installs Bakery only.
- `install-poundcake-helm.sh` installs PoundCake only.
- `install-bakery-helm.sh` can verify/create provider secrets and Bakery HMAC secrets.
- `install-poundcake-helm.sh` can verify cluster prerequisites and optionally create a docker-registry pull secret object.

Installer non-responsibilities:

- It does not auto-discover remote Bakery config.
- It does not auto-discover shared DB config.
- It does not inject `stackstormPackSync.endpoint`.
- It does not inject `poundcakeImage.pullSecrets`.

Those settings belong in values or override files.

## Secret Inventory

Typical external/operator-managed secrets:

- `bakery-rackspace-core`
- `bakery-servicenow`
- `bakery-jira`
- `bakery-github`
- `bakery-pagerduty`
- `bakery-teams`
- `bakery-discord`
- `bakery-hmac` or another Bakery HMAC secret name you choose
- `ghcr-creds` for private GHCR pulls
- `poundcake-git` for Git sync

Typical chart-managed/internal secrets remain chart-owned unless explicitly overridden:

- PoundCake admin/bootstrap secrets
- MariaDB user/root passwords
- StackStorm bootstrap/internal auth secrets

## Common Flows

### Bakery Only

1. Create or update the active Genestack override files under `/etc/genestack/helm-configs/poundcake/`.
2. Put the Bakery runtime settings in `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`.
3. Put pull-secret references, if needed, in `/etc/genestack/helm-configs/poundcake/00-pull-secret-overrides.yaml`.
4. Install Bakery:

```bash
./install/install-bakery-helm.sh \
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<password>'
```

The installer creates or reuses provider secrets. Default provider secret names already match `helm/values.yaml`, so no extra `--set-string bakery.<provider>.existingSecret=...` wiring is needed unless you intentionally choose a non-default secret name.
If the Rackspace Core secret is missing and you do not pass those flags, the installer prompts for them in an interactive shell.

### PoundCake Only

1. Create or update the active Genestack override files under `/etc/genestack/helm-configs/poundcake/`.
2. Put the PoundCake runtime settings in `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`.
3. Put pull-secret references, if needed, in `/etc/genestack/helm-configs/poundcake/00-pull-secret-overrides.yaml`.
4. Install PoundCake:

```bash
./install/install-poundcake-helm.sh
```

### Co-Located Bakery + PoundCake

1. Install Bakery first.
2. Update `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml` for the PoundCake release.
3. Set the shared DB block in that active override file.
4. Confirm `database.sharedOperator.serverName` matches the Bakery MariaDB server name for your Bakery release.
5. Install PoundCake.

This is how you express shared MariaDB mode now:

```yaml
database:
  mode: shared_operator
  sharedOperator:
    serverName: bakery-poundcake-bakery-mariadb
    provisionResources: true
```

### Remote Bakery

1. Install Bakery in its own environment.
2. Publish Bakery at an HTTPS URL.
3. Create the same HMAC secret in both environments.
4. Update the active PoundCake override file at `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`.
5. Set:

```yaml
bakery:
  auth:
    existingSecret: bakery-hmac
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-hmac
```

6. Install PoundCake.

The full opinionated walkthrough is in [REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](/Users/aedan/Documents/GitHub/poundcake/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md).

## Private GHCR Pulls

If images are private, the pull-secret reference must live in values:

```yaml
poundcakeImage:
  pullSecrets:
    - ghcr-creds
```

Put this in `/etc/genestack/helm-configs/poundcake/00-pull-secret-overrides.yaml`.

If you want the installer to create or update that secret object:

```bash
source ./install/set-env-helper.sh
export HELM_REGISTRY_USERNAME="<gh-username>"
export HELM_REGISTRY_PASSWORD="<github_pat_with_read_packages>"
./install/install-poundcake-helm.sh
```

Relevant installer env vars:

- `POUNDCAKE_IMAGE_PULL_SECRET_NAME`
- `POUNDCAKE_CREATE_IMAGE_PULL_SECRET`
- `POUNDCAKE_IMAGE_PULL_SECRET_EMAIL`

The installer does not inject pull-secret references into pod specs anymore.

## Verification

Basic rollout checks:

```bash
kubectl -n <namespace> get pods
helm list -n <namespace>
curl -fsS http://<service-or-route>/api/v1/health
```

Confirm the rendered release picked up the expected settings:

```bash
helm get values <release> -n <namespace> -o yaml
```

Useful things to verify:

- `bakery.client.enabled`
- `bakery.client.baseUrl`
- `database.mode`
- `database.sharedOperator.serverName`
- `poundcakeImage.pullSecrets`
- `bakery.<provider>.existingSecret`
- `git.existingSecret`

## Bakery HMAC Notes

Protected Bakery endpoints expect:

- `Authorization: HMAC <key_id>:<hex_signature>`
- `X-Timestamp: <unix_epoch_seconds>`
- `Idempotency-Key: <opaque-key>` on mutating calls

`GET /api/v1/health` remains open.

## Migration Policy

Fresh-install alpha rule:

- PoundCake API has one baseline Alembic revision.
- Bakery has one baseline Alembic revision.
- Do not create chained revisions.
- Fold schema changes into the baseline migration files instead.
