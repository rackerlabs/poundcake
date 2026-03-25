# Bootstrap Ingredients

This directory holds source-controlled bootstrap ingredient catalogs and may also hold
cluster-specific ingredient catalog files that are kept outside version control.

Use this location when a cluster needs extra bootstrap ingredients that should not be
committed back to the PoundCake repo. The Dishwasher bootstrap ingredient loader scans this
directory recursively for `.yaml` and `.yml` files.

Recommended usage:

- Keep shared/default ingredient catalogs in version control.
- Place per-cluster ingredient catalog files here via a local mount, config-management tool,
  or untracked file.
- Use this for cluster-specific entities, destinations, or provider wiring that should stay
  local to that environment.

Non-YAML files in this directory are ignored by the loader.
