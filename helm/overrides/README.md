# Helm Override Examples

This directory contains sanitized PoundCake-side override examples.

## Included Examples

- `remote-bakery-overrides.yaml`
  Use this when PoundCake should talk to a separately deployed Bakery instance.
- `ghcr-pull-secret-overrides.yaml`
  Reference an existing registry pull secret.
- `gateway-shared-hostname-overrides.yaml`
  Publish PoundCake through Gateway API on a shared hostname.
- `ha-overrides.yaml`
  Scale the PoundCake workers for a basic HA footprint.
- `poundcake-only-overrides.yaml`
  Minimal PoundCake-only example values.

Bakery-only and co-located Bakery examples were removed because Bakery is now deployed from the
standalone [rackerlabs/bakery](https://github.com/rackerlabs/bakery) repo.
