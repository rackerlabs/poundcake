# PoundCake CLI Guide

The `pcake` command-line tool provides a powerful interface for managing PoundCake alerts and rules.

## Installation

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd poundcake-merged

# Install in development mode (recommended for local development)
pip install -e .

# Or install normally
pip install .
```

### Verify Installation

```bash
pcake --help
```

## Configuration

### Environment Variables

```bash
# Required: PoundCake API endpoint
export POUNDCAKE_URL=http://localhost:8000

# Optional: API key for authentication
export POUNDCAKE_API_KEY=your-api-key-here
```

### Configuration File

You can also create a `.poundcake.yml` configuration file:

```yaml
url: http://localhost:8000
api_key: your-api-key-here
format: table  # json, yaml, or table
```

## Commands

### Global Options

```bash
pcake [OPTIONS] COMMAND [ARGS]

Options:
  -u, --url TEXT        PoundCake API URL (env: POUNDCAKE_URL)
  -k, --api-key TEXT    API key for authentication (env: POUNDCAKE_API_KEY)
  -f, --format TEXT     Output format: json, yaml, table (default: table)
  -v, --verbose         Enable verbose output
  --help                Show help message
```

## Alert Commands

### List Alerts

```bash
# List all alerts
pcake alerts list

# List with specific status
pcake alerts list --status firing
pcake alerts list --status resolved
pcake alerts list --status remediating

# Limit number of results
pcake alerts list --limit 10

# Filter by time range
pcake alerts list --since "2024-01-01"
pcake alerts list --until "2024-01-31"
```

### Watch Alerts

Real-time monitoring of alerts:

```bash
# Watch all alerts (refreshes every 2 seconds)
pcake alerts watch

# Watch with specific status
pcake alerts watch --status firing

# Change refresh interval
pcake alerts watch --interval 5
```

### Get Alert Details

```bash
# Get specific alert by ID
pcake alerts get <alert-id>

# Get with full details
pcake alerts get <alert-id> --full
```

### Filter Alerts

```bash
# Filter by labels
pcake alerts list --label "severity=critical"
pcake alerts list --label "instance=prod-server-1"

# Multiple labels
pcake alerts list --label "severity=critical" --label "team=ops"

# Filter by annotation
pcake alerts list --annotation "runbook_url=*"
```

## Rule Commands

### List Rules

```bash
# List all Prometheus rules
pcake rules list

# List rules in specific namespace
pcake rules list --namespace monitoring

# Filter by name pattern
pcake rules list --name "*cpu*"
```

### Get Rule Details

```bash
# Get specific rule
pcake rules get <namespace> <name>

# Get with full details including expressions
pcake rules get <namespace> <name> --full
```

### Create Rule

```bash
# Create a new Prometheus rule
pcake rules create monitoring app-alerts HighCPUUsage \
  --expr 'node_cpu_usage > 90' \
  --severity critical \
  --summary "High CPU usage detected" \
  --description "CPU usage is above 90% for 5 minutes"

# With additional labels
pcake rules create monitoring app-alerts HighMemory \
  --expr 'node_memory_usage > 85' \
  --severity warning \
  --label "team=platform" \
  --label "component=infrastructure"

# With annotations
pcake rules create monitoring app-alerts DiskFull \
  --expr 'node_disk_usage > 95' \
  --severity critical \
  --annotation "runbook_url=https://wiki.example.com/runbooks/disk-full" \
  --annotation "dashboard=https://grafana.example.com/d/disk"
```

### Update Rule

```bash
# Update rule expression
pcake rules update monitoring app-alerts HighCPUUsage \
  --expr 'node_cpu_usage > 85'

# Update severity
pcake rules update monitoring app-alerts HighCPUUsage \
  --severity warning

# Update multiple fields
pcake rules update monitoring app-alerts HighCPUUsage \
  --expr 'node_cpu_usage > 85' \
  --severity warning \
  --summary "Updated CPU threshold"
```

### Delete Rule

```bash
# Delete a rule
pcake rules delete monitoring app-alerts HighCPUUsage

# Delete with confirmation
pcake rules delete monitoring app-alerts HighCPUUsage --yes
```

### Validate Rule

```bash
# Validate rule syntax before creating
pcake rules validate \
  --expr 'rate(http_requests_total[5m]) > 100'

# Validate with namespace and name
pcake rules validate monitoring app-alerts NewRule \
  --expr 'up == 0'
