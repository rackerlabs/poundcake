# Developer Runbook (Fork + Lab)

This runbook covers local development, CI/CD behavior, fork-based package publishing, and lab deployment.

## 1) Prerequisites

Required tools:

- `git`
- `python` 3.11+
- `pip`
- `docker` and `docker compose`
- `kubectl`
- `helm` 3.13+
- `gh` (GitHub CLI)

Required access:

- GitHub fork of `poundcake`
- GHCR package permissions for your fork owner
- Kubernetes cluster access for lab deployment

Quick verification:

```bash
python --version
docker --version
docker compose version
kubectl version --client
helm version
gh --version
gh auth status
```

## 2) Local Setup (Docker Compose)

Install dependencies:

```bash
make dev-install
```

## 2.1) Python venv Setup (Unit Tests + pre-commit)

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Install and run pre-commit hooks:

```bash
pre-commit install
pre-commit run -a
```

Typical local quality checks:

```bash
make test
make lint
```

Start local stack with compose:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Check health and logs:

```bash
curl http://localhost:8000/api/v1/health
docker compose -f docker/docker-compose.yml logs -f api prep-chef chef timer dishwasher
```

Stop stack:

```bash
docker compose -f docker/docker-compose.yml down
```

## 3) Build/Test Workflow

Run tests:

```bash
make test
```

Manual shell e2e test execution examples (compose and k8s): see `/Users/chris.breu/code/poundcake/tests/README.md` under **Run Tests By Hand**.

Run lint/type checks:

```bash
make lint
```

Format:

```bash
make format
```

Coverage output:

- HTML coverage is generated in `htmlcov/` by `make test`.

## 4) Release/Versioning Rules

Versioning inputs:

- App version tags: Git tags like `v0.0.2` trigger release workflow.
- Helm chart publish version: `helm/Chart.yaml` `version:` field.

Rules:

- Bump `helm/Chart.yaml` `version:` before publishing a new chart version.

- Pushing a `v*` tag runs `.github/workflows/release.yaml`.
- Pushing to `main` runs `.github/workflows/build-push.yaml`.

Tag and push:

```bash
export RELEASE_TAG="v0.0.2"
git tag "$RELEASE_TAG"
git push origin "$RELEASE_TAG"
```

## 5) Deploy Workflows (Fork Artifacts -> Lab)

Configure your fork for package publishing:

```bash
export FORK_REPO="<your-github-user>/poundcake"
export FORK_OWNER="<your-github-user>"

gh variable set GHCR_OWNER --repo "$FORK_REPO" --body "$FORK_OWNER"
gh variable set GHCR_REPO_NAME --repo "$FORK_REPO" --body "poundcake"
```

Secrets in fork:

```bash
# Preferred: use GITHUB_TOKEN path in workflow if possible.
gh secret delete CR_PAT --repo "$FORK_REPO" || true

# If needed, set CR_PAT with read:packages + write:packages.
# gh secret set CR_PAT --repo "$FORK_REPO"
```

Trigger image build (push to fork main):

```bash
git checkout main
git pull --ff-only
git push origin main
```

Trigger chart publish (release tag in fork):

```bash
export RELEASE_TAG="v0.0.2"
git tag "$RELEASE_TAG"
git push origin "$RELEASE_TAG"
```

Deploy in lab from fork registries:

```bash
export HELM_REGISTRY_USERNAME="<github-user>"
export HELM_REGISTRY_PASSWORD="<github-token-with-read:packages>"

export POUNDCAKE_GHCR_OWNER="$FORK_OWNER"
export POUNDCAKE_CHART_REPO="oci://ghcr.io/${FORK_OWNER}/charts/poundcake"
# Default helper behavior is local chart install (POUNDCAKE_CHART_REPO unset).
# Set POUNDCAKE_CHART_REPO only when you explicitly want OCI chart source.
# export POUNDCAKE_CHART_REPO="oci://ghcr.io/${FORK_OWNER}/charts/poundcake"
export POUNDCAKE_IMAGE_REPO="ghcr.io/${FORK_OWNER}/poundcake"
export POUNDCAKE_UI_IMAGE_REPO="ghcr.io/${FORK_OWNER}/poundcake-ui"
export POUNDCAKE_BAKERY_IMAGE_REPO="ghcr.io/${FORK_OWNER}/poundcake-bakery"

./install/install-bakery-helm.sh
./install/install-poundcake-helm.sh --validate
./install/install-poundcake-helm.sh
```

