# Configuration And Command Reference

This document is the consolidated reference for PoundCake configuration surfaces.

It covers:

- Helm chart values from [helm/values.yaml](/Users/aedan/Documents/GitHub/poundcake/helm/values.yaml)
- installer wrappers and their flags/env vars
- the optional environment helper
- the PoundCake CLI global options and command tree

This is a reference, not a deployment walkthrough. For guided operator flows, use:

- [DEPLOY.md](/Users/aedan/Documents/GitHub/poundcake/docs/DEPLOY.md)
- [REMOTE_BAKERY_DEPLOYMENT_GUIDE.md](/Users/aedan/Documents/GitHub/poundcake/docs/REMOTE_BAKERY_DEPLOYMENT_GUIDE.md)
- [AUTH.md](/Users/aedan/Documents/GitHub/poundcake/docs/AUTH.md)
- [CLI.md](/Users/aedan/Documents/GitHub/poundcake/docs/CLI.md)

## Assumptions

This reference assumes the supported Genestack deployment model:

- chart versions come from `/etc/genestack/helm-chart-versions.yaml`
- live PoundCake overrides live under `/etc/genestack/helm-configs/poundcake/`
- live global overrides live under `/etc/genestack/helm-configs/global_overrides/`
- the canonical entry points are `./install/install-poundcake-helm.sh` and `./install/install-bakery-helm.sh`

Recommended live override layout:

- `00-pull-secret-overrides.yaml`
- `10-main-overrides.yaml`
- `20-auth-overrides.yaml`
- `30-git-sync-overrides.yaml`

## Override Precedence

The PoundCake installer builds Helm input in this order:

1. Chart defaults from [helm/values.yaml](/Users/aedan/Documents/GitHub/poundcake/helm/values.yaml)
2. `POUNDCAKE_BASE_OVERRIDES` if the file exists
3. all `*.yaml` files in `POUNDCAKE_GLOBAL_OVERRIDES_DIR`, sorted
4. all `*.yaml` files in `POUNDCAKE_SERVICE_CONFIG_DIR`, sorted
5. installer-injected profile flags
6. any extra Helm arguments passed through the installer

Practical consequences:

- put persistent runtime config in YAML files, not in installer env vars
- use `00-*`, `10-*`, `20-*`, `30-*` file prefixes if you need deterministic override order
- the PoundCake installer injects `poundcake.enabled=true` and `bakery.enabled=false`
- the Bakery installer injects `poundcake.enabled=false`, `bakery.enabled=true`, `bakery.worker.enabled=true`, and `bakery.database.createServer=true`

## Install Entry Points

Supported wrappers:

- [install/install-poundcake-helm.sh](/Users/aedan/Documents/GitHub/poundcake/install/install-poundcake-helm.sh)
- [install/install-bakery-helm.sh](/Users/aedan/Documents/GitHub/poundcake/install/install-bakery-helm.sh)

Canonical scripts:

- [helm/bin/install-poundcake.sh](/Users/aedan/Documents/GitHub/poundcake/helm/bin/install-poundcake.sh)
- [helm/bin/install-bakery.sh](/Users/aedan/Documents/GitHub/poundcake/helm/bin/install-bakery.sh)

Optional helper:

- [install/set-env-helper.sh](/Users/aedan/Documents/GitHub/poundcake/install/set-env-helper.sh)

## PoundCake Installer

Installer flags:

| Flag | Purpose |
|---|---|
| `--debug` | Enable shell tracing for the install run. |
| `--validate` | Run `helm lint` and `helm template --debug` before install. |
| `--operators-mode <install-missing\|verify\|skip>` | Control whether dependency operators are installed, only verified, or skipped. |
| `--verify-operators` | Shortcut for `--operators-mode verify`. |
| `--skip-operators` | Shortcut for `--operators-mode skip`. |
| `--skip-preflight` | Skip dependency and cluster-connectivity checks. |
| `--rotate-secrets` | Delete selected chart-managed secrets before install. |

Release, chart, and override discovery env vars:

