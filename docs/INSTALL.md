# Installation Guide

PoundCake is deployed to Kubernetes using Helm. This guide covers installation and configuration.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.x
- MySQL/MariaDB database (external or provisioned separately)
- StackStorm instance (can be deployed via Helm)

## Quick Start

### 1. Install StackStorm (if not already installed)

```bash
# Use the provided install script
cd bin
./install-stackstorm.sh

# Or install via Helm manually
helm repo add stackstorm https://helm.stackstorm.com
helm install stackstorm stackstorm/stackstorm-ha \
  --namespace stackstorm \
  --create-namespace
```

### 2. Install PoundCake

```bash
# Install from OCI registry
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set database.url="mysql+pymysql://user:pass@mysql:3306/poundcake" \
  --set redis.enabled=true \
  --set stackstorm.apiKey=your-st2-api-key
```

Or use a values file:

```bash
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  -f my-values.yaml
```

### 3. Verify Installation

```bash
# Check pods are running
kubectl get pods -n poundcake

# Check service
kubectl get svc -n poundcake

# View logs
kubectl logs -n poundcake -l app.kubernetes.io/name=poundcake
```

### 4. Access the UI

```bash
# Port forward
kubectl port-forward svc/poundcake 8080:8080 -n poundcake

# Open browser
open http://localhost:8080
```

## Database Setup

PoundCake requires MySQL/MariaDB for persistent storage.

### Option 1: External Database

Use an existing MySQL/MariaDB instance:

```yaml
# values.yaml
database:
  url: "mysql+pymysql://poundcake:password@mysql.database.svc:3306/poundcake"
```

Or use a secret:

```bash
# Create secret
kubectl create secret generic poundcake-db \
  --namespace poundcake \
  --from-literal=database-url="mysql+pymysql://user:pass@mysql:3306/poundcake"

# Reference in values
database:
  existingSecret: poundcake-db
  secretKey: database-url
```

### Option 2: Deploy MySQL with Bitnami Chart

```bash
# Add Bitnami repo
helm repo add bitnami https://charts.bitnami.com/bitnami

# Install MySQL
helm install mysql bitnami/mysql \
  --namespace poundcake \
  --set auth.database=poundcake \
  --set auth.username=poundcake \
  --set auth.password=poundcake-password

# Use in PoundCake
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --set database.url="mysql+pymysql://poundcake:poundcake-password@mysql:3306/poundcake"
```

### Database Schema

PoundCake automatically creates tables on startup:

- `poundcake_api_calls` - Request tracking with request_id
- `poundcake_alerts` - Alert data from Alertmanager
- `poundcake_st2_execution_link` - Links to StackStorm executions
- `poundcake_mappings` - Alert-to-action mappings
- `poundcake_task_executions` - Celery task tracking

## StackStorm Configuration

### Authentication Options

**Option 1: API Key (Recommended)**

```yaml
stackstorm:
  url: "http://stackstorm-st2api.stackstorm.svc:9101"
  apiKey: "your-api-key"
```

**Option 2: Admin Credentials for Auto-Generation**

```yaml
stackstorm:
  url: "http://stackstorm-st2api.stackstorm.svc:9101"
  authUrl: "http://stackstorm-st2auth.stackstorm.svc:9100"
  adminUser: "st2admin"
  adminPasswordSecret: "stackstorm-admin"
  adminPasswordSecretKey: "password"
```

**Option 3: Existing Secret**

```bash
kubectl create secret generic stackstorm-creds \
  --namespace poundcake \
  --from-literal=api-key="your-api-key"
```

```yaml
stackstorm:
  existingSecret: stackstorm-creds
  secretKeys:
    apiKey: "api-key"
```

## Redis Configuration

Redis is required for Celery task processing.

### Deploy Redis with Chart (Default)

```yaml
redis:
  enabled: true
  deploy: true
  password: "redis-password"
  persistence:
    enabled: true
    size: 1Gi
```

### Use External Redis

