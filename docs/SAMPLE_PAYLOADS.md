# Sample Alertmanager Payload - Hello World Example

## Simple Hello World Alert

This is a minimal, working example you can use to test the webhook endpoint.

### cURL Command

```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"HelloWorldAlert\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {
      "alertname": "HelloWorldAlert"
    },
    "commonLabels": {
      "alertname": "HelloWorldAlert",
      "severity": "info",
      "environment": "test"
    },
    "commonAnnotations": {
      "summary": "Hello World Test Alert",
      "description": "This is a test alert to verify the webhook is working correctly"
    },
    "externalURL": "http://alertmanager:9093",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "HelloWorldAlert",
          "severity": "info",
          "instance": "test-server:8080",
          "environment": "test",
          "team": "platform"
        },
        "annotations": {
          "summary": "Hello World Test Alert",
          "description": "This is a test alert to verify the webhook is working correctly",
          "runbook_url": "https://docs.example.com/runbooks/hello-world"
        },
        "startsAt": "2026-01-09T21:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph?g0.expr=up",
        "fingerprint": "hello-world-test-12345"
      }
    ]
  }'
```

### Expected Response

```json
{
  "status": "accepted",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "alerts_received": 1,
  "task_ids": ["abc123-task-id"],
  "message": "Successfully received and queued 1 alerts"
}
```

### What Happens

1. **API receives the webhook**
   - Creates/updates alert in database
   - Queues Celery task for processing
   - Returns 202 Accepted immediately

2. **Celery worker processes the alert**
   - Logs: "Processing alert: hello-world-test-12345"
   - Logs: "Alert processing logic for: HelloWorldAlert"
   - Updates processing status to "completed"

3. **You can check the results**
   ```bash
   # View the alert
   curl http://localhost:8000/api/v1/alerts/hello-world-test-12345
   
   # View all alerts
   curl http://localhost:8000/api/v1/alerts
   
   # View Celery task status
   curl http://localhost:8000/api/v1/tasks/{task_id}
   
   # Check Flower dashboard
   open http://localhost:5555
   ```

## More Complex Example - Multiple Alerts

Test with multiple alerts in one webhook:

```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{job=\"test\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {
      "job": "test"
    },
    "commonLabels": {
      "job": "test",
      "environment": "production"
    },
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "HighCPU",
          "severity": "warning",
          "instance": "server-01:9100",
          "job": "test"
        },
        "annotations": {
          "summary": "High CPU usage detected",
          "description": "CPU usage is above 80% for 5 minutes"
        },
        "startsAt": "2026-01-09T21:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph",
        "fingerprint": "cpu-alert-001"
      },
      {
        "status": "firing",
        "labels": {
          "alertname": "HighMemory",
          "severity": "warning",
          "instance": "server-01:9100",
          "job": "test"
        },
        "annotations": {
          "summary": "High memory usage detected",
          "description": "Memory usage is above 90% for 5 minutes"
        },
        "startsAt": "2026-01-09T21:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph",
        "fingerprint": "memory-alert-001"
      },
      {
        "status": "firing",
        "labels": {
          "alertname": "DiskSpaceLow",
          "severity": "critical",
          "instance": "server-01:9100",
          "job": "test"
        },
        "annotations": {
          "summary": "Disk space is running low",
          "description": "Disk usage is above 95%"
        },
        "startsAt": "2026-01-09T21:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph",
        "fingerprint": "disk-alert-001"
      }
    ]
  }'
```

## Resolved Alert Example

Test a resolved alert (when issue is fixed):

```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"HelloWorldAlert\"}",
    "truncatedAlerts": 0,
    "status": "resolved",
    "receiver": "webhook",
    "groupLabels": {
      "alertname": "HelloWorldAlert"
    },
    "commonLabels": {
      "alertname": "HelloWorldAlert",
      "severity": "info"
    },
    "commonAnnotations": {
      "summary": "Hello World Alert Resolved"
    },
    "externalURL": "http://alertmanager:9093",
    "alerts": [
      {
        "status": "resolved",
        "labels": {
          "alertname": "HelloWorldAlert",
          "severity": "info",
          "instance": "test-server:8080"
        },
        "annotations": {
          "summary": "Hello World Alert Resolved",
          "description": "The test condition has been resolved"
        },
        "startsAt": "2026-01-09T21:00:00Z",
        "endsAt": "2026-01-09T21:05:00Z",
        "generatorURL": "http://prometheus:9090/graph",
        "fingerprint": "hello-world-test-12345"
      }
    ]
  }'
```

## Testing Different Severities

```bash
# Info severity
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"InfoAlert\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {"alertname": "InfoAlert"},
    "commonLabels": {"alertname": "InfoAlert", "severity": "info"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "InfoAlert", "severity": "info", "instance": "test:9090"},
      "annotations": {"summary": "Informational alert", "description": "This is just for information"},
      "startsAt": "2026-01-09T21:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph",
      "fingerprint": "info-alert-001"
    }]
  }'

# Warning severity
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"WarningAlert\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {"alertname": "WarningAlert"},
    "commonLabels": {"alertname": "WarningAlert", "severity": "warning"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "WarningAlert", "severity": "warning", "instance": "test:9090"},
      "annotations": {"summary": "Warning level alert", "description": "Something needs attention"},
      "startsAt": "2026-01-09T21:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph",
      "fingerprint": "warning-alert-001"
    }]
  }'

# Critical severity
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"CriticalAlert\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {"alertname": "CriticalAlert"},
    "commonLabels": {"alertname": "CriticalAlert", "severity": "critical"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "CriticalAlert", "severity": "critical", "instance": "test:9090"},
      "annotations": {"summary": "Critical alert!", "description": "Immediate action required!"},
      "startsAt": "2026-01-09T21:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph",
      "fingerprint": "critical-alert-001"
    }]
  }'
```

