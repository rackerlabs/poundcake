# Deployment

PoundCake deploys as a standalone monitoring control plane. Bakery is no longer installed from
this repo; deploy it separately from [rackerlabs/bakery](https://github.com/rackerlabs/bakery) and
point PoundCake at it with `bakery.client.*` values.

Auth provider and RBAC setup live in [AUTH.md](AUTH.md).

## Supported Model

- This repo installs PoundCake API, UI, workers, StackStorm, and supporting infra.
- Remote communications are handled by a separately deployed Bakery instance.
- PoundCake does not share Bakery’s normal HMAC secret anymore.
- Bakery issues a bootstrap credential for the PoundCake monitor ID, and PoundCake stores the
  Bakery-issued per-monitor secret locally after registration.
- Runtime configuration belongs in values files and Kubernetes secrets, not installer flags.

## Canonical Paths

- PoundCake override directory: `/etc/poundcake/helm-configs/poundcake/`
- Bakery override directory: `/etc/bakery/helm-configs/bakery/`
- Global overrides: `/etc/poundcake/helm-configs/global_overrides/`
- Shared chart version file: `/etc/poundcake/helm-chart-versions.yaml`
- PoundCake installer wrapper: [install/install-poundcake-helm.sh](../install/install-poundcake-helm.sh)
- Standalone Bakery repo: [rackerlabs/bakery](https://github.com/rackerlabs/bakery)

Recommended override layout:

- `00-pull-secret-overrides.yaml`
- `10-main-overrides.yaml`
- `20-auth-overrides.yaml`
- `30-git-sync-overrides.yaml`

Before deploying, update the `poundcake` chart entry in `/etc/poundcake/helm-chart-versions.yaml`.
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

## Optional StackStorm Packs

If you want PoundCake's StackStorm deployment to install the `kubernetes` and `openstack` packs
during bootstrap, add the pack settings directly to `10-main-overrides.yaml`.

Example `10-main-overrides.yaml` addition:

```yaml
stackstorm:
  bootstrap:
    packs:
      kubernetes:
        enabled: true
        version: ""
        config:
          kubeconfig: |
            apiVersion: v1
            kind: Config
            current-context: admin@target-cluster
            clusters:
              - name: target-cluster
                cluster:
                  server: https://kubernetes.example.com:6443
                  certificate-authority-data: <base64-cluster-ca>
            contexts:
              - name: admin@target-cluster
                context:
                  cluster: target-cluster
                  user: admin-user
            users:
              - name: admin-user
                user:
                  client-certificate-data: <base64-admin-client-certificate>
                  client-key-data: <base64-admin-client-key>
          caCert: ""
      openstack:
        enabled: true
        version: ""
        config:
          cloudsYaml: |
            clouds:
              target:
                auth:
                  auth_url: https://keystone.example.com:5000/v3
                  username: <openstack-username>
                  password: <openstack-password>
                  project_name: <openstack-project>
                  user_domain_name: Default
                  project_domain_name: Default
                region_name: RegionOne
          caCert: ""
```

Important notes:

- Put the Kubernetes admin client certificate and private key inside the embedded `kubeconfig`.
- `stackstorm.bootstrap.packs.kubernetes.config.caCert` is optional and only needed if you want to
  mount the cluster CA separately instead of using kubeconfig-embedded `certificate-authority-data`.
- `stackstorm.bootstrap.packs.openstack.config.caCert` is optional and only needed when the target
  cloud uses a private CA that should be mounted separately.
- These values are secrets. Keep them only in secured operator-managed override files such as
  `/etc/poundcake/helm-configs/poundcake/10-main-overrides.yaml`, and do not commit real
  credentials or certificate material to the repo.

Once these values are present, the PoundCake Helm bootstrap flow will install and configure the
enabled StackStorm packs automatically.

For horizontally scaled StackStorm deployments, use shared RWX storage for third-party pack files
and virtualenvs so newly created pods can immediately access the same pack content.

If those shared PVC-backed directories already contain third-party pack content from an earlier
install, the bootstrap job reuses the existing pack and virtualenv directories rather than deleting
and recreating them. This avoids permission failures on persistent RWX storage during reinstall.
If you intentionally want to replace the third-party pack content, clear the corresponding PVC
contents first and then rerun the installer.

If the shared pack directories are owned by a group such as `st2packs`, align all StackStorm
deployments and startup jobs with that numeric GID using `stackstormPodSecurityContext`. Example:

```yaml
stackstormPodSecurityContext:
  fsGroup: 1001
  fsGroupChangePolicy: OnRootMismatch
  supplementalGroups:
    - 1001
```

Choose the numeric GID that owns `/opt/stackstorm/packs` and `/opt/stackstorm/virtualenvs` in your
environment. This is especially important when `st2-register-content --register-setup-virtualenvs`
creates additional pack virtualenvs like `chatops`: the parent `/opt/stackstorm/virtualenvs`
directory must be writable to the pod's effective group, not only to the preinstalled pack mounts.

Example:

```yaml
longhorn:
  rwxStorageClass:
    create: true
    name: longhorn-rwx

persistence:
  stackstormSharedStorage:
    enabled: true
    storageClassName: longhorn-rwx
    accessMode: ReadWriteMany
    packVolumeSize: 5Gi
    virtualenvVolumeSize: 10Gi
```

This chart can create the Longhorn RWX `StorageClass` during Helm install when
`longhorn.rwxStorageClass.create=true`. A repo-local example manifest also lives at
[config/storage/longhorn-rwx-storageclass.yaml](../config/storage/longhorn-rwx-storageclass.yaml).

Longhorn RWX notes:

- Longhorn RWX volumes are served by share-manager pods over NFSv4.
- Each Kubernetes node mounting the volume needs an NFSv4 client installed.
- Longhorn recommends `migratable: "false"` for RWX volumes.

Documented operator-facing values:

- `stackstorm.bootstrap.packs.kubernetes.enabled`
- `stackstorm.bootstrap.packs.kubernetes.config.kubeconfig`
- `stackstorm.bootstrap.packs.kubernetes.config.caCert`
- `stackstorm.bootstrap.packs.openstack.enabled`
- `stackstorm.bootstrap.packs.openstack.config.cloudsYaml`
- `stackstorm.bootstrap.packs.openstack.config.caCert`
- `persistence.stackstormSharedStorage.enabled`
- `persistence.stackstormSharedStorage.storageClassName`
- `persistence.stackstormSharedStorage.packVolumeSize`
- `persistence.stackstormSharedStorage.virtualenvVolumeSize`
- `longhorn.rwxStorageClass.create`
- `longhorn.rwxStorageClass.name`

## Bakery Bootstrap Secret

The monitor ID is auto-derived by the chart as `<namespace>/<release>`. Create the PoundCake-side
secret in the PoundCake namespace with the bootstrap credential returned by Bakery plus a local
encryption key for the stored per-monitor secret:

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
kubectl -n <namespace> rollout status deploy/poundcake-api --timeout=300s
kubectl -n <namespace> rollout status deploy/poundcake-ui --timeout=300s
```

Confirm PoundCake is wired for remote Bakery:

```bash
helm get values <release-name> -n <namespace> -o yaml
kubectl -n <namespace> get secret bakery-monitor-bootstrap
kubectl -n <namespace> exec deploy/poundcake-api -- printenv | grep '^POUNDCAKE_BAKERY_'
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
kubectl -n <namespace> exec deploy/poundcake-mariadb -- \
  mariadb -u"$(kubectl -n <namespace> get secret poundcake-secrets -o jsonpath='{.data.DB_USER}' | base64 -d)" \
  -p"$(kubectl -n <namespace> get secret poundcake-secrets -o jsonpath='{.data.DB_PASSWORD}' | base64 -d)" \
  "$(kubectl -n <namespace> get secret poundcake-secrets -o jsonpath='{.data.DB_NAME}' | base64 -d)" \
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
kubectl get secret poundcake-admin -n <namespace> -o jsonpath='{.data.username}' | base64 -d; echo
kubectl get secret poundcake-admin -n <namespace> -o jsonpath='{.data.password}' | base64 -d; echo
kubectl get secret poundcake-admin -n <namespace> -o jsonpath='{.data.internal-api-key}' | base64 -d; echo
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