| Variable | Default | Purpose |
|---|---|---|
| `POUNDCAKE_RELEASE_NAME` | `poundcake` | Helm release name. |
| `POUNDCAKE_NAMESPACE` | `rackspace` | Target namespace. |
| `POUNDCAKE_HELM_TIMEOUT` | `120m` | Helm timeout. |
| `POUNDCAKE_CHART_REPO` | unset | Chart source override, usually `oci://...` when not using the local `./helm` chart. |
| `POUNDCAKE_CHART_VERSION` | unset | Explicit chart version, mainly for OCI installs. |
| `POUNDCAKE_VERSION_FILE` | unset | Explicit chart version file path. The installer also falls back to `/etc/genestack/helm-chart-version.yaml` and `/etc/genestack/helm-chart-versions.yaml`. |
| `POUNDCAKE_BASE_OVERRIDES` | `/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml` | Optional base values file. |
| `POUNDCAKE_GLOBAL_OVERRIDES_DIR` | `/etc/genestack/helm-configs/global_overrides` | Global values directory. |
| `POUNDCAKE_SERVICE_CONFIG_DIR` | `/etc/genestack/helm-configs/poundcake` | PoundCake service values directory. |
| `POUNDCAKE_HELM_POST_RENDERER` | `/etc/genestack/kustomize/kustomize.sh` | Optional post-renderer. |
| `POUNDCAKE_HELM_POST_RENDERER_ARGS` | `poundcake/overlay` | Post-renderer args. |
| `POUNDCAKE_HELM_POST_RENDERER_OVERLAY_DIR` | `/etc/genestack/kustomize/poundcake/overlay` | Guard used before enabling the post-renderer. |

Behavior env vars:

| Variable | Default | Purpose |
|---|---|---|
| `POUNDCAKE_INSTALL_DEBUG` | `false` | Same effect as `--debug`. |
| `POUNDCAKE_HELM_VALIDATE` | `false` | Same effect as `--validate`. |
| `POUNDCAKE_OPERATORS_MODE` | `install-missing` | Default operator-handling mode. |
| `POUNDCAKE_HELM_WAIT` | `false` | Adds `--wait` to Helm when explicitly enabled. |
| `POUNDCAKE_ALLOW_HOOK_WAIT` | `false` | Required if you intentionally force `--wait` or `--atomic`. |
| `POUNDCAKE_HELM_ATOMIC` | `false` | Adds `--atomic` to Helm when explicitly enabled. |
| `POUNDCAKE_HELM_CLEANUP_ON_FAIL` | `false` | Adds `--cleanup-on-fail` to Helm when explicitly enabled. |

Registry and pull-secret env vars:

| Variable | Default | Purpose |
|---|---|---|
| `HELM_REGISTRY_USERNAME` | unset | Helm OCI login username and image pull-secret username when private GHCR is used. |
| `HELM_REGISTRY_PASSWORD` | unset | Helm OCI login password/token and image pull-secret password when private GHCR is used. |
| `POUNDCAKE_IMAGE_PULL_SECRET_NAME` | `ghcr-creds` | Pull-secret name created or reused by the installer. |
| `POUNDCAKE_CREATE_IMAGE_PULL_SECRET` | `true` | Whether the installer should create or update the Docker registry secret. |
| `POUNDCAKE_IMAGE_PULL_SECRET_EMAIL` | `noreply@local` | Email field for the generated docker-registry secret. |

Dependency operator env vars:

- MariaDB:
  - `POUNDCAKE_MARIADB_OPERATOR_RELEASE_NAME=mariadb-operator`
  - `POUNDCAKE_MARIADB_OPERATOR_CRDS_RELEASE_NAME=mariadb-operator-crds`
  - `POUNDCAKE_MARIADB_OPERATOR_NAMESPACE=mariadb-system`
  - `POUNDCAKE_MARIADB_OPERATOR_CRDS_CHART_NAME=mariadb-operator-crds`
  - `POUNDCAKE_MARIADB_OPERATOR_CHART_NAME=mariadb-operator`
  - `POUNDCAKE_MARIADB_OPERATOR_CHART_REPO_URL=https://helm.mariadb.com/mariadb-operator`
  - `POUNDCAKE_MARIADB_OPERATOR_CHART_VERSION=0.38.1`
- Redis:
  - `POUNDCAKE_REDIS_OPERATOR_RELEASE_NAME=redis-operator`
  - `POUNDCAKE_REDIS_OPERATOR_NAMESPACE=redis-systems`
  - `POUNDCAKE_REDIS_OPERATOR_CHART_NAME=redis-operator`
  - `POUNDCAKE_REDIS_OPERATOR_CHART_REPO_URL=https://ot-container-kit.github.io/helm-charts`
  - `POUNDCAKE_REDIS_OPERATOR_CHART_VERSION=0.22.1`
