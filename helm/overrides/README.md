# Helm Override Examples

This directory contains sanitized example fragments and example layouts.

These files are not the supported live deployment path by themselves. In Genestack, the active values come from:

- `/etc/genestack/helm-chart-versions.yaml`
- `/etc/genestack/helm-configs/global_overrides/*.yaml`
- `/etc/genestack/helm-configs/poundcake/*.yaml`

Recommended live file layout:

- `00-pull-secret-overrides.yaml`
- `10-main-overrides.yaml`
- `20-auth-overrides.yaml`
- `30-git-sync-overrides.yaml`

Use the files in this directory as merge sources or sanitized examples, not as a direct substitute for the live Genestack files.

## What Each Example Is For

- `poundcake-only-overrides.yaml`
  - Minimal service-selection example for PoundCake-only installs.
- `bakery-only-overrides.yaml`
  - Minimal service-selection and provider-reference example for Bakery-only installs.
- `colocated-shared-db-overrides.yaml`
  - Merge into the active PoundCake main override when PoundCake should use the Bakery MariaDB operator server in the same environment.
- `remote-bakery-overrides.yaml`
  - Merge into the PoundCake-side main override when PoundCake should use a remote Bakery deployment.
- `ghcr-pull-secret-overrides.yaml`
  - Merge into `00-pull-secret-overrides.yaml` to reference an existing registry pull secret.
- `gateway-shared-hostname-overrides.yaml`
  - Merge into `10-main-overrides.yaml` when PoundCake should publish through Gateway API on a shared hostname.
- `ha-overrides.yaml`
  - Merge into `10-main-overrides.yaml` to scale PoundCake workers and enable a basic HA footprint.
- `split-install/`
  - Sanitized example of the supported Genestack split-install layout.

## Values-First Rules

- Put runtime config such as remote Bakery, shared DB mode, gateway publication, auth provider enablement, Git sync, and `poundcakeImage.pullSecrets` in values files.
- Use installer flags for operational behavior and optional secret creation only.
- Bakery provider credentials should live in Kubernetes Secrets referenced by `existingSecret` values.
- The installers own service selection:
  - `install-poundcake-helm.sh` renders PoundCake only
  - `install-bakery-helm.sh` renders Bakery only

## Common Merge Targets

Use these example-to-live mappings:

- pull-secret reference fragments -> `/etc/genestack/helm-configs/poundcake/00-pull-secret-overrides.yaml`
- Gateway, database, remote Bakery, Bakery runtime, scaling, scheduling, and resource fragments -> `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`
- auth provider fragments -> `/etc/genestack/helm-configs/poundcake/20-auth-overrides.yaml`
- Git sync fragments -> `/etc/genestack/helm-configs/poundcake/30-git-sync-overrides.yaml`

## Related Docs

- [DEPLOY.md](/Users/aedan/Documents/GitHub/poundcake/docs/DEPLOY.md)
- [REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](/Users/aedan/Documents/GitHub/poundcake/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md)
- [REFERENCE.md](/Users/aedan/Documents/GitHub/poundcake/docs/REFERENCE.md)
