# Bootstrap Recipes

This directory is the local bootstrap recipe catalog location used by Dishwasher.

PoundCake now recreates recipe catalog files here during bootstrap and periodic remote sync,
so shared bootstrap recipes are no longer meant to be source controlled in this repo.

You can still place cluster-specific recipe catalog files here outside version control when a
cluster needs local-only bootstrap recipes or per-cluster entities that should not be committed
back to the PoundCake repo.

Recommended usage:

- Treat generated files here as runtime or environment-specific state.
- Add local-only `.yaml` or `.yml` recipe catalog files here through a mount, config-management
  tool, or untracked file when needed for a specific cluster.
- Do not rely on repo-tracked recipe files living here long term.

Non-YAML files in this directory are ignored by the recipe loader.