- RabbitMQ:
  - `POUNDCAKE_RABBITMQ_OPERATOR_NAMESPACE=rabbitmq-system`
  - `POUNDCAKE_RABBITMQ_CLUSTER_OPERATOR_MANIFEST_URL=https://github.com/rabbitmq/cluster-operator/releases/download/v2.12.0/cluster-operator.yml`
  - `POUNDCAKE_RABBITMQ_TOPOLOGY_OPERATOR_MANIFEST_URL=https://github.com/rabbitmq/messaging-topology-operator/releases/download/v1.15.0/messaging-topology-operator-with-certmanager.yaml`
- MongoDB:
  - `POUNDCAKE_MONGODB_OPERATOR_RELEASE_NAME=mongodb-community-operator`
  - `POUNDCAKE_MONGODB_OPERATOR_NAMESPACE=mongodb-system`
  - `POUNDCAKE_MONGODB_OPERATOR_CHART_NAME=community-operator`
  - `POUNDCAKE_MONGODB_OPERATOR_CHART_REPO_URL=https://mongodb.github.io/helm-charts`
  - `POUNDCAKE_MONGODB_OPERATOR_CHART_VERSION=0.13.0`

Important PoundCake installer guardrails:

- image repositories, tags, digests, remote Bakery settings, shared DB settings, StackStorm pack sync, and `poundcakeImage.pullSecrets` must come from values files
- the installer rejects old image env vars such as `POUNDCAKE_IMAGE_TAG`, `POUNDCAKE_UI_IMAGE_TAG`, and `POUNDCAKE_BAKERY_IMAGE_TAG`
- the installer rejects old remote Bakery env vars such as `POUNDCAKE_REMOTE_BAKERY_*`
- the installer rejects old shared DB env vars such as `POUNDCAKE_SHARED_DB_*`
- the installer rejects old pack-sync env vars such as `POUNDCAKE_PACK_SYNC_ENDPOINT`
- `--wait` and `--atomic` are guarded because startup hooks can deadlock when Helm waits for resources before creating the hook jobs

## Bakery Installer

The Bakery installer manages provider secrets, Bakery HMAC auth, and then delegates the chart install to the PoundCake installer in bakery-only mode.

Common Bakery installer behavior:

- default release name: `bakery`
- default namespace: inherits `POUNDCAKE_NAMESPACE` or falls back to `rackspace`
- default active provider: `rackspace_core`
- provider secrets are reused if they already exist
- missing provider credentials trigger an interactive prompt when stdin is a TTY
- existing provider secrets are only updated when `--update-bakery-secret` or `POUNDCAKE_UPDATE_BAKERY_SECRET=true` is used
- the Bakery HMAC auth secret is auto-created in the target namespace when missing

Provider and secret inputs:

| Provider / purpose | Active provider value | Secret-name flag and env | Credential flags and env |
|---|---|---|---|
| Rackspace Core | `rackspace_core` | `--bakery-rackspace-secret-name` / `POUNDCAKE_BAKERY_RACKSPACE_SECRET_NAME` default `bakery-rackspace-core` | `--bakery-rackspace-url`, `--bakery-rackspace-username`, `--bakery-rackspace-password` with matching `POUNDCAKE_BAKERY_RACKSPACE_*` env vars |
| ServiceNow | `servicenow` | `--bakery-servicenow-secret-name` / `POUNDCAKE_BAKERY_SERVICENOW_SECRET_NAME` default `bakery-servicenow` | `--bakery-servicenow-url`, `--bakery-servicenow-username`, `--bakery-servicenow-password` with matching `POUNDCAKE_BAKERY_SERVICENOW_*` env vars |
| Jira | `jira` | `--bakery-jira-secret-name` / `POUNDCAKE_BAKERY_JIRA_SECRET_NAME` default `bakery-jira` | `--bakery-jira-url`, `--bakery-jira-username`, `--bakery-jira-api-token` with matching `POUNDCAKE_BAKERY_JIRA_*` env vars |
| GitHub | `github` | `--bakery-github-secret-name` / `POUNDCAKE_BAKERY_GITHUB_SECRET_NAME` default `bakery-github` | `--bakery-github-token` with `POUNDCAKE_BAKERY_GITHUB_TOKEN` |
| PagerDuty | `pagerduty` | `--bakery-pagerduty-secret-name` / `POUNDCAKE_BAKERY_PAGERDUTY_SECRET_NAME` default `bakery-pagerduty` | `--bakery-pagerduty-api-key` with `POUNDCAKE_BAKERY_PAGERDUTY_API_KEY` |
| Teams | `teams` | `--bakery-teams-secret-name` / `POUNDCAKE_BAKERY_TEAMS_SECRET_NAME` default `bakery-teams` | `--bakery-teams-webhook-url` with `POUNDCAKE_BAKERY_TEAMS_WEBHOOK_URL` |
| Discord | `discord` | `--bakery-discord-secret-name` / `POUNDCAKE_BAKERY_DISCORD_SECRET_NAME` default `bakery-discord` | `--bakery-discord-webhook-url` with `POUNDCAKE_BAKERY_DISCORD_WEBHOOK_URL` |
| Shared Bakery HMAC auth | not provider-specific | `--bakery-auth-secret-name` / `POUNDCAKE_BAKERY_AUTH_SECRET_NAME` default release-derived | optional HMAC env vars: `POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY_ID`, `POUNDCAKE_BAKERY_HMAC_ACTIVE_KEY`, `POUNDCAKE_BAKERY_HMAC_NEXT_KEY_ID`, `POUNDCAKE_BAKERY_HMAC_NEXT_KEY` |