## Complete Testing Workflow

### 1. Start the services
```bash
cd poundcake-api
docker-compose up -d
```

### 2. Check health
```bash
curl http://localhost:8000/api/v1/health
```

### 3. Send test alert
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "{}:{alertname=\"HelloWorldAlert\"}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {"alertname": "HelloWorldAlert"},
    "commonLabels": {"alertname": "HelloWorldAlert", "severity": "info"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "HelloWorldAlert", "severity": "info", "instance": "test:8080"},
      "annotations": {"summary": "Hello World!", "description": "Testing the webhook"},
      "startsAt": "2026-01-09T21:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph",
      "fingerprint": "hello-world-12345"
    }]
  }'
```

### 4. Check the alert was stored
```bash
# List all alerts
curl http://localhost:8000/api/v1/alerts

# Get specific alert
curl http://localhost:8000/api/v1/alerts/hello-world-12345
```

### 5. Check processing in logs
```bash
# API logs
docker-compose logs api | grep "hello-world"

# Worker logs
docker-compose logs worker | grep "hello-world"
```

### 6. View in Flower
```bash
# Open Flower dashboard
open http://localhost:5555

# Or check via API
curl http://localhost:8000/api/v1/stats/celery
```

### 7. Check database
```bash
docker-compose exec mariadb mariadb -upoundcake -ppoundcake poundcake -e "
  SELECT fingerprint, alert_name, severity, processing_status, created_at 
  FROM alerts 
  ORDER BY created_at DESC 
  LIMIT 5;
"
```

## JSON File Format

If you prefer to save the payload as a file:

**hello-world-alert.json:**
```json
{
  "version": "4",
  "groupKey": "{}:{alertname=\"HelloWorldAlert\"}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "webhook",
  "groupLabels": {
    "alertname": "HelloWorldAlert"
  },
  "commonLabels": {
    "alertname": "HelloWorldAlert",
    "severity": "info",
    "environment": "test"
  },
  "commonAnnotations": {
    "summary": "Hello World Test Alert",
    "description": "This is a test alert to verify the webhook is working"
  },
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HelloWorldAlert",
        "severity": "info",
        "instance": "test-server:8080",
        "environment": "test"
      },
      "annotations": {
        "summary": "Hello World Test Alert",
        "description": "This is a test alert to verify everything works"
      },
      "startsAt": "2026-01-09T21:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph",
      "fingerprint": "hello-world-12345"
    }
  ]
}
```

Then send it with:
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @hello-world-alert.json
```

## Python Example

Using Python's requests library:

```python
import requests
import json
from datetime import datetime, timezone

payload = {
    "version": "4",
    "groupKey": '{}:{alertname="HelloWorldAlert"}',
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "webhook",
    "groupLabels": {"alertname": "HelloWorldAlert"},
    "commonLabels": {"alertname": "HelloWorldAlert", "severity": "info"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [{
        "status": "firing",
        "labels": {
            "alertname": "HelloWorldAlert",
            "severity": "info",
            "instance": "test:8080"
        },
        "annotations": {
            "summary": "Hello World from Python!",
            "description": "Testing webhook with Python"
        },
        "startsAt": datetime.now(timezone.utc).isoformat(),
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph",
        "fingerprint": f"python-test-{int(datetime.now().timestamp())}"
    }]
}

response = requests.post(
    "http://localhost:8000/api/v1/webhook",
    json=payload
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

## Expected Output in Logs

When you send the hello world alert, you should see:

**API Logs:**
```
INFO: Received Alertmanager webhook with 1 alerts request_id=...
INFO: Created new alert: hello-world-12345
INFO: Queued 1 alerts for processing
```

**Worker Logs:**
```
INFO: Processing alert: hello-world-12345
INFO: Alert processing logic for: HelloWorldAlert
INFO: Successfully processed alert: hello-world-12345
```

**Flower Dashboard:**
- Task appears in "Tasks" tab
- Status changes from PENDING → STARTED → SUCCESS
- Result shows processing details

## Troubleshooting

### Alert not appearing?
```bash
# Check API is running
curl http://localhost:8000/api/v1/health

# Check worker is running
docker-compose ps worker

# Check MariaDB connection
docker-compose exec mariadb mariadb -upoundcake -ppoundcake -e "SHOW DATABASES;"
```

### Alert stuck in "pending"?
```bash
# Check worker logs
docker-compose logs worker

# Check Celery connection
docker-compose exec worker celery -A app.tasks.celery_app:celery_app inspect active
```

### Wrong fingerprint?
The fingerprint must match exactly when querying:
```bash
# List all to see actual fingerprints
curl http://localhost:8000/api/v1/alerts | jq '.[] | {fingerprint, alert_name}'
```

## Summary

**Simplest test:**
```bash
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{"version":"4","groupKey":"{}:{}","truncatedAlerts":0,"status":"firing","receiver":"webhook","groupLabels":{},"commonLabels":{},"commonAnnotations":{},"externalURL":"http://alertmanager:9093","alerts":[{"status":"firing","labels":{"alertname":"HelloWorld","severity":"info","instance":"test:8080"},"annotations":{"summary":"Hello World!"},"startsAt":"2026-01-09T21:00:00Z","endsAt":"0001-01-01T00:00:00Z","generatorURL":"http://prometheus:9090","fingerprint":"hello-123"}]}'
```

That's it! You should get a 202 response and see the alert being processed.
