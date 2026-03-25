# Remote Bakery Deployment Guide

This guide covers the PoundCake side of a split deployment. Bakery itself now lives in the
standalone [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.

Use this sequence:

1. Deploy Bakery from the standalone Bakery repo.
2. Publish Bakery at an HTTPS URL.
3. Create the same HMAC secret in both environments.
4. Configure PoundCake with `bakery.client.*` values.
5. Install and verify PoundCake.

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
      existingSecret: bakery-hmac
```

## Shared HMAC Secret

Generate one shared HMAC key and reuse it on both sides:

```bash
export SHARED_BAKERY_HMAC_KEY="$(openssl rand -base64 32)"
```

Create the PoundCake-side secret:

```bash
kubectl -n rackspace create secret generic bakery-hmac \
  --from-literal=active-key-id=active \
  --from-literal=active-key="${SHARED_BAKERY_HMAC_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Create the matching Bakery-side secret with the same key material by following the standalone
Bakery repo docs.

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
- `bakery.client.auth.existingSecret: bakery-hmac`

Confirm the public PoundCake endpoint:

```bash
curl -fsS https://<poundcake-public-hostname>/api/v1/health
```

If PoundCake still shows `POUNDCAKE_BAKERY_ENABLED=false` or an in-cluster Bakery URL, the release
was not redeployed with the remote Bakery client settings.