Shared Bakery installer toggles:

| Flag / env | Default | Purpose |
|---|---|---|
| `--bakery-active-provider` / `POUNDCAKE_BAKERY_ACTIVE_PROVIDER` | `rackspace_core` | Active provider value written into the install when you override the default. |
| `--update-bakery-secret` / `POUNDCAKE_UPDATE_BAKERY_SECRET` | `false` | Allow secret updates when the secret already exists. |
| `--namespace` / `-n` | inherited | Forwarded namespace override. |

Bakery installer guardrails:

- `install-bakery.sh` rejects `--mode`, `--no-local-bakery`, and `--enable-bakery`
- `install-bakery.sh` rejects `bakery.database.createServer=false`
- `install-bakery.sh` rejects `bakery.enabled=false`
- `install-bakery.sh` rejects `poundcake.enabled=true`
- old Bakery DB env vars such as `POUNDCAKE_BAKERY_DB_INTEGRATED`, `POUNDCAKE_BAKERY_DB_HOST`, `POUNDCAKE_BAKERY_DB_NAME`, and `POUNDCAKE_BAKERY_DB_USER` are not supported

## Optional Environment Helper

[install/set-env-helper.sh](/Users/aedan/Documents/GitHub/poundcake/install/set-env-helper.sh) is optional.

What it does:

- exports common fork/GHCR convenience vars
- leaves image refs and app runtime config in values files
- sets defaults for chart source, namespace, timeouts, override directories, and post-renderer paths

What it does not do:

- it does not configure remote Bakery
- it does not configure shared DB mode
- it does not set image tags
- it does not populate provider credentials

## CLI Reference

Global options:

| Option | Env var | Default | Purpose |
|---|---|---|---|
| `--url`, `-u` | `POUNDCAKE_URL` | `http://localhost:8080` | PoundCake API URL. |
| `--api-key`, `-k` | `POUNDCAKE_API_KEY` | unset | API key for authenticated service access. |
| `--format`, `-f` | none | `table` | Output format: `json`, `yaml`, or `table`. |
| `--verbose`, `-v` | none | `false` | Enable verbose CLI output. |

Command inventory:

