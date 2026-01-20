# PoundCake CLI Reference

The PoundCake CLI (`pcake`) provides command-line access to manage alerts, Prometheus rules, and remediations.

## Installation

The CLI is included in the PoundCake repository under `cli/`.

```bash
# Install CLI dependencies
cd cli
pip install -r requirements.txt

# Or install as package
pip install -e .
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POUNDCAKE_URL` | PoundCake API URL | `http://localhost:8080` |
| `POUNDCAKE_API_KEY` | API key for authentication | None |

### Command-Line Options

```bash
pcake --help

Options:
  -u, --url TEXT      PoundCake API URL
  -k, --api-key TEXT  API key for authentication (if required)
  -f, --format TEXT   Output format [json|yaml|table]
  -v, --verbose       Enable verbose output
  --help              Show this message and exit
```

## Commands

### Alerts

Manage alerts and remediations.

#### List Alerts

```bash
# List all alerts
pcake alerts list

# Filter by status
pcake alerts list --status remediating
pcake alerts list -s pending

# Filter by severity
pcake alerts list --severity critical

# Combine filters
pcake alerts list --status pending --severity critical
```

Status options: `received`, `pending`, `remediating`, `remediated`, `resolved`

Severity options: `critical`, `warning`, `info`

#### Get Alert Details

```bash
pcake alerts get <fingerprint>
```

#### Watch Alerts

```bash
# Show alerts once
pcake alerts watch

# Continuously watch (refreshes every 5 seconds)
pcake alerts watch --watch
pcake alerts watch -w

# Watch with filters
pcake alerts watch --watch --status remediating
```

### Rules

Manage Prometheus alert rules.

#### List Rules

```bash
pcake rules list
```

#### Get Rule

```bash
pcake rules get <crd_name> <group_name> <rule_name>

# Example
pcake rules get my-alerts app-alerts HighMemory
```

#### Create Rule

```bash
# From PromQL expression
pcake rules create <crd_name> <group_name> <rule_name> \
  --expr 'memory_usage > 90' \
  --for 5m \
  --severity critical \
  --summary 'High memory usage detected' \
  --description 'Memory usage is above 90% on {{ $labels.instance }}'

# From YAML file
pcake rules create <crd_name> <group_name> <rule_name> --file rule.yaml
```

#### Update Rule

```bash
# Update expression
pcake rules update my-alerts app-alerts HighMemory --expr 'memory_usage > 85'

# Update from file
pcake rules update my-alerts app-alerts HighMemory --file updated-rule.yaml

# Update severity
pcake rules update my-alerts app-alerts HighMemory --severity warning
```

#### Delete Rule

```bash
# With confirmation prompt
pcake rules delete my-alerts app-alerts HighMemory

# Skip confirmation
pcake rules delete my-alerts app-alerts HighMemory --yes
pcake rules delete my-alerts app-alerts HighMemory -y
```

#### Apply Rules from File

Apply multiple rules from a Prometheus rules YAML file:

```bash
# Apply rules
pcake rules apply rules.yaml

# Specify CRD name
pcake rules apply rules.yaml --crd-name my-custom-alerts

# Dry run (show what would be created)
pcake rules apply rules.yaml --dry-run
```

Example rules file (`rules.yaml`):

```yaml
groups:
  - name: app-alerts
    rules:
      - alert: HighMemory
        expr: memory_usage > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: High memory usage detected

      - alert: HighCPU
        expr: cpu_usage > 80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: High CPU usage detected
```

## Output Formats

### Table (Default)

```bash
pcake alerts list
```

```
FINGERPRINT          ALERTNAME        STATUS       SEVERITY   RECEIVED
abc123def456...     HighMemory       remediating  critical   2024-01-15 10:30:00
xyz789ghi012...     DiskFull         resolved     warning    2024-01-15 09:15:00
```

### JSON

```bash
pcake --format json alerts list
```

```json
{
  "alerts": [
    {
      "fingerprint": "abc123def456...",
      "alertname": "HighMemory",
      "status": "remediating",
      "severity": "critical",
      "received_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### YAML

```bash
pcake --format yaml alerts list
```

```yaml
alerts:
  - fingerprint: abc123def456...
    alertname: HighMemory
    status: remediating
    severity: critical
    received_at: '2024-01-15T10:30:00Z'
```

## Examples

### Typical Workflow

```bash
# Set API URL
export POUNDCAKE_URL=http://poundcake.example.com:8080

# Check current alerts
pcake alerts list

# Watch for remediating alerts
pcake alerts watch --watch --status remediating

# Get details of a specific alert
pcake alerts get abc123def456

# List current Prometheus rules
pcake rules list

# Create a new rule
pcake rules create prod-alerts infra HighLoad \
  --expr 'node_load1 > 4' \
  --for 10m \
  --severity critical \
  --summary 'High load average on {{ $labels.instance }}'

# Apply rules from a file
pcake rules apply my-rules.yaml

# Update an existing rule
pcake rules update prod-alerts infra HighLoad --expr 'node_load1 > 3'

# Delete a rule
pcake rules delete prod-alerts infra HighLoad --yes
```

### Scripting

```bash
#!/bin/bash
# Script to check for critical alerts

export POUNDCAKE_URL=http://poundcake.example.com:8080

# Get critical alerts in JSON format
alerts=$(pcake --format json alerts list --severity critical)

# Count alerts
count=$(echo "$alerts" | jq '.alerts | length')

if [ "$count" -gt 0 ]; then
    echo "WARNING: $count critical alerts found"
    echo "$alerts" | jq '.alerts[] | .alertname'
    exit 1
fi

echo "OK: No critical alerts"
exit 0
```

### Kubernetes Access

When running from outside the cluster:

```bash
# Port forward to PoundCake service
kubectl port-forward svc/poundcake 8080:8080 -n poundcake &

# Use CLI
export POUNDCAKE_URL=http://localhost:8080
pcake alerts list
```

## Error Handling

The CLI provides clear error messages:

```bash
$ pcake alerts get nonexistent
Error: Failed to get alert: 404 Not Found - Alert not found

$ pcake rules create bad-input
Error: Either --file or --expr must be provided
```

Exit codes:
- `0`: Success
- `1`: Error (connection, API error, invalid input)

## Git Integration

When Git integration is enabled, rule changes can create pull requests:

```bash
$ pcake rules create prod-alerts infra NewRule --expr 'up == 0'
Created rule: NewRule
Pull request created: https://github.com/yourorg/prometheus-rules/pull/42
```