```yaml
redis:
  enabled: true
  deploy: false
  external:
    url: "redis://my-redis:6379/0"
    password: "redis-password"
```

## Authentication

Enable authentication to protect the UI and API:

```yaml
auth:
  enabled: true
  sessionTimeout: 86400  # 24 hours
```

Retrieve the generated admin password:

```bash
kubectl get secret poundcake-admin -n poundcake \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

## Horizontal Scaling

For high availability deployments:

```yaml
replicaCount: 3

redis:
  enabled: true  # Required for distributed state

celery:
  enabled: true
  replicaCount: 2
  concurrency: 4
```

## Ingress Configuration

Expose PoundCake via Ingress:

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
  hosts:
    - host: poundcake.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: poundcake-tls
      hosts:
        - poundcake.example.com
```

## Prometheus Integration

### Enable ServiceMonitor

```yaml
serviceMonitor:
  enabled: true
  labels:
    release: kube-prometheus-stack
```

### Configure Prometheus CRD Management

```yaml
prometheus:
  url: "http://prometheus-server.prometheus.svc:9090"
  useCrds: true
  crdNamespace: prometheus
  crdLabels:
    release: kube-prometheus-stack
```

## Git Integration (GitOps)

Enable Git integration for rule management with PR workflow:

```yaml
git:
  enabled: true
  repoUrl: "https://github.com/yourorg/prometheus-rules.git"
  branch: main
  provider: github
  token: "github-token"
  userName: PoundCake
  userEmail: poundcake@example.com
```

## Complete Example values.yaml

```yaml
replicaCount: 2

database:
  url: "mysql+pymysql://poundcake:password@mysql:3306/poundcake"

redis:
  enabled: true
  deploy: true
  password: "redis-password"
  persistence:
    enabled: true

celery:
  enabled: true
  replicaCount: 2
  concurrency: 4

stackstorm:
  url: "http://stackstorm-st2api.stackstorm.svc:9101"
  authUrl: "http://stackstorm-st2auth.stackstorm.svc:9100"
  adminPasswordSecret: "stackstorm-admin"

prometheus:
  url: "http://prometheus-server.prometheus.svc:9090"
  useCrds: true
  crdNamespace: monitoring
  crdLabels:
    release: kube-prometheus-stack

auth:
  enabled: true

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: poundcake.example.com
      paths:
        - path: /
          pathType: Prefix

serviceMonitor:
  enabled: true
  labels:
    release: kube-prometheus-stack
```

## Alertmanager Configuration

Configure Alertmanager to send webhooks to PoundCake:

```yaml
receivers:
  - name: poundcake
    webhook_configs:
      - url: http://poundcake.poundcake.svc.cluster.local:8080/api/v1/webhook
        send_resolved: true
```

## Upgrading

```bash
# Upgrade to latest version
helm upgrade poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  -f my-values.yaml

# Upgrade to specific version
helm upgrade poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --version 1.2.0 \
  -f my-values.yaml
```

## Uninstalling

```bash
helm uninstall poundcake --namespace poundcake
kubectl delete namespace poundcake
```

## Troubleshooting

### Pods not starting

```bash
# Check pod status
kubectl describe pod -n poundcake -l app.kubernetes.io/name=poundcake

# Check logs
kubectl logs -n poundcake -l app.kubernetes.io/name=poundcake --tail=100
```

### Database connection issues

```bash
# Verify database URL is set
kubectl get deployment poundcake -n poundcake -o jsonpath='{.spec.template.spec.containers[0].env}' | jq

# Test database connectivity
kubectl run mysql-client --rm -it --image=mysql:8 --restart=Never -- \
  mysql -h mysql -u poundcake -ppassword -e "SELECT 1"
```

### StackStorm connection issues

```bash
# Test StackStorm API
kubectl run curl --rm -it --image=curlimages/curl --restart=Never -- \
  curl -H "St2-Api-Key: your-key" http://stackstorm-st2api.stackstorm.svc:9101/v1/actions
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more detailed troubleshooting steps.
