# poundcake Helm Chart

This chart deploys PoundCake, its UI, and the StackStorm components it depends on.

## Key Points

- The chart no longer renders any in-cluster Bakery resources.
- Remote Bakery is configured only through `bakery.client.*` values.
- If `bakery.client.enabled=true`, `bakery.client.baseUrl` must be set.
- Bakery itself is deployed from the standalone
  [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.

## Install

Recommended path:

```bash
./install/install-poundcake-helm.sh
```

For repeatable rollouts, update `/etc/poundcake/helm-chart-versions.yaml` or export
`POUNDCAKE_CHART_VERSION` before running the installer. Normal releases should move by chart
version; leave image tag overrides unset so PoundCake, UI, and helper images inherit the chart's
`appVersion` defaults.

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

Creating the bootstrap secret alone does not enable remote Bakery. PoundCake must be deployed with
`bakery.client.enabled=true` and `bakery.client.baseUrl` pointing at the external Bakery URL.

## Release Update Advisories

`releaseUpdateNotifications.enabled` defaults to `true`. The API checks the configured OCI chart
repository every `releaseUpdateNotifications.checkIntervalSeconds` seconds and opens informational
advisories through the enabled global communications routes when it finds a newer PoundCake
`appVersion`. PoundCake never upgrades itself.

PoundCake records each available app/chart version after successful delivery, so manually closing
the remote ticket or notification does not recreate that advisory. If Bakery or global routes are
not ready, the checker retries later. PoundCake supplies the advisory content and route context;
Bakery renders the final provider-native format.

## Installer

Use the repo wrapper for PoundCake:

```bash
./install/install-poundcake-helm.sh
```

Use the standalone Bakery repo for Bakery installs.

By default, the StackStorm actionrunner service account gets cluster-scoped RBAC to patch PVCs,
delete pods, create pod evictions, and patch Deployments, StatefulSets, and DaemonSets for
workload recycling. Operators can disable either permission set with
`stackstormActionrunner.pvcPatchRbac.enabled=false` or
`stackstormActionrunner.workloadRecycleRbac.enabled=false`.

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
This is required when StackStorm later creates additional virtualenv directories such as
`/opt/stackstorm/virtualenvs/chatops`; parent-directory RWX mounts only help if the pod is a
member of the owning group, typically `st2packs`.

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
        source:
          type: git
          name: openstack
          repoUrl: https://github.com/StackStorm-Exchange/stackstorm-openstack.git
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
- When enabling the `openstack` pack, prefer the Git source shown above instead of relying on the
  implicit Exchange source.
- If either remote endpoint uses a private CA, provide the CA content in `caCert` and reference it from the corresponding config.

## Optional Bootstrap Recipe Repo Sync

The chart defaults `bootstrap.rulesRepoUrl` to blank. Leave it blank unless you explicitly want
bootstrap-managed recipes generated from a remote rules repo.

If you do enable it, make sure the repo is reachable from the cluster and that `git.existingSecret`
or another supported Git credential path is configured when the repo is private.

For the operator override-file version of these examples, including how to place Kubernetes admin
cert/key material and OpenStack credentials into `10-main-overrides.yaml`, see
[docs/DEPLOY.md](../docs/DEPLOY.md).
