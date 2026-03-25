# poundcake Helm Chart

This chart deploys PoundCake, its UI, and the StackStorm components it depends on.

## Key Points

- The chart no longer renders any in-cluster Bakery resources.
- Remote Bakery is configured only through `bakery.client.*` values.
- If `bakery.client.enabled=true`, `bakery.client.baseUrl` must be set.
- Bakery itself is deployed from the standalone
  [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.

## Install

```bash
helm upgrade --install poundcake ./helm \
  --set poundcakeImage.repository=<your-repo/poundcake> \
  --set poundcakeImage.tag=<tag>
```

## Remote Bakery

```yaml
bakery:
  config:
    activeProvider: rackspace_core
  client:
    enabled: true
    enforceRemoteBaseUrl: true
    baseUrl: https://bakery.example.com
    auth:
      existingSecret: bakery-hmac
```

## Installer

Use the repo wrapper for PoundCake:

```bash
./install/install-poundcake-helm.sh
```

Use the standalone Bakery repo for Bakery installs.
