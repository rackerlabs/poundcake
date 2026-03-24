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

## Canonical Paths

- Main override file: `/etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml`
- Global overrides: `/etc/genestack/helm-configs/global_overrides/*.yaml`
- PoundCake service overrides: `/etc/genestack/helm-configs/poundcake/*.yaml`
- Chart version file: `/etc/genestack/helm-chart-versions.yaml`

Example override fragments in-repo:

- `helm/overrides/poundcake-only-overrides.yaml`
- `helm/overrides/bakery-only-overrides.yaml`
- `helm/overrides/colocated-shared-db-overrides.yaml`
- `helm/overrides/remote-bakery-overrides.yaml`
- `helm/overrides/ghcr-pull-secret-overrides.yaml`
- `helm/overrides/split-install/`

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

Sanitized starter files live in `helm/overrides/split-install/` and map directly to that layout.

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
  gatewayName: "<gateway-name>"
  gatewayNamespace: "<gateway-namespace>"
  listener:
    name: "<poundcake-gateway-listener-name>"
    hostname: "<poundcake-public-url-host>"
    port: 443
    protocol: "HTTPS"
    tlsSecretName: "<poundcake-gateway-tls-secret-name>"
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
    gatewayName: "<gateway-name>"
    gatewayNamespace: "<gateway-namespace>"
    listener:
      name: "<bakery-gateway-listener-name>"
      hostname: "<bakery-public-url-host>"
      port: 443
      protocol: "HTTPS"
      tlsSecretName: "<bakery-gateway-tls-secret-name>"
    hostnames:
      - "<bakery-public-url-host>"
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
  --bakery-auth-secret-name bakery-hmac \
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<rackspace-core-password>'
```

### 6. Install PoundCake Second

```bash
export POUNDCAKE_NAMESPACE="rackspace"
./install/install-poundcake-helm.sh
```

### 7. Verify The Split Deployment

```bash
helm list -n bakery
helm list -n rackspace
curl -fsS https://<bakery-public-url-host>/api/v1/health
curl -fsS https://<poundcake-public-url-host>/api/v1/health
helm get values poundcake -n rackspace -o yaml
```

Expected PoundCake release values include:

- `poundcakeImage.pullSecrets`
- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl: https://<bakery-public-url-host>`
- `bakery.client.auth.existingSecret: bakery-hmac`

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

1. Start from `helm/overrides/bakery-only-overrides.yaml`.
2. Merge it into your active override file.
3. Install Bakery:

```bash
./install/install-bakery-helm.sh \
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<password>'
```

The installer creates or reuses provider secrets. Default provider secret names already match `helm/values.yaml`, so no extra `--set-string bakery.<provider>.existingSecret=...` wiring is needed unless you intentionally choose a non-default secret name.

### PoundCake Only

1. Start from `helm/overrides/poundcake-only-overrides.yaml`.
2. Merge it into your active override file.
3. Install PoundCake:

```bash
./install/install-poundcake-helm.sh
```

### Co-Located Bakery + PoundCake

1. Install Bakery first.
2. Merge `helm/overrides/colocated-shared-db-overrides.yaml` into the PoundCake override file.
3. Confirm `database.sharedOperator.serverName` matches the Bakery MariaDB server name for your Bakery release.
4. Install PoundCake.

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
4. Merge `helm/overrides/remote-bakery-overrides.yaml` into the PoundCake override file.
5. Set:

```yaml
bakery:
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

Use `helm/overrides/ghcr-pull-secret-overrides.yaml` as the starter fragment.

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