| Command | Purpose | Parameters |
|---|---|---|
| `auth providers` | List enabled auth providers. | `none` |
| `auth me` | Show the current authenticated principal. | `none` |
| `auth login` | Log in and persist the session locally. | `--provider, --username, --password` |
| `auth logout` | Clear the local session and attempt remote logout. | `none` |
| `auth principals list` | List observed principals available for user-specific bindings. | `--provider, --search, --limit, --offset` |
| `auth bindings list` | List current role bindings. | `--provider` |
| `auth bindings create` | Create a role binding. | `--provider, --type, --role, --group, --principal-id` |
| `auth bindings update` | Update a role binding. | `<binding_id>, --role, --group` |
| `auth bindings delete` | Delete a role binding. | `<binding_id>` |
| `overview` | Show the monitoring overview dashboard in the CLI. | `--activity-limit, --incident-limit, --communication-limit, --suppression-limit` |
| `incidents list` | List incidents. | `--processing-status, --alert-status, --alert-group-name, --req-id, --search, --limit, --offset` |
| `incidents get` | Get one incident. | `<incident_id>` |
| `incidents timeline` | Show timeline events for an incident. | `<incident_id>` |
| `incidents watch` | Continuously refresh the incident list. | `--processing-status, --alert-status, --alert-group-name, --req-id, --search, --limit, --offset, --interval, --once` |
| `communications list` | List communication activity. | `--status, --channel, --search, --limit, --offset` |
| `communications get` | Get one communication activity record by id. | `<communication_id>` |
| `suppressions list` | List suppressions. | `--status, --enabled/--disabled, --scope, --limit, --offset` |
| `suppressions get` | Get one suppression. | `<suppression_id>` |
| `suppressions create` | Create a suppression window. | `--name, --starts-at, --ends-at, --scope, --reason, --created-by, --summary-ticket-enabled/--summary-ticket-disabled, --matcher-key, --matcher-operator, --matcher-value, --matcher-json` |
| `suppressions cancel` | Cancel a suppression window. | `<suppression_id>` |
| `activity list` | List workflow execution activity. | `--processing-status, --req-id, --order-id, --execution-ref, --phase, --search, --limit, --offset` |
| `activity get` | Get one workflow run by id. | `<dish_id>` |
| `alert-rules list` | List alert rules. | `none` |
| `alert-rules get` | Get one alert rule. | `<source_name>, <group_name>, <rule_name>` |
| `alert-rules create` | Create an alert rule. | `<source_name>, <group_name>, <rule_name>, --file, --expr, --for, --severity, --summary, --description, --labels-json, --annotations-json` |
| `alert-rules update` | Update an alert rule. | `<source_name>, <group_name>, <rule_name>, --file, --expr, --for, --severity, --summary, --description, --labels-json, --annotations-json` |
| `alert-rules delete` | Delete an alert rule. | `<source_name>, <group_name>, <rule_name>, --yes` |
| `alert-rules apply` | Apply all rules from a Prometheus rule-group file. | `<file>, --source-name, --dry-run` |
| `global-communications get` | Get the global communications policy. | `none` |
| `global-communications set` | Set the global communications policy. | `--file, --route-json` |
| `workflows list` | List workflows. | `--name, --enabled, --disabled, --limit, --offset` |
| `workflows get` | Get one workflow. | `<workflow_id>` |
| `workflows create` | Create a workflow. | `--file, --name, --description, --enabled, --disabled, --clear-timeout-sec, --communications-mode, --step-json, --route-json` |
| `workflows update` | Update a workflow. | `<workflow_id>, --file, --name, --description, --enabled, --disabled, --clear-timeout-sec, --communications-mode, --step-json, --route-json` |
| `workflows delete` | Delete a workflow. | `<workflow_id>, --yes` |
| `actions list` | List actions. | `--execution-target, --task-key-template, --search, --limit, --offset` |
| `actions get` | Get one action. | `<action_id>` |
| `actions create` | Create an action. | `--template, --execution-target, --destination-target, --task-key-template, --execution-engine, --execution-purpose, --execution-id, --is-default/--not-default, --is-blocking/--non-blocking, --expected-duration-sec, --timeout-duration-sec, --retry-count, --retry-delay, --on-failure, --payload-json, --parameters-json` |
| `actions update` | Update an action. | `<action_id>, --template, --execution-target, --destination-target, --task-key-template, --execution-engine, --execution-purpose, --execution-id, --is-default/--not-default, --is-blocking/--non-blocking, --expected-duration-sec, --timeout-duration-sec, --retry-count, --retry-delay, --on-failure, --payload-json, --parameters-json` |
| `actions delete` | Delete an action. | `<action_id>, --yes` |

Legacy aliases:

- `orders` -> `incidents`
- `rules` -> `alert-rules`
- `recipes` -> `workflows`
- `ingredients` -> `actions`

## Helm Values Reference

High-impact sections and where they usually belong:

