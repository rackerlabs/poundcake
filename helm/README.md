# poundcake Helm Chart

This chart deploys PoundCake, its UI, and the StackStorm components it depends on.

## Key Points

- The chart no longer renders any in-cluster Bakery resources.
- Remote Bakery is configured only through `bakery.client.*` values.
- If `bakery.client.enabled=true`, `bakery.client.baseUrl` must be set.
- Bakery itself is deployed from the standalone
  [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.

## Install

```bash
helm upgrade --install poundcake ./helm \
  --set poundcakeImage.repository=<your-repo/poundcake> \
  --set poundcakeImage.tag=<tag>
```

## Remote Bakery

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

## Installer

Use the repo wrapper for PoundCake:

```bash
./install/install-poundcake-helm.sh
```

Use the standalone Bakery repo for Bakery installs.

## Optional StackStorm Packs

The chart can install the StackStorm `kubernetes` and `openstack` packs into
the StackStorm pods during startup. Both are opt-in.

For horizontally scaled StackStorm components, enable shared RWX storage for third-party pack files
and virtualenvs so new pods can mount the same content immediately. Longhorn RWX is supported via
`longhorn.rwxStorageClass.create=true` together with
`persistence.stackstormSharedStorage.enabled=true`.

When those shared PVC-backed pack or virtualenv directories already contain content from a previous
install, the bootstrap flow now reuses the existing directories instead of deleting them. This keeps
re-runs idempotent on RWX storage. Replacing existing third-party pack content requires a deliberate
manual cleanup step before rerunning bootstrap.

If the shared `/opt/stackstorm/packs` and `/opt/stackstorm/virtualenvs` parents are owned by a
group other than the container's default GID, set `stackstormPodSecurityContext` so StackStorm
workloads and startup hooks join the owning group. Example:

```yaml
stackstormPodSecurityContext:
  fsGroup: 1001
  fsGroupChangePolicy: OnRootMismatch
  supplementalGroups:
    - 1001
```

Use the numeric GID that owns the shared directories inside the StackStorm image or volume mount.

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
            clusters: []
            contexts: []
            current-context: ""
            kind: Config
            users: []
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
                  username: example
                  password: example
                  project_name: example
                  user_domain_name: Default
                  project_domain_name: Default
                region_name: RegionOne
          caCert: ""
```

Operational requirements:

- StackStorm pods need outbound access to StackStorm Exchange / GitHub to install the packs.
- The `kubernetes` pack needs a valid kubeconfig and enough RBAC on the target cluster.
- The `openstack` pack needs a valid `clouds.yaml`-style config and credentials that can reach Keystone and the requested service APIs.
- If either remote endpoint uses a private CA, provide the CA content in `caCert` and reference it from the corresponding config.

For the operator override-file version of these examples, including how to place Kubernetes admin
cert/key material and OpenStack credentials into `10-main-overrides.yaml`, see
[docs/DEPLOY.md](../docs/DEPLOY.md).