```

## Output Formats

### Table Format (Default)

```bash
pcake alerts list
# Output:
# ID    STATUS    SEVERITY    NAME              STARTED
# 123   firing    critical    HighCPU           2024-01-15 10:30:00
# 124   resolved  warning     HighMemory        2024-01-15 10:25:00
```

### JSON Format

```bash
pcake alerts list --format json
# Output:
# [
#   {
#     "id": 123,
#     "status": "firing",
#     "severity": "critical",
#     "name": "HighCPU",
#     "started_at": "2024-01-15T10:30:00Z"
#   }
# ]
```

### YAML Format

```bash
pcake alerts list --format yaml
# Output:
# - id: 123
#   status: firing
#   severity: critical
#   name: HighCPU
#   started_at: '2024-01-15T10:30:00Z'
```

## Advanced Usage

### Piping and Filtering

```bash
# Get firing alerts and save to file
pcake alerts list --status firing --format json > firing_alerts.json

# Count critical alerts
pcake alerts list --label "severity=critical" --format json | jq length

# Get alert IDs only
pcake alerts list --format json | jq -r '.[].id'
```

### Scripting

```bash
#!/bin/bash
# Check for critical alerts and send notification

CRITICAL_COUNT=$(pcake alerts list \
  --status firing \
  --label "severity=critical" \
  --format json | jq length)

if [ "$CRITICAL_COUNT" -gt 0 ]; then
  echo "WARNING: $CRITICAL_COUNT critical alerts firing!"
  # Send notification
fi
```

### Automation

```bash
# Cron job to check alerts every 5 minutes
*/5 * * * * /usr/local/bin/pcake alerts watch --once | mail -s "Alert Report" admin@example.com
```

## Examples

### Monitor Production Alerts

```bash
# Watch critical alerts in production
pcake alerts watch \
  --status firing \
  --label "severity=critical" \
  --label "environment=production"
```

### Create Alert Rule Set

```bash
# Create multiple related rules
for threshold in 80 90 95; do
  pcake rules create monitoring disk-alerts "DiskUsage${threshold}" \
    --expr "node_disk_usage > ${threshold}" \
    --severity $([ $threshold -gt 90 ] && echo "critical" || echo "warning") \
    --summary "Disk usage above ${threshold}%"
done
```

### Export Current Rules

```bash
# Export all rules as JSON
pcake rules list --format json > rules_backup.json

# Export specific namespace
pcake rules list --namespace monitoring --format yaml > monitoring_rules.yaml
```

### Audit Alert History

```bash
# Get all resolved alerts from last 24 hours
pcake alerts list \
  --status resolved \
  --since "24 hours ago" \
  --format json > daily_resolved.json

# Count alerts by status
for status in firing resolved remediating; do
  count=$(pcake alerts list --status $status --format json | jq length)
  echo "$status: $count"
done
```

## Troubleshooting

### Connection Issues

```bash
# Test API connectivity
curl $POUNDCAKE_URL/health

# Use verbose mode for debugging
pcake -v alerts list

# Check configuration
echo $POUNDCAKE_URL
echo $POUNDCAKE_API_KEY
```

### Authentication Errors

```bash
# Verify API key is set
echo $POUNDCAKE_API_KEY

# Test with explicit API key
pcake -k "your-api-key" alerts list
```

### Output Issues

```bash
# Force table output
pcake alerts list --format table

# Get raw JSON for debugging
pcake alerts list --format json | jq .
```

## Tips and Best Practices

1. **Use Environment Variables**: Set `POUNDCAKE_URL` and `POUNDCAKE_API_KEY` in your shell profile
2. **Alias Common Commands**: Create shell aliases for frequently used commands
3. **Watch Mode**: Use `pcake alerts watch` during incident response
4. **JSON Output**: Use `--format json` for scripting and automation
5. **Verbose Mode**: Use `-v` flag when troubleshooting issues

## Integration with Other Tools

### With jq

```bash
# Get count of alerts by status
pcake alerts list --format json | jq 'group_by(.status) | map({status: .[0].status, count: length})'
```

### With curl

```bash
# CLI uses the same API endpoints
pcake alerts list
# is equivalent to:
curl $POUNDCAKE_URL/api/alerts
```

### With Monitoring Systems

```bash
# Export metrics for external monitoring
pcake alerts list --status firing --format json | \
  jq 'group_by(.severity) | map({severity: .[0].severity, count: length})' | \
  prometheus_exporter.py
```

## Getting Help

```bash
# General help
pcake --help

# Command help
pcake alerts --help
pcake rules --help

# Subcommand help
pcake alerts list --help
pcake rules create --help
```

## API Reference

The CLI communicates with these API endpoints:

- `GET /api/alerts` - List alerts
- `GET /api/alerts/{id}` - Get alert details
- `GET /api/calls` - List API calls
- `GET /api/rules` - List rules
- `POST /api/rules` - Create rule
- `PUT /api/rules/{id}` - Update rule
- `DELETE /api/rules/{id}` - Delete rule

For full API documentation, visit: http://localhost:8000/docs
