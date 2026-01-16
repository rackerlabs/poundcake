# PoundCake Webhook Test Payloads

This directory contains sample JSON payloads for testing the PoundCake webhook endpoint.

## Available Payloads

### test-basic.json
Simple test alert with minimal information.

**Usage:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/test-basic.json
```

**Use case:** Quick smoke test to verify webhook is working.

---

### alert-firing.json
Realistic firing alert with full metadata (HighCPUUsage warning).

**Usage:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/alert-firing.json
```

**Use case:** Test alert processing and StackStorm workflow triggers.

---

### alert-resolved.json
Resolved alert showing how alerts clear (HighCPUUsage resolved).

**Usage:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/alert-resolved.json
```

**Use case:** Test resolved alert handling and cleanup workflows.

---

### alert-multiple.json
Multiple alerts in a single webhook (3 servers with low disk space).

**Usage:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/alert-multiple.json
```

**Use case:** Test batch processing and concurrent task execution.

---

### alert-critical.json
Critical severity alert requiring immediate action (ServiceDown).

**Usage:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @examples/alert-critical.json
```

**Use case:** Test high-priority alert routing and urgent remediation workflows.

---

## Quick Test All Payloads

```bash
# From repository root
for payload in examples/*.json; do
  echo "Testing $payload..."
  curl -X POST http://localhost:8000/api/v1/webhook \
    -H "Content-Type: application/json" \
    -d @$payload
  echo -e "\n---\n"
  sleep 2
done
```

## Verify Results

After sending webhooks, check:

### 1. API Response
Each curl should return:
```json
{
  "status": "accepted",
  "request_id": "req-abc-123",
  "alerts_received": 1,
  "task_ids": ["task-xyz-789"],
  "message": "Webhook received and queued for processing"
}
```

### 2. Database
```bash
# Check alerts were stored
curl http://localhost:8000/api/v1/alerts

# Check API calls
curl http://localhost:8000/api/v1/calls
```

### 3. Celery Tasks
```bash
# View in Flower
open http://localhost:5555

# Or check specific request
curl http://localhost:8000/api/v1/requests/{request_id}/status
```

### 4. Logs
```bash
# API logs
docker-compose logs -f api

# Celery worker logs
docker-compose logs -f celery
```

## Customizing Payloads

Copy any example and modify:

```bash
# Copy example
cp examples/alert-firing.json my-custom-alert.json

# Edit in your favorite editor
nano my-custom-alert.json

# Test
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @my-custom-alert.json
```

### Key Fields to Customize

**Alert Identity:**
- `fingerprint` - Unique alert identifier (change for each test)
- `labels.alertname` - Alert name (appears in UI)
- `labels.instance` - Source instance/host

**Timing:**
- `startsAt` - When alert fired (ISO 8601 format)
- `endsAt` - When alert resolved (for resolved alerts)

**Severity:**
- `labels.severity` - info, warning, critical
- Affects alert routing and priority

**Metadata:**
- `annotations.summary` - Brief description
- `annotations.description` - Detailed information
- `annotations.runbook_url` - Link to runbook

## Required Fields

All payloads must include:

**Top-level:**
- `version` - Alertmanager version (usually "4")
- `groupKey` - Grouping identifier
- `status` - firing or resolved
- `receiver` - Receiver name
- `groupLabels` - Labels used for grouping
- `commonLabels` - Labels common to all alerts
- `commonAnnotations` - Annotations common to all alerts
- `externalURL` - Alertmanager external URL

**Per-alert:**
- `status` - firing or resolved
- `labels.alertname` - Alert name (required)
- `startsAt` - Start time (ISO 8601)
- `fingerprint` - Unique identifier

## Tips

### Generate Dynamic Fingerprints

```bash
# Using timestamp
FINGERPRINT="test-$(date +%s)"

# Using random string
FINGERPRINT="test-$(uuidgen | cut -c1-8)"

# In JSON (using jq)
jq --arg fp "test-$(date +%s)" '.alerts[0].fingerprint = $fp' \
  examples/test-basic.json | \
  curl -X POST http://localhost:8000/api/v1/webhook \
    -H "Content-Type: application/json" \
    -d @-
```

### Test Specific Scenarios

**High volume test:**
```bash
for i in {1..10}; do
  jq --arg fp "test-$i" '.alerts[0].fingerprint = $fp' \
    examples/test-basic.json | \
    curl -X POST http://localhost:8000/api/v1/webhook \
      -H "Content-Type: application/json" \
      -d @-
done
```

**Rapid fire test:**
```bash
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/v1/webhook \
    -H "Content-Type: application/json" \
    -d @examples/test-basic.json &
done
wait
```

## Troubleshooting

**Error: "Field required"**
- Missing required field in payload
- Check against examples above
- Validate JSON syntax with `jq . < file.json`

**Error: "Not Found" or 404**
- Wrong endpoint - use `/api/v1/webhook` not `/webhook`
- Check API is running: `curl http://localhost:8000/api/v1/health`

**No response from Celery**
- Check Celery workers: `docker-compose logs celery`
- View tasks in Flower: http://localhost:5555
- Verify Redis is running: `docker-compose ps redis`

**Alerts not appearing in database**
- Check API logs: `docker-compose logs api`
- Verify database connection: `docker-compose exec mariadb mysql -uroot -prootpassword poundcake`
- Check tables exist: `SHOW TABLES LIKE 'poundcake_%';`

## Real Alertmanager Integration

Once testing is complete, configure Alertmanager:

```yaml
# alertmanager.yml
route:
  receiver: poundcake
  group_by: ['alertname', 'instance']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h

receivers:
  - name: poundcake
    webhook_configs:
      - url: http://poundcake-api:8000/api/v1/webhook
        send_resolved: true
```

Then Alertmanager will send these payloads automatically!

## More Examples

Need more examples? Check:
- `../scripts/test-webhook.sh` - Automated test script
- Real Alertmanager webhook: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
- Alertmanager webhook format: https://prometheus.io/docs/alerting/latest/notifications/