| Value path | Typical live file | What it controls |
|---|---|---|
| `poundcakeImage.pullSecrets` | `00-pull-secret-overrides.yaml` | Pull-secret references for PoundCake and Bakery workloads that use PoundCake-managed images. |
| `gateway.*` | `10-main-overrides.yaml` | PoundCake Gateway API publication, hostnames, listener, and path-prefix behavior. |
| `bakery.gateway.*` | `10-main-overrides.yaml` | Bakery Gateway API publication for split installs. |
| `bakery.client.*` | `10-main-overrides.yaml` | PoundCake remote Bakery client behavior, base URL, auth secret reference, and retries. |
| `database.*` | `10-main-overrides.yaml` | PoundCake DB mode, shared operator server, or external DB secret. |
| `bakery.database.*` | `10-main-overrides.yaml` | Bakery DB contract and Bakery-owned MariaDB settings. |
| `bakery.config.*` | `10-main-overrides.yaml` | Bakery active provider, dry-run mode, and worker behavior. |
| `bakery.<provider>.existingSecret` | `10-main-overrides.yaml` | Secret references for Rackspace Core, ServiceNow, Jira, GitHub, PagerDuty, Teams, and Discord. |
| `bakery.auth.*` | `10-main-overrides.yaml` | Bakery server-side HMAC auth settings. |
| `auth.*` | `20-auth-overrides.yaml` | Local, Active Directory, Auth0, and Azure AD provider enablement and non-secret settings. |
| `git.*` | `30-git-sync-overrides.yaml` | Git sync enablement, repo URL, paths, provider, and secret references. |
| `service.*`, `services.*`, `ingress.*` | `10-main-overrides.yaml` | Service exposure and optional ingress. |
| `config.*`, `suppressions.*`, `prometheus.*`, `serviceMonitor.*` | `10-main-overrides.yaml` | API runtime tuning, suppression lifecycle, Prometheus integration, and ServiceMonitor settings. |
| `chef.*`, `prepChef.*`, `timer.*`, `dishwasher.*`, `intervals.*` | `10-main-overrides.yaml` | Worker toggles, resource sizing, and polling intervals. |
| `stackstorm.*`, `stackstormComponents.*`, `stackstormServices.*`, `stackstormPackSync.*` | `10-main-overrides.yaml` | StackStorm connectivity, optional component toggles, and pack-sync behavior. |
| `nodeSelector`, `tolerations`, `affinity`, `resources`, `defaultResources`, `pdb`, `podDisruptionBudget` | `10-main-overrides.yaml` | Placement, resilience, and resource tuning. |
| `podSecurityContext`, `securityContext`, `utilitySecurityContext`, `infraSecurityContext` | `10-main-overrides.yaml` | Security contexts for API, UI, workers, startup hooks, and infra. |
| `redis.*`, `rabbitmq.*`, `mongodb.*`, `persistence.*`, `mariadbOperator.*`, `secrets.*` | `10-main-overrides.yaml` | Dependency deployment modes, persistence sizing, operator-created DB resources, and chart-managed secret inputs. |

Secret-backed value sections to pay attention to:

- `git.existingSecret`
- `auth.activeDirectory.existingSecret`
- `auth.activeDirectory.caBundle.existingSecret`
- `auth.auth0.ui.existingSecret`
- `auth.auth0.cli.existingSecret`
- `auth.azureAd.ui.existingSecret`
- `database.existingSecret`
- `redis.external.existingSecret`
- `redis.existingSecret`
- `rabbitmq.existingSecret`
- `mongodb.existingSecret`
- `bakery.auth.existingSecret`
- `bakery.client.auth.existingSecret`
- `bakery.servicenow.existingSecret`
- `bakery.jira.existingSecret`
- `bakery.github.existingSecret`
- `bakery.pagerduty.existingSecret`
- `bakery.teams.existingSecret`
- `bakery.discord.existingSecret`
- `bakery.rackspaceCore.existingSecret`

Current complete top-level inventory from [helm/values.yaml](/Users/aedan/Documents/GitHub/poundcake/helm/values.yaml):

