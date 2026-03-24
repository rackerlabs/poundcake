# Deployment Guide: Bakery And PoundCake In Different Environments

This is the supported split-environment flow:

1. Install Bakery in the Bakery environment.
2. Publish Bakery at an HTTPS URL.
3. Create the same HMAC secret in both environments.
4. Install PoundCake with remote Bakery values in its override file.
5. Verify both sides.

The key rule is simple: remote Bakery settings live in values files, not installer flags.

## Assumptions

- Bakery and PoundCake run in different namespaces or different clusters.
- Bakery will be reachable at an HTTPS URL such as `https://bakery.example.com`.
- Chart versions are sourced from `/etc/genestack/helm-chart-versions.yaml`.
- Image repositories and tags are already pinned in your override files.

Generate one shared HMAC key and reuse it in both environments:

```bash
export SHARED_BAKERY_HMAC_KEY="$(openssl rand -base64 32)"
export BAKERY_URL="https://bakery.example.com"
```

## Step 1: Prepare Override Files

Bakery environment:

- Start from `helm/overrides/bakery-only-overrides.yaml`.

PoundCake environment:

- Start from `helm/overrides/poundcake-only-overrides.yaml`.
- Merge in `helm/overrides/remote-bakery-overrides.yaml`.
- Set:

```yaml
bakery:
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-hmac
```

## Step 2: Create The Shared HMAC Secret In Both Environments

Bakery environment:

```bash
kubectl -n bakery create secret generic bakery-hmac \
  --from-literal=active-key-id=active \
  --from-literal=active-key="${SHARED_BAKERY_HMAC_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

PoundCake environment:

```bash
kubectl -n rackspace create secret generic bakery-hmac \
  --from-literal=active-key-id=active \
  --from-literal=active-key="${SHARED_BAKERY_HMAC_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

If you use a different secret name, set that same name in both override files with `existingSecret`.

## Step 3: Install Bakery

Run these commands in the Bakery environment:

```bash
export POUNDCAKE_NAMESPACE="bakery"

./install/install-bakery-helm.sh \
  --bakery-auth-secret-name bakery-hmac \
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<password>'
```

Wait for Bakery to roll out:

```bash
kubectl -n bakery rollout status deploy/bakery-poundcake-bakery --timeout=180s
kubectl -n bakery rollout status deploy/bakery-poundcake-bakery-worker --timeout=180s
```

## Step 4: Publish Bakery

Expose Bakery at the URL PoundCake will use, then verify:

```bash
curl -fsS "${BAKERY_URL}/api/v1/health"
```

## Step 5: Install PoundCake

Run these commands in the PoundCake environment:

```bash
export POUNDCAKE_NAMESPACE="rackspace"
./install/install-poundcake-helm.sh
```

Wait for PoundCake to roll out:

```bash
kubectl -n poundcake rollout status deploy/poundcake-api --timeout=180s
kubectl -n poundcake rollout status deploy/poundcake-ui --timeout=180s
```

## Step 6: Verify

Bakery environment:

```bash
kubectl -n bakery get secret bakery-hmac
curl -fsS "${BAKERY_URL}/api/v1/health"
```

PoundCake environment:

```bash
kubectl -n rackspace get secret bakery-hmac
helm get values poundcake -n rackspace -o yaml
kubectl -n rackspace get deploy
```

Things to confirm in the PoundCake release values:

- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl: ${BAKERY_URL}`
- `bakery.client.auth.existingSecret: bakery-hmac`

If you need auth and RBAC setup after deployment, continue with [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).