Note:

- Installers:
  - `install/install-bakery-helm.sh` installs Bakery only.
  - `install/install-poundcake-helm.sh` installs PoundCake only.
  - Co-located flow in one namespace is Bakery first, then PoundCake.
  - For non-co-located Bakery, use `./install/install-poundcake-helm.sh --remote-bakery-url <url>`.
- `install/install-poundcake-helm.sh` reads desired chart versions from `/etc/genestack/helm-chart-versions.yaml`:
  - `poundcake`
  - `stackstorm`
  - `mariadb-operator`
  - `redis-operator`
  - `rabbitmq-cluster-operator`
  - `mongodb-operator` (optional; falls back to installer default when absent)

### 5.1) Installer Environment Variables

Defaults below are installer defaults from `helm/bin/install-poundcake.sh` unless noted.
If you source `install/set-env-helper.sh`, those helper exports may override these defaults.

| Variable | Default | Required? | Purpose | When to set |
|---|---|---|---|---|
| `FORK_OWNER` | _(none)_ | Yes for fork workflow | Owner/org for fork package references in helper snippets | Always in fork-based deploy workflows |
| `HELM_REGISTRY_USERNAME` | `""` (helper: `$FORK_OWNER`) | Required for private GHCR | Used for Helm OCI login and docker-registry secret creation | Set when chart/images are private |
| `HELM_REGISTRY_PASSWORD` | `""` | Required for private GHCR | Token/password for OCI login and pull-secret auth; must include `read:packages` for private pulls | Set when using private GHCR |
| `POUNDCAKE_GHCR_OWNER` | `rackerlabs` (helper: `$FORK_OWNER`) | Optional | Owner used to derive default image repo | Set when pulling from a fork/private owner |
| `POUNDCAKE_CHART_REPO` | local chart path (`./helm`) (helper leaves unset for local mode) | Optional | Chart source (`oci://...` or local) | Set for OCI-based deployments |
| `POUNDCAKE_CHART_VERSION` | `""` | Optional | Explicit OCI chart version | Pin chart version for repeatable deploys |
| `POUNDCAKE_VERSION_FILE` | `/etc/genestack/helm-chart-versions.yaml` | Optional | Source for auto-detected chart version key `poundcake` | Change only if your version file is elsewhere |
| `POUNDCAKE_IMAGE_REPO` | `ghcr.io/${POUNDCAKE_GHCR_OWNER}/poundcake` | Optional | PoundCake image repository | Set for fork/private image repo |
| `POUNDCAKE_IMAGE_TAG` | `""` | Conditionally required | PoundCake image tag | Set when not using digest pin |
| `POUNDCAKE_IMAGE_DIGEST` | `""` | Conditionally required | PoundCake image digest (`sha256:...`) | Set when not using tag pin; preferred for immutable deploys |
| `POUNDCAKE_UI_IMAGE_REPO` | `""` (helper sets fork path) | Optional | UI image repository override (`uiImage.repository`) | Set for fork/private UI image repo |
| `POUNDCAKE_BAKERY_IMAGE_REPO` | `""` (helper sets fork path) | Optional | Bakery image repository override (`bakery.image.repository`) | Set for fork/private Bakery image repo |
| `POUNDCAKE_BAKERY_IMAGE_TAG` | `""` (helper defaults from `POUNDCAKE_IMAGE_TAG`) | Optional | Bakery image tag (`bakery.image.tag`) | Used when Bakery digest unset |
| `POUNDCAKE_BAKERY_IMAGE_DIGEST` | `""` | Optional | Bakery image digest (`sha256:...`) | Overrides Bakery tag; if unset, `POUNDCAKE_IMAGE_DIGEST` is used |
| `POUNDCAKE_STACKSTORM_IMAGE_REPO` | `stackstorm/st2` | Optional | StackStorm image repository | Set when using custom/private StackStorm image |
| `POUNDCAKE_STACKSTORM_IMAGE_TAG` | `3.9.0` | Optional | StackStorm image tag | Pin custom StackStorm version |
| `POUNDCAKE_RELEASE_NAME` | `poundcake` | Optional | Helm release name | Change for parallel installs |
| `POUNDCAKE_NAMESPACE` | `rackspace` | Optional | Kubernetes namespace for install | Set per environment/tenant |
| `POUNDCAKE_HELM_TIMEOUT` | `120m` | Optional | Helm operation timeout | Increase for slower clusters |
| `POUNDCAKE_HELM_WAIT` | `false` | Optional | Enable Helm `--wait` | Only for advanced troubleshooting; guarded due to hook deadlock risk |
| `POUNDCAKE_ALLOW_HOOK_WAIT` | `false` | Optional | Bypass wait deadlock guard | Set only when intentionally forcing wait/atomic |
| `POUNDCAKE_HELM_ATOMIC` | `false` | Optional | Enable Helm `--atomic` | Use only if you accept hook/wait behavior implications |
| `POUNDCAKE_HELM_CLEANUP_ON_FAIL` | `false` | Optional | Enable Helm cleanup on failure | Enable in strict CI environments |
| `POUNDCAKE_IMAGE_PULL_SECRET_NAME` | `ghcr-pull` | Optional | Pull secret name created/reused by installer | Set when org requires naming convention |
| `POUNDCAKE_CREATE_IMAGE_PULL_SECRET` | `true` | Optional | Auto-create/apply docker-registry secret | Disable if secret is pre-provisioned |
| `POUNDCAKE_IMAGE_PULL_SECRET_EMAIL` | `noreply@local` | Optional | Email field used when creating docker-registry secret | Set if your policy requires real address |
| `POUNDCAKE_IMAGE_PULL_SECRET_ENABLED` | `true` | Optional | Inject pull secret into PoundCake workloads | Set `false` only when all images are public or pull handled elsewhere |
| `POUNDCAKE_PACK_SYNC_ENDPOINT` | `http://poundcake-api:8000/api/v1/cook/packs` | Optional | Canonical StackStorm pack-sync endpoint | Override only for explicit compatibility migrations |

