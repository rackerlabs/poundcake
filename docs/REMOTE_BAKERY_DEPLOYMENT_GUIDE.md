# Deployment Guide: Bakery And PoundCake In Different Environments

This is the supported split-environment flow:

1. Install Bakery in the Bakery environment.
2. Publish Bakery at an HTTPS URL.
3. Create the same HMAC secret in both environments.
4. Install PoundCake with remote Bakery values in its override file.
5. Verify both sides.

The key rule is simple: remote Bakery settings live in values files, not installer flags.

## Assumptions

- Bakery and PoundCake run in different namespaces or different clusters inside Genestack-style environments.
- Bakery will be reachable at an HTTPS URL such as `https://bakery.example.com`.
- Chart versions are sourced from `/etc/genestack/helm-chart-versions.yaml`.
- Active overrides live under `/etc/genestack/helm-configs/`.
- PoundCake-specific overrides live under `/etc/genestack/helm-configs/poundcake/`.
- Global overrides live under `/etc/genestack/helm-configs/global_overrides/`.
- Gateway API already has a parent Gateway named `flex-gateway` in namespace `envoy-gateway`.
- Image repositories and tags are already pinned in your override files.

Set the published Bakery URL you will use from the PoundCake side:

```bash
export BAKERY_URL="https://bakery.example.com"
```

The shared HMAC key is created manually on purpose. `install-bakery-helm.sh` can manage the Bakery-side secret in its own namespace, but it does not create the matching client secret in the remote PoundCake namespace or cluster.

## Step 1: Prepare Override Files

Bakery environment:

- Create or update `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`.
- Put the Bakery Gateway publication values in that active override file:

```yaml
bakery:
  gateway:
    enabled: true
    gatewayName: "flex-gateway"
    gatewayNamespace: "envoy-gateway"
    listener:
      name: "bakery-https"
      hostname: "<bakery-public-hostname>"
      port: 443
      protocol: "HTTPS"
      tlsSecretName: "bakery-gw-tls-secret"
      allowedNamespaces: "All"
      updateIfExists: true
    hostnames:
      - "<bakery-public-hostname>"
  auth:
    existingSecret: bakery-hmac
```

PoundCake environment:

- Create or update `/etc/genestack/helm-configs/poundcake/10-main-overrides.yaml`.
- Put the PoundCake publication settings and remote Bakery client settings in that active override file:

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
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-hmac
```

## Step 2: Create The Shared HMAC Secret In Both Environments

Generate one shared HMAC key and reuse that exact same key in both environments:

```bash
export SHARED_BAKERY_HMAC_KEY="$(openssl rand -base64 32)"
```

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
  --bakery-rackspace-url <rackspace-core-url> \
  --bakery-rackspace-username <rackspace-core-username> \
  --bakery-rackspace-password '<password>'
```

If `bakery-rackspace-core` does not already exist, the Bakery installer will prompt for those Rackspace Core values when run interactively. In automation or any non-interactive shell, pass the `--bakery-rackspace-*` flags.

Wait for Bakery to roll out:

```bash
kubectl -n bakery rollout status deploy/bakery-poundcake-bakery --timeout=180s
kubectl -n bakery rollout status deploy/bakery-poundcake-bakery-worker --timeout=180s
```

## Step 4: Verify Bakery Is Published Through Gateway API

The previous steps already set the Bakery Gateway values in the active override file. During the Bakery install, the chart should publish Bakery at the exact HTTPS URL PoundCake will use.

This step verifies that the rendered Gateway API resources attached correctly and that the external Bakery endpoint is live.

For that to work, the Bakery release values must already include:

- `bakery.gateway.enabled: true`
- the Genestack parent Gateway `flex-gateway` in namespace `envoy-gateway`
- a Bakery listener name/hostname/TLS secret
- a matching Bakery hostname under `bakery.gateway.hostnames`

After the Bakery release is installed, verify the Gateway path end to end:

```bash
kubectl -n envoy-gateway get gateway flex-gateway
kubectl -n bakery get httproute
kubectl -n bakery get httproute <bakery-httproute-name> -o yaml
curl -fsS "${BAKERY_URL}/api/v1/health"
```

Do not install PoundCake remote mode until the Bakery `HTTPRoute` shows an accepted parent and the external health check is returning `200`.

## Step 5: Install PoundCake

Run these commands in the PoundCake environment:

```bash
./install/install-poundcake-helm.sh
```

Wait for PoundCake to roll out:

```bash
kubectl -n rackspace rollout status deploy/poundcake-api --timeout=180s
kubectl -n rackspace rollout status deploy/poundcake-ui --timeout=180s
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

- `gateway.enabled: true`
- `gateway.listener.name: poundcake-https`
- `gateway.listener.tlsSecretName: poundcake-gw-tls-secret`
- `bakery.client.enabled: true`
- `bakery.client.enforceRemoteBaseUrl: true`
- `bakery.client.baseUrl: ${BAKERY_URL}`
- `bakery.client.auth.existingSecret: bakery-hmac`

Things to confirm in the Bakery release values:

- `bakery.gateway.enabled: true`
- `bakery.gateway.gatewayName: flex-gateway`
- `bakery.gateway.gatewayNamespace: envoy-gateway`
- `bakery.gateway.listener.hostname: <bakery-public-hostname>`
- `bakery.gateway.listener.tlsSecretName`

## Step 7: Connect Supporting Components And Complete Bootstrap

After both releases are healthy, complete the application bootstrap and surrounding integrations so the environment is fully functional:

- get the generated PoundCake admin credentials
- sign in to PoundCake
- set the global communications policy to include Rackspace Core
- configure Alertmanager to send authenticated webhook traffic to PoundCake

Get the default local admin credentials and service token:

```bash
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.username}' | base64 -d; echo
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.password}' | base64 -d; echo
kubectl get secret poundcake-admin -n rackspace -o jsonpath='{.data.internal-api-key}' | base64 -d; echo
```

You can configure the global communications policy in either the UI or the CLI.

UI path:

1. Open `https://<poundcake-public-hostname>/login`.
2. Sign in with the generated local admin credentials.
3. Go to `Configuration -> Global Communications`.
4. Add and save a Rackspace Core route with:

```yaml
label: "Rackspace Core"
execution_target: "rackspace_core"
provider_config:
  account_number: "<rackspace-account-number>"
```

CLI path:

```bash
poundcake --url https://<poundcake-public-hostname> auth login --provider local --username admin

poundcake --url https://<poundcake-public-hostname> global-communications set \
  --route-json '{"label":"Rackspace Core","execution_target":"rackspace_core","provider_config":{"account_number":"<rackspace-account-number>"}}'
```

The `auth login` command will prompt for the password you retrieved from `poundcake-admin`.

Alertmanager integration is configured in the Prometheus environment, not in the PoundCake UI or CLI. Point Alertmanager at the PoundCake webhook and authenticate it with the same `internal-api-key`.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: poundcake
  namespace: <prometheus-namespace>
spec:
  route:
    receiver: poundcake
    groupBy:
      - alertname
      - group_name
  receivers:
    - name: poundcake
      webhookConfigs:
        - url: http://poundcake-api.rackspace.svc.cluster.local:8000/api/v1/webhook
          sendResolved: true
          httpConfig:
            authorization:
              type: Bearer
              credentials:
                name: poundcake-admin
                key: internal-api-key
```

PoundCake also accepts `X-Auth-Token`, but the `Authorization: Bearer` form above matches the working Prometheus Operator integration used during the rebuild.

If you need auth and RBAC setup after deployment, continue with [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md).
