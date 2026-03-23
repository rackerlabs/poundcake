# Quick Start: Bakery And PoundCake In Different Environments

This guide covers the supported "split environment" layout:

- Bakery runs in one namespace or cluster.
- PoundCake runs in a different namespace or cluster.
- PoundCake calls Bakery over a reachable HTTPS URL.
- Bakery and PoundCake keep separate database ownership.

This is the installer-focused quick start. The Docker Compose quick start is for local development on one machine and is not the deployment flow described here.

Recommended flow:

- Install Bakery first.
- Set an explicit Bakery HMAC key during Bakery install.
- Install PoundCake with `--remote-bakery-url` and the same HMAC key.
- Let the PoundCake installer create its local client secret.

If you are using a provider other than Rackspace Core, keep the same overall flow and swap in the matching `--bakery-<provider>-...` installer flags for the Bakery side.

## Before You Start

Make sure you have:

- a Bakery URL reachable from the PoundCake environment, for example `https://bakery.example.com`
- a shared HMAC secret value that both environments will use
- the image tag or digest values you plan to deploy
- image pull auth configured if you deploy private GHCR images
- provider credentials ready for the Bakery side if you are enabling a real ticketing provider

Important notes:

- Do not enable shared DB mode across environments. When Bakery is remote, PoundCake should keep its own database resources.
- The Kubernetes secret names do not have to match across environments, but the HMAC key material must match.
- `GET /api/v1/health` is open on Bakery, so you can test reachability before wiring PoundCake to it.
- Helm chart version is resolved by the installers from `/etc/genestack/helm-chart-versions.yaml` by default.
- Image repositories/tags/digests must be configured in values files or override files, not installer env vars.

Set the shared values once so both installs use the same URL and HMAC key:

```bash
export BAKERY_URL=https://bakery.example.com
export SHARED_BAKERY_HMAC_KEY='<shared-hmac-key>'
```

If you need to generate a fresh HMAC key, one simple option is:

```bash
export SHARED_BAKERY_HMAC_KEY="$(openssl rand -base64 32)"
```

## Step 1: Install Bakery In The Bakery Environment

Set the HMAC key that PoundCake will use later:

```bash
export POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY="${SHARED_BAKERY_HMAC_KEY}"
```

Install Bakery and store that key in a named Bakery auth secret:

```bash
export POUNDCAKE_NAMESPACE=bakery

./install/install-bakery-helm.sh \
  --bakery-auth-secret-name bakery-hmac \
  --bakery-rackspace-url https://ws.core.rackspace.com \
  --bakery-rackspace-username poundcake \
  --bakery-rackspace-password '<password>'
```

If you are doing an initial connectivity test, append this flag to the Bakery install command:

```bash
--set bakery.config.ticketingDryRun=true
```

Expose Bakery using your normal ingress, Gateway API, or load balancer workflow, then confirm PoundCake will be able to reach the final URL:

```bash
curl -fsS "${BAKERY_URL}/api/v1/health"
```

## Step 2: Install PoundCake In The PoundCake Environment

Use the same HMAC key on the PoundCake side and let the PoundCake installer create the local client secret:

```bash
export POUNDCAKE_NAMESPACE=poundcake

./install/install-poundcake-helm.sh \
  --remote-bakery-url "${BAKERY_URL}" \
  --remote-bakery-auth-mode hmac \
  --remote-bakery-auth-secret bakery-hmac \
  --remote-bakery-hmac-key "${SHARED_BAKERY_HMAC_KEY}"
```

What this does:

- enables the PoundCake Bakery client
- points PoundCake at the remote Bakery URL
- creates the `bakery-hmac` secret in the PoundCake namespace if it does not already exist
- wires `bakery.client.auth.existingSecret=bakery-hmac`
- leaves PoundCake in normal embedded DB mode unless you explicitly override it

Before running those commands, ensure the image refs for each environment are pinned in your values or override files.
Typical override path: `/etc/genestack/helm-configs/poundcake/poundcake-helm-overrides.yaml`.

## Repeat Installs And Upgrades

The command above is the easiest first install because it lets the installer create the PoundCake-side client secret. On later reruns, that secret will already exist. At that point either:

- rerun with `--remote-bakery-auth-secret bakery-hmac` and omit `--remote-bakery-hmac-key`, or
- rotate/manage the secret explicitly and keep using `--remote-bakery-auth-secret`.

## Alternate PoundCake Flow: Reuse A Pre-Created Secret

If the PoundCake environment already has the client secret, create it yourself and point the installer at it:

```bash
kubectl -n poundcake create secret generic bakery-hmac \
  --from-literal=active-key-id=active \
  --from-literal=active-key="${SHARED_BAKERY_HMAC_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then install PoundCake without passing the raw HMAC key:

```bash
./install/install-poundcake-helm.sh \
  --remote-bakery-url "${BAKERY_URL}" \
  --remote-bakery-auth-mode hmac \
  --remote-bakery-auth-secret bakery-hmac
```

## Verify The Wiring

Bakery environment:

```bash
kubectl -n bakery get secret bakery-hmac
kubectl -n bakery get deploy
curl -fsS "${BAKERY_URL}/api/v1/health"
```

PoundCake environment:

```bash
kubectl -n poundcake get secret bakery-hmac
kubectl -n poundcake get deploy
```

Optional: verify the PoundCake environment can reach Bakery directly:

```bash
kubectl -n poundcake run bakery-healthcheck \
  --rm -i --restart=Never \
  --image=curlimages/curl:8.12.1 \
  -- curl -fsS "${BAKERY_URL}/api/v1/health"
```

If you want to confirm the HMAC key id on both sides:

```bash
kubectl -n bakery get secret bakery-hmac -o jsonpath='{.data.active-key-id}' | base64 -d; echo
kubectl -n poundcake get secret bakery-hmac -o jsonpath='{.data.active-key-id}' | base64 -d; echo
```

## Common Gotchas

- If Bakery auto-generated its own HMAC secret earlier, PoundCake will not know that secret value automatically across clusters. For split environments, prefer setting `POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY` explicitly during the Bakery install.
- If you pass `--remote-bakery-hmac-key` to the PoundCake installer and the target secret already exists, the installer will fail instead of rotating the secret.
- If PoundCake cannot reach Bakery, validate DNS, TLS, firewall rules, and the external route before debugging HMAC auth.
- Do not set `--shared-db-mode on` just because Bakery exists somewhere else. Shared DB auto-discovery only applies to co-located installs.

## Related Docs

- Main deployment guide: [DEPLOY.md](DEPLOY.md)
- Auth and RBAC setup: [AUTH.md](AUTH.md)