Important clarifications:

- `HELM_REGISTRY_PASSWORD` must have `read:packages` for private GHCR pulls.
- `POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true` injects pull secret into PoundCake workloads.
- `POUNDCAKE_CREATE_IMAGE_PULL_SECRET=true` requires namespace and secret create/apply RBAC.
- Bakery image precedence is `POUNDCAKE_BAKERY_IMAGE_DIGEST` -> `POUNDCAKE_BAKERY_IMAGE_TAG` -> chart defaults, with `POUNDCAKE_IMAGE_DIGEST` used when Bakery digest is unset.

### 5.2) Chart Pull-Secret Values (Canonical vs Legacy)

- Canonical key: `poundcakeImage.pullSecrets`
- Legacy fallback (temporary): `imagePullSecrets`

Examples:

```bash
# Canonical
helm upgrade --install poundcake ./helm --set poundcakeImage.pullSecrets[0]=ghcr-pull

# Legacy fallback (backward compatibility)
helm upgrade --install poundcake ./helm --set imagePullSecrets[0]=ghcr-pull
```

Scope:

- Pull secret is applied to PoundCake deployments and `poundcake-bootstrap`.
- Pull secret is not applied to StackStorm/infra workloads by default.

Secret ownership and readiness notes:

- `poundcake-secrets` is for PoundCake MariaDB credentials (`DB_*`).
- `stackstorm-secrets` is authoritative for StackStorm infra credentials (`MONGO_*`, `RABBITMQ_*`, `ST2_AUTH_*`).
- `poundcake-api` uses `stackstorm-secrets` for RabbitMQ health-check credentials.
- Redis is currently unauthenticated in this chart; readiness still treats Redis TCP reachability as blocking.

### 5.3) Private GHCR Quick Path

```bash
source ./install/set-env-helper.sh
export HELM_REGISTRY_PASSWORD="<github-token-with-read:packages>"

# Optional overrides
# export POUNDCAKE_IMAGE_REPO="ghcr.io/<owner>/poundcake"
# export POUNDCAKE_IMAGE_TAG="release-20260221-1200"
# export POUNDCAKE_IMAGE_DIGEST="sha256:<64-hex>"
# export POUNDCAKE_BAKERY_IMAGE_DIGEST="sha256:<64-hex>"
# export POUNDCAKE_NAMESPACE="rackspace"

./install/install-poundcake-helm.sh
```

Verification:

```bash
# Secret exists
kubectl -n <ns> get secret <pull-secret-name>

# PoundCake pod spec includes pull secret
kubectl -n <ns> get pod <poundcake-pod> -o jsonpath='{.spec.imagePullSecrets[*].name}'

# No anonymous GHCR token error in events
kubectl -n <ns> describe pod <poundcake-pod> | sed -n '/Events/,$p'
```


