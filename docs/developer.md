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
export POUNDCAKE_IMAGE_REPO="ghcr.io/${FORK_OWNER}/poundcake"
export POUNDCAKE_UI_IMAGE_REPO="ghcr.io/${FORK_OWNER}/poundcake-ui"
export POUNDCAKE_BAKERY_IMAGE_REPO="ghcr.io/${FORK_OWNER}/poundcake-bakery"

./install/install-helm.sh --validate
./install/install-helm.sh
```

Note:
- `install/install-helm.sh` reads desired chart versions from `/etc/genestack/helm-chart-versions.yaml`:
  - `poundcake`
  - `stackstorm`
  - `mariadb-operator`
  - `redis-operator`
  - `rabbitmq-cluster-operator`

## 6) Secrets/Auth Handling

GitHub/GHCR:
- `HELM_REGISTRY_USERNAME` + `HELM_REGISTRY_PASSWORD` are used by Helm OCI login in installer.
- In workflows, ensure token used for package push has `read:packages` and `write:packages`.

Kubernetes/Helm:
- Secrets should be stored as Kubernetes Secrets and referenced by workloads.
- Use `--rotate-secrets` with installer only when you intentionally want to regenerate chart-managed secrets.

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

## 9) CI/CD Behavior

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
