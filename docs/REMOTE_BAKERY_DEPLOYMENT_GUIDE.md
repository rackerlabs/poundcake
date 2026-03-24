# Deployment Guide: Bakery And PoundCake In Different Environments

This is the opinionated deployment path for a split-environment install:

1. Deploy Bakery in the Bakery environment.
2. Expose Bakery at an HTTPS URL that the PoundCake environment can reach.
3. Deploy PoundCake in the PoundCake environment.
4. Verify both sides.

This guide intentionally avoids the installer option matrix. It shows the normal sequence and the exact steps to run.

## Assumptions

- Bakery and PoundCake run in different namespaces or different clusters.
- Bakery will be reachable at an HTTPS URL such as `https://bakery.example.com`.
- Image repositories and tags are already pinned in Helm values or override files.
- Helm chart version comes from `/etc/genestack/helm-chart-versions.yaml`.

Generate one shared HMAC key and reuse it in both environments:

```bash
export SHARED_BAKERY_HMAC_KEY="$(openssl rand -base64 32)"
export BAKERY_URL="https://bakery.example.com"
```

Important:

- The Bakery installer will create the Bakery HMAC secret for you.
- If you do not set `POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY`, the Bakery installer will generate a random key itself.
- For a split-environment deployment, do not rely on that auto-generated key. Generate the shared key yourself once and reuse the same value for both Bakery and PoundCake.
- `openssl rand -base64 32` generates 32 random bytes encoded as base64, not 32 bits.

## Step 1: Deploy Bakery

Run these commands in the Bakery environment:

```bash
export POUNDCAKE_NAMESPACE="bakery"
export POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY="${SHARED_BAKERY_HMAC_KEY}"

./install/install-bakery-helm.sh \
  --bakery-auth-secret-name bakery-hmac \
  --bakery-rackspace-url https://ws.core.rackspace.com \
  --bakery-rackspace-username poundcake \
  --bakery-rackspace-password '<password>'
```

Wait for Bakery to finish rolling out:

```bash
kubectl -n bakery rollout status deploy/bakery-poundcake-bakery --timeout=180s
kubectl -n bakery rollout status deploy/bakery-poundcake-bakery-worker --timeout=180s
```

## Step 2: Expose Bakery

Publish Bakery at the URL you want PoundCake to use. After that, verify it responds:

```bash
curl -fsS "${BAKERY_URL}/api/v1/health"
```

## Step 3: Deploy PoundCake

Run these commands in the PoundCake environment:

```bash
export POUNDCAKE_NAMESPACE="poundcake"

./install/install-poundcake-helm.sh \
  --remote-bakery-url "${BAKERY_URL}" \
  --remote-bakery-auth-mode hmac \
  --remote-bakery-auth-secret bakery-hmac \
  --remote-bakery-hmac-key "${SHARED_BAKERY_HMAC_KEY}"
```

Wait for PoundCake to finish rolling out:

```bash
kubectl -n poundcake rollout status deploy/poundcake-api --timeout=180s
kubectl -n poundcake rollout status deploy/poundcake-ui --timeout=180s
```

## Step 4: Verify The Deployment

Bakery environment:

```bash
kubectl -n bakery get secret bakery-hmac
curl -fsS "${BAKERY_URL}/api/v1/health"
```

PoundCake environment:

```bash
kubectl -n poundcake get secret bakery-hmac
kubectl -n poundcake get deploy
```

That is the deployment sequence:

1. Install Bakery first.
2. Expose Bakery.
3. Install PoundCake with the Bakery URL and the same HMAC key.
4. Verify rollout and health.

If you need auth and RBAC setup after the deployment, continue with [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).