| Top-level key | Immediate child keys |
|---|---|
| `replicaCount` | default: `1` |
| `poundcake` | `poundcake.enabled` |
| `nameOverride` | default: `''` |
| `fullnameOverride` | default: `''` |
| `serviceAccount` | `serviceAccount.create`, `serviceAccount.annotations`, `serviceAccount.name` |
| `podAnnotations` |  |
| `podSecurityContext` | `podSecurityContext.fsGroup`, `podSecurityContext.runAsNonRoot`, `podSecurityContext.seccompProfile` |
| `securityContext` | `securityContext.capabilities`, `securityContext.readOnlyRootFilesystem`, `securityContext.runAsNonRoot`, `securityContext.runAsUser` |
| `service` | `service.type`, `service.port` |
| `ui` | `ui.enabled`, `ui.service`, `ui.resources` |
| `ingress` | `ingress.enabled`, `ingress.className`, `ingress.annotations`, `ingress.hosts`, `ingress.tls` |
| `gateway` | `gateway.enabled`, `gateway.gatewayName`, `gateway.gatewayNamespace`, `gateway.listener`, `gateway.hostnames`, `gateway.annotations`, `gateway.className`, `gateway.name`, `gateway.listeners`, `gateway.sessionPersistence` |
| `resources` | `resources.limits`, `resources.requests` |
| `autoscaling` | `autoscaling.enabled`, `autoscaling.minReplicas`, `autoscaling.maxReplicas`, `autoscaling.targetCPUUtilizationPercentage` |
| `nodeSelector` | `nodeSelector.node-role.kubernetes.io/worker` |
| `tolerations` | default: `[]` |
| `affinity` |  |
| `config` | `config.host`, `config.port`, `config.debug`, `config.logLevel`, `config.logFormat`, `config.metricsEnabled`, `config.metricsPath`, `config.defaultTimeout`, `config.maxConcurrentRemediations` |
| `suppressions` | `suppressions.enabled`, `suppressions.lifecycleEnabled`, `suppressions.lifecycleIntervalSeconds`, `suppressions.lifecycleBatchLimit` |
| `stackstorm` | `stackstorm.releaseName`, `stackstorm.url`, `stackstorm.authUrl`, `stackstorm.verifySsl`, `stackstorm.apiKeySecretName`, `stackstorm.apiKeySecretKey`, `stackstorm.autoDiscover`, `stackstorm.discoverAcrossNamespaces`, `stackstorm.adminUser`, `stackstorm.adminPassword`, `stackstorm.adminPasswordSecret`, `stackstorm.adminPasswordSecretKey`, `stackstorm.resourceNames` |
| `redis` | `redis.enabled`, `redis.deploy`, `redis.external`, `redis.image`, `redis.password`, `redis.existingSecret`, `redis.secretKey`, `redis.auth`, `redis.persistence`, `redis.resources`, `redis.metrics`, `redis.alertTtlHours`, `redis.lockTimeoutSeconds` |
| `rabbitmq` | `rabbitmq.enabled`, `rabbitmq.external`, `rabbitmq.existingSecret`, `rabbitmq.secretKeys`, `rabbitmq.host`, `rabbitmq.port`, `rabbitmq.username`, `rabbitmq.password`, `rabbitmq.vhost`, `rabbitmq.replicas`, `rabbitmq.auth`, `rabbitmq.persistence`, `rabbitmq.service`, `rabbitmq.resources` |
| `mappings` | `mappings.common.yaml` |
| `serviceMonitor` | `serviceMonitor.enabled`, `serviceMonitor.namespace`, `serviceMonitor.interval`, `serviceMonitor.scrapeTimeout`, `serviceMonitor.labels` |
| `podDisruptionBudget` | `podDisruptionBudget.enabled`, `podDisruptionBudget.minAvailable` |
| `persistence` | `persistence.enabled`, `persistence.storageClass`, `persistence.accessMode`, `persistence.size`, `persistence.storageClassName`, `persistence.mariadb`, `persistence.mongo`, `persistence.rabbitmq`, `persistence.redis`, `persistence.config` |
| `prometheus` | `prometheus.url`, `prometheus.verifySsl`, `prometheus.useCrds`, `prometheus.crdNamespace`, `prometheus.allowRuleManagement`, `prometheus.crdLabels` |
| `git` | `git.enabled`, `git.repoUrl`, `git.branch`, `git.rulesPath`, `git.workflowsPath`, `git.actionsPath`, `git.filePerAlert`, `git.filePattern`, `git.userName`, `git.userEmail`, `git.provider`, `git.existingSecret`, `git.secretKeys` |
| `auth` | `auth.enabled`, `auth.sessionTimeout`, `auth.oidcStateTtl`, `auth.internalApiKey`, `auth.local`, `auth.activeDirectory`, `auth.auth0`, `auth.azureAd` |
| `database` | `database.mode`, `database.sharedOperator`, `database.url`, `database.existingSecret`, `database.secretKey` |
| `mariadbOperator` | `mariadbOperator.enabled`, `mariadbOperator.namespace`, `mariadbOperator.server`, `mariadbOperator.database`, `mariadbOperator.user`, `mariadbOperator.grants` |
| `mongodb` | `mongodb.enabled`, `mongodb.external`, `mongodb.host`, `mongodb.port`, `mongodb.database`, `mongodb.username`, `mongodb.password`, `mongodb.existingSecret`, `mongodb.usernameKey`, `mongodb.passwordKey`, `mongodb.image`, `mongodb.auth`, `mongodb.persistence`, `mongodb.resources`, `mongodb.service` |
| `chef` | `chef.enabled`, `chef.replicaCount`, `chef.interval`, `chef.resources` |
| `prepChef` | `prepChef.enabled`, `prepChef.replicaCount`, `prepChef.interval`, `prepChef.resources` |
| `timer` | `timer.enabled`, `timer.replicaCount`, `timer.interval`, `timer.slaBufferPercent`, `timer.resources` |
| `dishwasher` | `dishwasher.enabled`, `dishwasher.replicaCount`, `dishwasher.interval`, `dishwasher.defaultDuration`, `dishwasher.defaultTimeout`, `dishwasher.pruneMissing`, `dishwasher.resources` |
| `bootstrap` | `bootstrap.poundcakeBootstrap` |
| `stackstormActionrunner` | `stackstormActionrunner.serviceAccount`, `stackstormActionrunner.pvcPatchRbac` |
| `bakery` | `bakery.enabled`, `bakery.replicaCount`, `bakery.serviceAccount`, `bakery.worker`, `bakery.dbInit`, `bakery.image`, `bakery.service`, `bakery.gateway`, `bakery.resources`, `bakery.config`, `bakery.auth`, `bakery.client`, `bakery.servicenow`, `bakery.jira`, `bakery.github`, `bakery.pagerduty`, `bakery.teams`, `bakery.discord`, `bakery.rackspaceCore`, `bakery.database` |
| `poundcakeImage` | `poundcakeImage.repository`, `poundcakeImage.tag`, `poundcakeImage.digest`, `poundcakeImage.pullPolicy`, `poundcakeImage.pullSecrets`, `poundcakeImage.securityContext` |
| `uiImage` | `uiImage.repository`, `uiImage.tag`, `uiImage.pullPolicy`, `uiImage.containerPort`, `uiImage.runtimeWritablePaths`, `uiImage.securityContext` |
| `stackstormImage` | `stackstormImage.repository`, `stackstormImage.tag`, `stackstormImage.pullPolicy`, `stackstormImage.securityContext` |
| `utilitySecurityContext` | `utilitySecurityContext.runAsNonRoot`, `utilitySecurityContext.runAsUser`, `utilitySecurityContext.allowPrivilegeEscalation`, `utilitySecurityContext.readOnlyRootFilesystem`, `utilitySecurityContext.capabilities` |
| `images` | `images.mariadb`, `images.mongodb`, `images.rabbitmq`, `images.redis`, `images.alpine`, `images.busybox`, `images.kubectl` |
| `stackstormApi` | `stackstormApi.readiness` |
| `poundcakeApi` | `poundcakeApi.readiness`, `poundcakeApi.ticketing` |
| `secrets` | `secrets.dbRootPassword`, `secrets.dbName`, `secrets.dbUser`, `secrets.dbPassword`, `secrets.mongoRootPassword`, `secrets.mongoUsername`, `secrets.mongoPassword`, `secrets.rabbitmqUser`, `secrets.rabbitmqPassword`, `secrets.st2AuthUser`, `secrets.st2AuthPassword`, `secrets.packSyncToken` |
| `stackstormPackSync` | `stackstormPackSync.enabled`, `stackstormPackSync.endpoint`, `stackstormPackSync.pollIntervalSeconds`, `stackstormPackSync.bootstrapPollIntervalSeconds`, `stackstormPackSync.timeoutSeconds` |
| `services` | `services.api`, `services.ui`, `services.stackstormApi`, `services.stackstormAuth`, `services.stackstormStream`, `services.stackstormWeb` |
| `stackstormComponents` | `stackstormComponents.register`, `stackstormComponents.stream`, `stackstormComponents.web`, `stackstormComponents.client` |
| `stackstormServices` | `stackstormServices.mongodb`, `stackstormServices.rabbitmq`, `stackstormServices.redis`, `stackstormServices.auth`, `stackstormServices.api`, `stackstormServices.actionrunner`, `stackstormServices.rulesengine`, `stackstormServices.workflowengine`, `stackstormServices.scheduler`, `stackstormServices.notifier`, `stackstormServices.garbagecollector`, `stackstormServices.timersengine`, `stackstormServices.sensorcontainer`, `stackstormServices.register`, `stackstormServices.stream`, `stackstormServices.web`, `stackstormServices.client` |
| `intervals` | `intervals.chef`, `intervals.prepChef`, `intervals.timer`, `intervals.dishwasher`, `intervals.prepInterval` |
| `logFormat` | default: `'console'` |
| `defaultResources` | `defaultResources.requests`, `defaultResources.limits` |
| `infraSecurityContext` | `infraSecurityContext.mariadb`, `infraSecurityContext.mongodb`, `infraSecurityContext.rabbitmq`, `infraSecurityContext.redis` |
| `startupHooks` | `startupHooks.gateLogging`, `startupHooks.parallelWait`, `startupHooks.cleanup` |
| `pdb` | `pdb.enabled` |
