# PoundCake Webhook Testing Guide

## Overview

The webhook endpoint receives Alertmanager notifications and stores them in the database.

**Endpoint:** `POST /api/v1/webhook`

## Data Flow
```
Alertmanager → POST /webhook → PoundCake API → MariaDB alerts table
                                        ↓
                                   Return req_id
```

## Step-by-Step Testing

### 1. Send Test Webhook
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-group",
    "status": "firing",
    "receiver": "poundcake",
    "groupLabels": {"alertname": "TestAlert"},
    "commonLabels": {
      "alertname": "TestAlert",
      "severity": "warning"
    },
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "TestAlert",
          "severity": "warning",
          "instance": "test-instance"
        },
        "annotations": {
          "summary": "This is a test alert"
        },
        "startsAt": "2026-01-30T15:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "fingerprint": "test123abc"
      }
    ]
  }'
```

**Expected Response:**
```json
{
  "status": "accepted",
  "request_id": "req_abc123...",
  "alerts_received": 1,
  "task_ids": ["task-uuid-1"],
  "message": "Webhook received and queued for processing"
}
```

### 2. Verify Alert in Database

**Via API:**
```bash
# Query by request_id
curl "http://localhost:8000/api/v1/alerts?req_id=req_abc123..."

# Query by fingerprint
curl "http://localhost:8000/api/v1/alerts?fingerprint=test123abc"

# Query by alert name
curl "http://localhost:8000/api/v1/alerts?name=TestAlert"

# Query by processing status
curl "http://localhost:8000/api/v1/alerts?processing_status=new"
```

**Via Database:**
```bash
docker exec poundcake-mariadb mysql -upoundcake -ppoundcake poundcake \
  -e "SELECT * FROM alerts WHERE fingerprint='test123abc'\\G"
```

### 3. Check Alert Table Schema
```bash
docker exec poundcake-mariadb mysql -upoundcake -ppoundcake poundcake \
  -e "DESCRIBE alerts;"
```

**Expected Columns:**
- `id` - Primary key
- `req_id` - Request ID from webhook
- `fingerprint` - Unique alert identifier
- `alert_status` - firing/resolved
- `processing_status` - new/processing/processed/failed
- `alert_name` - Name of the alert
- `group_name` - Alert group (for recipe matching)
- `severity` - critical/warning/info
- `instance` - Instance identifier
- `prometheus` - Prometheus instance
- `labels` - JSON blob of all labels
- `counter` - Number of times seen
- `ticket_number` - Optional ticket reference
- `created_at` - Timestamp
- `updated_at` - Timestamp

## Multiple Alerts Test

Send multiple alerts in one webhook:
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "multi-test",
    "status": "firing",
    "receiver": "poundcake",
    "groupLabels": {"alertname": "MultiTest"},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
      {
        "status": "firing",
        "labels": {"alertname": "Alert1", "severity": "critical"},
        "annotations": {"summary": "First alert"},
        "startsAt": "2026-01-30T15:00:00Z",
        "fingerprint": "fp1"
      },
      {
        "status": "firing",
        "labels": {"alertname": "Alert2", "severity": "warning"},
        "annotations": {"summary": "Second alert"},
        "startsAt": "2026-01-30T15:01:00Z",
        "fingerprint": "fp2"
      },
      {
        "status": "firing",
        "labels": {"alertname": "Alert3", "severity": "info"},
        "annotations": {"summary": "Third alert"},
        "startsAt": "2026-01-30T15:02:00Z",
        "fingerprint": "fp3"
      }
    ]
  }'
```

This should create 3 separate rows in the alerts table.

## Resolved Alerts Test

Test alert resolution:
```bash
# Send firing alert
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "TestResolution"},
      "startsAt": "2026-01-30T15:00:00Z",
      "fingerprint": "resolve-test-123"
    }]
  }'

# Send resolved alert (same fingerprint)
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "resolved",
      "labels": {"alertname": "TestResolution"},
      "startsAt": "2026-01-30T15:00:00Z",
      "endsAt": "2026-01-30T15:05:00Z",
      "fingerprint": "resolve-test-123"
    }]
  }'

# Check the alert - counter should be 2, status should be resolved
curl "http://localhost:8000/api/v1/alerts?fingerprint=resolve-test-123" | jq .
```

## Common Issues

### Issue: 422 Validation Error
**Cause:** Invalid JSON structure
**Fix:** Ensure all required fields are present (status, labels, startsAt, fingerprint)

### Issue: 500 Internal Server Error
**Cause:** Database connection issue
**Fix:** Check MariaDB is healthy: `docker ps | grep mariadb`

### Issue: Alert not appearing in queries
**Cause:** Processing not complete
**Fix:** Wait 2-3 seconds after POST, check logs: `docker logs poundcake-api`

## Monitoring

Check PoundCake logs for webhook processing:
```bash
# Follow logs in real-time
docker logs -f poundcake-api | grep webhook

# Check for errors
docker logs poundcake-api 2>&1 | grep -i error

# Check processing
docker logs poundcake-api 2>&1 | grep "pre_heat"
```

## Statistics

Check system statistics:
```bash
curl http://localhost:8000/api/v1/stats | jq .
```

**Response includes:**
- `total_alerts` - Total alerts in database
- `alerts_by_processing_status` - Breakdown by status
- `alerts_by_alert_status` - firing vs resolved
- `recent_alerts` - Alerts in last 24 hours

## Integration with Recipe Processing

After webhook ingestion, trigger recipe processing:
```bash
# Process all new alerts
curl -X POST "http://localhost:8000/api/v1/alerts/process?processing_status=new"

# Process specific fingerprints
curl -X POST "http://localhost:8000/api/v1/alerts/process?fingerprints=fp1,fp2,fp3"
```

This will:
1. Match alerts to recipes by `group_name`
2. Parse recipe `task_list`
3. Create oven entries
4. Execute StackStorm workflows

---

**Ready to test!** Run `./test_webhook.sh` to get started.