## 6) Secrets/Auth Handling

GitHub/GHCR:

- `HELM_REGISTRY_USERNAME` + `HELM_REGISTRY_PASSWORD` are used by Helm OCI login in installer.
- In workflows, ensure token used for package push has `read:packages` and `write:packages`.

Kubernetes/Helm:

- Secrets should be stored as Kubernetes Secrets and referenced by workloads.
- Use `--rotate-secrets` with installer only when you intentionally want to regenerate chart-managed secrets.

### 6.1) Private Pull Troubleshooting Matrix

| Symptom | Likely cause | Fix |
|---|---|---|
| `failed to fetch anonymous token ... 401 Unauthorized` | Pull secret not rendered on PoundCake pod spec, or bad credentials | Ensure `POUNDCAKE_IMAGE_PULL_SECRET_ENABLED=true`; verify pod `imagePullSecrets`; validate PAT scope (`read:packages`) |
| Pull secret exists but image pull still fails | GHCR package visibility/access mismatch for pulling principal | Grant package read access to user/org/token principal used in secret |
| Installer fails creating secret | Namespace or RBAC does not permit secret create/apply | Ensure namespace exists or allow installer namespace creation and secret create/apply RBAC |

### 6.2) Behavioral Guardrails

Installer safeguards to expect:

- `--wait`/`--atomic` deadlock guard: installer fails fast unless `POUNDCAKE_ALLOW_HOOK_WAIT=true` because startup jobs are hook-driven.
- Pull-secret preflight render check: installer validates PoundCake manifests include `imagePullSecrets` when pull-secret injection is enabled.

## 7) Observability/Verification

CI verification:

```bash
gh run list --repo "$FORK_REPO" --limit 10
gh run watch --repo "$FORK_REPO"
```

Artifact verification:

```bash
helm registry login ghcr.io -u "$HELM_REGISTRY_USERNAME" --password-stdin <<<"$HELM_REGISTRY_PASSWORD"
helm pull oci://ghcr.io/${FORK_OWNER}/charts/poundcake --version 0.0.2
```

Cluster verification after install:

```bash
kubectl -n rackspace get pods
kubectl -n rackspace get svc
kubectl -n rackspace get jobs
helm -n rackspace list
```

### 7.1) UI Non-root Entrypoint Verification

When `uiImage.tag` remains `latest`, verify the running pod is using the expected image and rendered config:

```bash
# 1) Confirm current image reference and immutable imageID (digest)
kubectl -n rackspace get pod -l app.kubernetes.io/component=ui \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].image}{"\t"}{.status.containerStatuses[0].imageID}{"\n"}{end}'

# 2) Check restart timestamps for rollout freshness
kubectl -n rackspace get pod -l app.kubernetes.io/component=ui \
  -o custom-columns=POD:.metadata.name,RESTARTS:.status.containerStatuses[0].restartCount,STARTED:.status.startTime

# 3) Verify rendered nginx config listens on 8080
kubectl -n rackspace exec deploy/poundcake-ui -- grep -n "listen" /etc/nginx/conf.d/default.conf

# 4) Verify nginx runs as non-root and is bound to :8080
kubectl -n rackspace exec deploy/poundcake-ui -- id -u
kubectl -n rackspace exec deploy/poundcake-ui -- sh -c 'ss -lntp 2>/dev/null || netstat -lnt 2>/dev/null'
```

Expected:
- `id -u` is not `0` (default is `1000`).
- Rendered config includes `listen 8080;` and does not include `listen 80;`.
- Listener output shows `:8080`.
- Service/ingress may still expose external port `80` while targeting container `8080`.

## 8) CI/CD Behavior

Workflow triggers:

- `.github/workflows/build-push.yaml`: push to `main`
- `.github/workflows/release.yaml`: push tags matching `v*`

Publish targets are configurable by Actions variables:

- `GHCR_OWNER` (defaults to repo owner if unset)
- `GHCR_REPO_NAME` (defaults to repo name if unset)

Expected outputs:

- Images: `ghcr.io/<owner>/poundcake`, `-ui`, `-bakery`
- Chart: `oci://ghcr.io/<owner>/charts/poundcake`

Common CI/CD failure patterns:

- `401 Unauthorized` on GHCR pull/push: token scope or package visibility issue.
- Chart push conflict: chart version already exists; bump `Chart.yaml` version.
