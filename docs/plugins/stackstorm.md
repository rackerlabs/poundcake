# StackStorm Plugin

## Status

- Service type: `stackstorm`
- Tier: `supported`
- External service: StackStorm

## Purpose

`stackstorm` executes StackStorm actions and workflows from PoundCake orders and
syncs PoundCake-owned StackStorm content.

In the provider-neutral capability model, StackStorm is intended for workflow
orchestration and pack-owned automations, not as a duplicate home for every
native single-step Kubernetes mutation that PoundCake already exposes through
the `k8s` plugin.

## Requirements

- A reachable StackStorm API endpoint.
- StackStorm content installed or synced for PoundCake-owned actions.
- A StackStorm API key or auth token stored through the credential-manager
  boundary.

## Credentials

The required credential is:

- `credential_type=stackstorm_api_key`
- `credential_key_id=default`

Credential payloads may include `api_key`, `st2_api_key`, or `auth_token`.

## Operator configuration

Helm is the durable way to point PoundCake at StackStorm. Setting `stackstorm.url`
appends `stackstorm` to `enabledPlugins` automatically (same pattern as Bakery):

```yaml
stackstorm:
  url: http://stackstorm-api.stackstorm.svc.cluster.local:9101
  verifySsl: false
```

The operator config stored on the plugin still requires:

- `url`: StackStorm API URL
- `verify_ssl`: whether PoundCake verifies the StackStorm API certificate

The StackStorm API key is **not** imported from environment variables. After
deploy, an admin sets `stackstorm_api_key` in Plugins or:

```bash
cakectl plugins credentials set stackstorm \
  --credential-type stackstorm_api_key \
  --payload-json '{"api_key":"<st2-api-key>"}'
```

Live health: Plugins → **Run now** on `plugin-health-check:stackstorm`, or
`cakectl plugins test-connection stackstorm`.

## Install StackStorm and connect PoundCake

StackStorm is a **separate Helm release** from PoundCake (`rackerlabs/poundcake-stackstorm`).
PoundCake does not start ST2 for you.

The short path that was verified in lab:

1. Install StackStorm into namespace `stackstorm`:

```bash
git clone git@github.com:rackerlabs/poundcake-stackstorm.git /opt/poundcake-stackstorm
cd /opt/poundcake-stackstorm
./bin/install-poundcake-stackstorm.sh
```

Wait until `stackstorm-bootstrap` is `Complete` and `stackstorm-api` is `1/1 Running`.
The bootstrap job writes secret `stackstorm-apikeys` with key `st2_api_key`.

2. Point PoundCake at that API. Setting `stackstorm.url` appends `stackstorm` to
`enabledPlugins`:

```yaml
stackstorm:
  url: http://stackstorm-api.stackstorm.svc.cluster.local:9101
  verifySsl: false
```

Apply with the PoundCake installer (same override directory as other PoundCake
values). In-cluster HTTP is allowed; use HTTPS plus `verifySsl: true` when the
API is remote.

3. After PoundCake rolls, import the ST2 API key. The plugin will not read it
from environment variables. From a host with `kubectl` to both namespaces:

```bash
POUNDCAKE_NAMESPACE=rackspace \
STACKSTORM_NAMESPACE=stackstorm \
  ./helm/devstack/configure-stackstorm-adapter.sh
```

Or set the key yourself (admin):

```bash
cakectl plugins credentials set stackstorm \
  --credential-type stackstorm_api_key \
  --payload-json '{"api_key":"<st2-api-key>"}'
cakectl plugins test-connection stackstorm
```

Expected result: Plugins shows `stackstorm` as `supported`, `healthy`,
`credential_status=ready`. A recipe step with `service_type=stackstorm` and
`service_exec=action_execution` can run pack actions such as `core.local`.

## Enabled behavior

- `health_check`
- `action_execution`
- `workflow_execution`
- `content_sync`

`content_sync` runs as a normal service-execution ingredient/order. The plugin
router does not expose a direct StackStorm content-sync action. The sync
implementation lives in `api/plugins/stackstorm/content_sync.py`, matching the
standard adapter layout for plugin-owned recurring import/sync work.

## Payload contracts

Operation-level `payload_schema` validation is authoritative. Invalid payloads
are rejected before adapter execution.

- `action_execution.execute_action` requires `action_ref` and accepts optional
  object `parameters`.
- `workflow_execution.execute_workflow` requires `workflow_ref` and accepts
  optional object `inputs`.
- `content_sync.sync_content` and `health_check` accept no payload fields.

## Devstack

The devstack installs StackStorm from
`https://github.com/rackerlabs/poundcake-stackstorm` into the `stackstorm`
namespace when `INSTALL_STACKSTORM=true`.
