# Helm Scripts

Place Helm-specific helper scripts in this directory.

Example use cases:
- chart validation helpers
- value-generation helpers
- release/packaging helpers

Current scripts:
- `common-functions.sh`: shared install helpers (preflight, overrides, validation, rotation).
- `startup-gate-runbook.sh`: collects startup gate evidence for `poundcake-api` init delays and outputs a timeline/classification summary.
