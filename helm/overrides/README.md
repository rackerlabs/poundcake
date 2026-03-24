# Helm Overrides

This directory stores example override files for Helm installs.

Recommended starter fragments:
- `poundcake-only-overrides.yaml`
- `bakery-only-overrides.yaml`
- `colocated-shared-db-overrides.yaml`
- `remote-bakery-overrides.yaml`
- `ghcr-pull-secret-overrides.yaml`
- `split-install/`

Canonical image keys for overrides:
- `poundcakeImage.repository` / `poundcakeImage.tag`
- `uiImage.repository` / `uiImage.tag`
- `bakery.image.repository` / `bakery.image.tag`

Base example source in-repo:
- `helm/base-overrides/poundcake-helm-overrides-examples.yaml`
  (copy/merge into `/etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml`)

Service selection in overrides now uses explicit booleans:
- `poundcake.enabled` (PoundCake + StackStorm resources)
- `bakery.enabled` (Bakery resources)

Installer mapping:
- `./install/install-poundcake-helm.sh` => `poundcake.enabled=true`, `bakery.enabled=false`
- `./install/install-bakery-helm.sh` => `poundcake.enabled=false`, `bakery.enabled=true`
- For co-located deployments in one namespace: install Bakery first, then PoundCake.

Values-first note:
- Put runtime config such as remote Bakery, shared DB mode, and `poundcakeImage.pullSecrets` in override files.
- Use installer flags for operational behavior and optional secret creation only.
- The Bakery installer forwards `existingSecret` names only when you intentionally choose a non-default secret name.

## Enable HA

1. Copy the HA example to the Genestack PoundCake overrides path:

```bash
sudo mkdir -p /etc/genestack/helm-configs/poundcake
sudo cp helm/overrides/ha-overrides.yaml /etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml
```

2. Run the Helm installer:

```bash
./install/install-poundcake-helm.sh
```

The installer will automatically include:

- `/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml`
- `/etc/genestack/helm-configs/global_overrides/*.yaml`
- `/etc/genestack/helm-configs/poundcake/*.yaml`
- kustomize post-renderer from `/etc/genestack/kustomize` (when present)

## Verify

```bash
kubectl -n rackspace get deploy poundcake poundcake-chef poundcake-timer poundcake-dishwasher
kubectl -n rackspace get svc poundcake
```

## Enable Envoy Gateway Route/Listener

Use the provided shared-host Gateway override to create/update:
- Gateway listener on `HTTPS`/`443`
- HTTPRoute for your published PoundCake hostname

1. Review and adjust gateway object names/namespace and TLS secret:

```bash
cat helm/overrides/gateway-shared-hostname-overrides.yaml
```

2. Copy into the active Genestack PoundCake override path:

```bash
sudo mkdir -p /etc/genestack/helm-configs/poundcake
sudo cp helm/overrides/gateway-shared-hostname-overrides.yaml /etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml
```

3. Install/upgrade:

```bash
./install/install-poundcake-helm.sh
```
