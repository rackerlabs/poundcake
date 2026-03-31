# Remote Bakery Deployment Guide

This guide covers the PoundCake side of a split deployment. Bakery itself now lives in the
standalone [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.

Use this sequence:

1. Deploy Bakery from the standalone Bakery repo.
2. Publish Bakery at an HTTPS URL.
3. Create a Bakery bootstrap credential for this PoundCake monitor ID.
4. Create the PoundCake bootstrap secret with that credential and a local encryption key.
5. Configure PoundCake with `bakery.client.*` values.
6. Install and verify PoundCake.

## Bakery Deployment Source

Deploy Bakery from the standalone repo and follow its install docs for Gateway publication,
provider secrets, and Bakery-side HMAC configuration:

- [bakery/docs/DEPLOY.md](https://github.com/rackerlabs/bakery/blob/main/docs/DEPLOY.md)
- [bakery/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](https://github.com/rackerlabs/bakery/blob/main/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md)

Assume Bakery will be reachable at a URL such as:

```bash
export BAKERY_URL="https://bakery.example.com"
```

## PoundCake Override Example

Put the PoundCake-side remote Bakery settings in the active PoundCake override file, typically
`/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`:

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
once, registers itself as `<namespace>/<release>`, then stores the returned per-monitor secret
locally.

Create the PoundCake-side secret after the Bakery admin endpoint returns the bootstrap key:

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

The Bakery-side flow, including the admin endpoint used to mint the bootstrap credential for the
`<namespace>/<release>` monitor ID, is documented in the standalone Bakery repo.

## Install PoundCake

Run the PoundCake install from this repo:

```bash
./install/install-poundcake-helm.sh
```

Wait for rollout:

```bash
kubectl -n rackspace rollout status deploy/poundcake-api --timeout=180s
kubectl -n rackspace rollout status deploy/poundcake-ui --timeout=180s
```

## Verify Remote Bakery Wiring

Confirm release values:

```bash
helm get values poundcake -n rackspace -o yaml
```

Confirm runtime env:

```bash
kubectl -n rackspace exec deploy/poundcake-api -- printenv | grep '^POUNDCAKE_BAKERY_'
```

Expected shape:

- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl: ${BAKERY_URL}`
- `bakery.client.auth.existingSecret: bakery-monitor-bootstrap`
- `POUNDCAKE_BAKERY_MONITOR_ID: <namespace>/<release>`

Confirm the public PoundCake endpoint:

```bash
curl -fsS https://<poundcake-public-hostname>/api/v1/health
```

If PoundCake still shows `POUNDCAKE_BAKERY_ENABLED=false` or an in-cluster Bakery URL, the release
was not redeployed with the remote Bakery client settings.
