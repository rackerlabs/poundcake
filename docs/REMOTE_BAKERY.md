# Remote Bakery Plugin Deployment

## Summary

PoundCake uses Bakery as the `bakery` plugin for external communication work. In
production, Bakery is deployed separately as its own Helm release, exposed at an
HTTPS URL, and connected to PoundCake through the plugin configuration and a
Bakery-issued bootstrap HMAC.

The operator registration path is the same as before the service-plugin rewrite:

1. Deploy Bakery and publish it at an HTTPS URL.
2. Mint a bootstrap credential in Bakery for this PoundCake monitor ID.
3. Apply that bootstrap Secret in the PoundCake namespace.
4. Set the remote Bakery client Helm values and point them at that Secret.
5. PoundCake registers itself with Bakery and stores the issued monitor HMAC in
   credential-manager.

Bakery owns provider credentials and provider-native ticket behavior. PoundCake
owns plugin identity, order flow, and the persisted adapter credential.

For the full PoundCake Helm deployment flow, see [OPERATOR.md](OPERATOR.md).
Bakery-side minting is documented in
[bakery/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](https://github.com/rackerlabs/bakery/blob/main/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md).

## Register A New Monitor

Pick a stable monitor ID before minting the bootstrap credential. Bakery and
PoundCake must use the same value. The PoundCake default is
`<namespace>/<release>` unless `bakery.client.monitor.id` is set. Do not reuse
the same ID across independent clusters.

On the Bakery cluster:

```bash
cd /opt/bakery
./bin/create-monitor-bootstrap.sh \
  --monitor-id rackspace/poundcake \
  --poundcake-namespace rackspace \
  > bakery-monitor-bootstrap.yaml
```

The helper creates a pending Bakery bootstrap credential and prints a Kubernetes
Secret for the PoundCake namespace. It does not create the monitor row. The
monitor is created when PoundCake calls `POST /api/v1/monitors/register`.

Apply the generated YAML in the PoundCake namespace:

```bash
kubectl apply -f bakery-monitor-bootstrap.yaml
```

The Secret keys PoundCake reads are `bootstrap-key-id` and `bootstrap-key`. The
script also emits `monitor-encryption-key`; that value belongs on Bakery's
`bakery-hmac` secret, not on PoundCake.

## PoundCake Helm Values

The chart default is `bakery.client.enabled: false`. Turning the client on is
enough to enable the `bakery` plugin: Helm appends `bakery` to
`config.enabledPlugins` automatically. You do not need a full plugin list just
to talk to Bakery.

Helm requires these three settings when the client is enabled. Apply the
bootstrap Secret in the PoundCake namespace first.

```yaml
bakery:
  client:
    enabled: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-monitor-bootstrap
```

The Secret keys PoundCake mounts are `bootstrap-key-id` and `bootstrap-key`.
Override `bakery.client.auth.secretKeys.*` only if the Secret uses different
key names.

Monitor ID defaults to `<namespace>/<release>`. Set it only when the bootstrap
credential was minted for a different value:

```yaml
bakery:
  client:
    monitor:
      id: example-cluster/poundcake
```

Do not reuse the same monitor ID across independent clusters.

`pluginId`, `activeProvider`, TLS verify, timeouts, and monitor metadata
(`environmentLabel`, `region`, `clusterName`, `tags`) all have chart defaults.
Set them only when the environment needs something other than those defaults.

### Default Core account

Registration does not need an account number. Opening Rackspace Core tickets
does. Manifest-driven communication routes do not store `account_number`, and a
UI or CLI edit of the route is not durable. Set the account on the Helm
client so PoundCake injects it at request time when a route has none:

```yaml
bakery:
  client:
    accountNumber: "<core-account-number>"
```

Use the Core account Bakery should ticket against. Do not put that value in
plugin configuration, the Plugins UI, or `cakectl plugins config`.

Install or upgrade PoundCake, then restart the API if the Secret was applied
after the first install:

```bash
./install/install-poundcake-helm.sh
kubectl -n <poundcake-namespace> rollout restart deploy/poundcake-api
```

On startup the bakery plugin:

1. reads `POUNDCAKE_BAKERY_BOOTSTRAP_HMAC_KEY_ID` / `POUNDCAKE_BAKERY_BOOTSTRAP_HMAC_KEY`
2. signs `POST /api/v1/monitors/register` with that bootstrap HMAC
3. stores the returned `monitor_id`, `monitor_uuid`, `hmac_key_id`, and
   `hmac_secret` as `bakery_monitor_hmac/default`
4. uses the issued monitor HMAC for later Bakery calls

If the issued credential already exists, PoundCake reuses it. Re-register only
when a new bootstrap Secret is applied and the bakery plugin bootstrap runs
with `force=true` (rotating the bootstrap credential on Bakery also requires
`--rotate` on `create-monitor-bootstrap.sh`).

## Optional Recovery Path

Admins can still write an already-issued monitor HMAC through
`/api/v1/plugins/bakery/credentials` or the Plugins UI. That is a recovery
path, not the normal new-monitor flow. The stored payload is:

```json
{
  "credential_type": "bakery_monitor_hmac",
  "credential_key_id": "default",
  "credential_payload": {
    "monitor_uuid": "<value issued by Bakery>",
    "monitor_id": "<stable PoundCake monitor id>",
    "hmac_key_id": "<value issued by Bakery>",
    "hmac_secret": "<value issued by Bakery>"
  },
  "rotate_credential": true
}
```

Non-secret connection settings (URL, TLS, retries, plugin identity, monitor
metadata) can also be saved through `/api/v1/plugins/bakery/configuration`.
That path does not set the Core account; keep `bakery.client.accountNumber` in
Helm.

## Operator UI And CLI

Helm owns Bakery registration and the default Core account. Everything else an
operator does against the PoundCake API for this plugin is available in both
the Plugins UI (`/config/plugins/bakery`) and `cakectl`.

| Need | UI | CLI |
|---|---|---|
| Inspect plugin and stored health | Plugins | `cakectl plugins show bakery` / `cakectl plugins health bakery` |
| Enable, disable, or change health cadence | Plugins controls | `cakectl plugins update bakery --enabled` / `--disabled` |
| Edit URL, TLS, and timeouts | Plugins → Adapter connection | `cakectl plugins config show bakery` / `cakectl plugins config set bakery --config-file ...` |
| Recovery monitor HMAC | Plugins → Adapter connection (admin) | `cakectl plugins credentials set bakery --credential-type bakery_monitor_hmac --payload-file ...` |
| Live connection test | Plugins → scheduled task **Run now** on `plugin-health-check:bakery` | `cakectl plugins test-connection bakery` |

The UI does not call `/test-connection` directly. Running the bakery health
scheduled task is the same operator action: it submits a health-check order
against the saved adapter state.

## Verify

```bash
kubectl -n <poundcake-namespace> exec deploy/poundcake-api -- printenv | grep '^POUNDCAKE_BAKERY_'
cakectl --url https://poundcake.example.com plugins show bakery
cakectl --url https://poundcake.example.com plugins health bakery
```

Expected runtime shape:

- `POUNDCAKE_BAKERY_ENABLED=true`
- `POUNDCAKE_BAKERY_BASE_URL=https://bakery.example.com`
- `POUNDCAKE_BAKERY_MONITOR_ID=<explicit monitor id or namespace/release>`
- `POUNDCAKE_BAKERY_BOOTSTRAP_HMAC_KEY_ID=<bootstrap key id>`
- `POUNDCAKE_BAKERY_ACCOUNT_NUMBER` set when Core tickets should use a default account

The bakery plugin should move from `initializing` to `healthy` after API
startup registration or a bakery health-check order succeeds. The Plugins UI
and `cakectl plugins health bakery` both read that stored registry state.

## Plugin Bootstrap And Health

When PoundCake starts, the enabled bakery plugin still registers:

- a `bakery` plugin row in `service_plugins`
- a `bakery-health-check` ingredient
- a `bakery-comms` communication ingredient
- a `plugin-health-check:bakery` recipe
- a `plugin-health-check:bakery` scheduled task
- a default Bakery communication route for the active provider

Dishwasher injects the due Bakery health task as an order. That order follows
the same workflow as every other PoundCake order.

## Troubleshooting

If the Bakery plugin does not become healthy:

- confirm `bakery.client.enabled=true` and `bakery.client.baseUrl` is HTTPS
- confirm the bootstrap Secret exists in the PoundCake namespace and uses
  `bootstrap-key-id` / `bootstrap-key`
- confirm the Secret's monitor ID matches `bakery.client.monitor.id` or
  `<namespace>/<release>`
- confirm Bakery has a bootstrap credential for that same monitor ID
- check `poundcake-api` logs for Bakery monitor registration errors
- check Plugins or `cakectl plugins health bakery` for `health_message` and
  `health_error_code`

If communication actions fail but health checks pass:

- confirm `bakery.client.accountNumber` is set when Core tickets need a default
  account
- confirm the Bakery communication route destination matches a provider
  configured in Bakery
- confirm Bakery provider credentials are valid
- inspect the order timeline for the failing `bakery-comms` `dish_ingredient`
