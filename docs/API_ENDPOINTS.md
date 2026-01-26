# PoundCake API Endpoints - v0.0.1

Complete list of all API endpoints and their query parameters.

## Base URL

```
http://localhost:8000
```

---

## Alert Management

### POST /api/v1/webhook

**Description:** Receive Alertmanager webhook and respond immediately with 202. Payload is processed in background.

**Request Body:** Alertmanager webhook payload (JSON)

**Query Parameters:** None

**Response:** 202 Accepted
```json
{
  "status": "accepted",
  "request_id": "uuid",
  "alerts_received": 1,
  "task_ids": [],
  "message": "Accepted 1 alerts for processing"
}
```

**Flow:**
1. Alertmanager posts to /webhook
2. PreHeatMiddleware generates req_id
3. PoundCake responds with 202 and req_id
4. Payload dispatched to pre_heat for background processing

---

### GET /api/v1/alerts

**Description:** Get alerts with optional filtering

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `req_id` | string | No | - | Filter by request ID |
| `fingerprint` | string | No | - | Filter by alert fingerprint |
| `name` | string | No | - | Filter by alert name |
| `processing_status` | string | No | - | Filter by processing status (new/processing/complete/failed) |
| `alert_status` | string | No | - | Filter by alert status (firing/resolved) |
| `severity` | string | No | - | Filter by severity |
| `limit` | int | No | 100 | Maximum number of alerts to return (max: 1000) |
| `offset` | int | No | 0 | Number of alerts to skip |

**Response:** 200 OK
```json
[
  {
    "id": 1,
    "req_id": "uuid",
    "fingerprint": "abc123",
    "alert_status": "firing",
    "processing_status": "new",
    "alert_name": "HostDown",
    "severity": "critical",
    "instance": "host1.example.com",
    "prometheus": "prometheus/kube-prometheus-stack-prometheus",
    "labels": {...},
    "counter": 1,
    "ticket_number": null,
    "created_at": "2026-01-23T12:00:00Z",
    "updated_at": "2026-01-23T12:00:00Z"
  }
]
```

**Examples:**
```bash
# Get all alerts
curl "http://localhost:8000/api/v1/alerts"

# Get alerts by fingerprint
curl "http://localhost:8000/api/v1/alerts?fingerprint=abc123"

# Get firing critical alerts
curl "http://localhost:8000/api/v1/alerts?alert_status=firing&severity=critical"

# Get alerts being processed
curl "http://localhost:8000/api/v1/alerts?processing_status=processing"

# Get alerts with pagination
curl "http://localhost:8000/api/v1/alerts?limit=50&offset=100"
```

---

### POST /api/v1/alerts/process

**Description:** Process alerts by executing their recipes. Returns 202 immediately.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `fingerprints` | array[string] | No | - | Specific fingerprints to process |
| `processing_status` | string | No | "new" | Process alerts with this status |

**Response:** 202 Accepted
```json
{
  "status": "accepted",
  "req_ids": ["uuid1", "uuid2"],
  "alerts_processed": 2,
  "execution_ids": ["st2-exec-1", "st2-exec-2"],
  "message": "Processed 2 of 2 alerts"
}
```

**Examples:**
```bash
# Process all new alerts
curl -X POST "http://localhost:8000/api/v1/alerts/process"

# Process specific alerts by fingerprint
curl -X POST "http://localhost:8000/api/v1/alerts/process?fingerprints=abc123&fingerprints=def456"

# Process failed alerts
curl -X POST "http://localhost:8000/api/v1/alerts/process?processing_status=failed"
```

---

### GET /api/v1/executions/{req_id}

**Description:** Get all executions (ovens) for a specific request ID

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `req_id` | string | Yes | Request ID from webhook |

**Query Parameters:** None

**Response:** 200 OK
```json
{
  "req_id": "uuid",
  "total_executions": 1,
  "executions": [
    {
      "oven_id": 1,
      "req_id": "uuid",
      "status": "complete",
      "recipe_name": "HostDown",
      "st2_workflow": "remediation.host_down_workflow",
      "st2_execution_id": "st2-exec-123",
      "alert_name": "HostDown",
      "started_at": "2026-01-23T12:00:00Z",
      "ended_at": "2026-01-23T12:01:00Z",
      "action_result": {...}
    }
  ]
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/executions/550e8400-e29b-41d4-a716-446655440000"
```

---

## Recipe Management

### POST /api/recipes/

**Description:** Create a new recipe

**Request Body:**
```json
{
  "name": "HostDownAlert",
  "description": "Recipe for handling host down alerts",
  "task_list": "uuid1,uuid2,uuid3",
  "st2_workflow_ref": "remediation.host_down_workflow",
  "time_to_complete": "2026-01-23T16:00:00Z",
  "time_to_clear": "2026-01-23T18:00:00Z"
}
```

**Query Parameters:** None

**Response:** 201 Created
```json
{
  "id": 1,
  "name": "HostDownAlert",
  "description": "Recipe for handling host down alerts",
  "task_list": "uuid1,uuid2,uuid3",
  "st2_workflow_ref": "remediation.host_down_workflow",
  "time_to_complete": "2026-01-23T16:00:00Z",
  "time_to_clear": "2026-01-23T18:00:00Z",
  "created_at": "2026-01-23T12:00:00Z",
  "updated_at": "2026-01-23T12:00:00Z"
}
```

---

### GET /api/recipes/

**Description:** List all recipes

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | int | No | 100 | Maximum number of recipes to return (max: 1000) |
| `offset` | int | No | 0 | Number of recipes to skip |

**Response:** 200 OK
```json
[
  {
    "id": 1,
    "name": "default",
    "description": "Default recipe",
    "st2_workflow_ref": "remediation.default_workflow",
    ...
  }
]
```

---

### GET /api/recipes/{recipe_id}

**Description:** Get a specific recipe by ID

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recipe_id` | int | Yes | Recipe ID |

**Query Parameters:** None

**Response:** 200 OK (same as POST response)

---

### GET /api/recipes/name/{recipe_name}

**Description:** Get a specific recipe by name

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recipe_name` | string | Yes | Recipe name |

**Query Parameters:** None

**Response:** 200 OK (same as POST response)

---

### PUT /api/recipes/{recipe_id}

**Description:** Update an existing recipe

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recipe_id` | int | Yes | Recipe ID |

**Request Body:** (all fields optional)
```json
{
  "name": "UpdatedName",
  "description": "Updated description",
  "st2_workflow_ref": "remediation.updated_workflow"
}
```

**Query Parameters:** None

**Response:** 200 OK

---

### DELETE /api/recipes/{recipe_id}

**Description:** Delete a recipe

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recipe_id` | int | Yes | Recipe ID |

**Query Parameters:** None

**Response:** 204 No Content

---

## Health & Statistics

### GET /api/v1/health

**Description:** Health check endpoint (checks database and StackStorm connectivity)

**Query Parameters:** None

**Response:** 200 OK
```json
{
  "status": "healthy",
  "version": "0.0.1",
  "database": "healthy",
  "stackstorm": "healthy",
  "timestamp": "2026-01-23T12:00:00Z"
}
```

---

### GET /api/v1/health/ready

**Description:** Readiness check for Kubernetes

**Query Parameters:** None

**Response:** 200 OK
```json
{
  "status": "ready"
}
```

---

### GET /api/v1/health/live

**Description:** Liveness check for Kubernetes

**Query Parameters:** None

**Response:** 200 OK
```json
{
  "status": "alive"
}
```

---

### GET /api/v1/stats

**Description:** Get system statistics

**Query Parameters:** None

**Response:** 200 OK
```json
{
  "total_alerts": 100,
  "total_recipes": 5,
  "total_executions": 80,
  "alerts_by_processing_status": {
    "new": 10,
    "processing": 5,
    "complete": 85
  },
  "alerts_by_alert_status": {
    "firing": 15,
    "resolved": 85
  },
  "executions_by_status": {
    "new": 2,
    "processing": 3,
    "complete": 75
  },
  "recent_alerts": 25
}
```

---

## StackStorm Integration

### GET /stackstorm/packs

**Description:** List StackStorm packs

**Query Parameters:** None

---

### GET /stackstorm/actions

**Description:** List StackStorm actions

**Query Parameters:** None

---

### GET /stackstorm/actions/{action_ref}

**Description:** Get specific StackStorm action

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action_ref` | string | Yes | Action reference (pack.action) |

---

### POST /stackstorm/actions

**Description:** Execute a StackStorm action

---

### PUT /stackstorm/actions/{action_ref}

**Description:** Update a StackStorm action

---

### DELETE /stackstorm/actions/{action_ref}

**Description:** Delete a StackStorm action

---

### GET /stackstorm/executions

**Description:** List StackStorm executions

---

## Prometheus Integration

### GET /prometheus/rules

**Description:** Get Prometheus rules

---

### GET /prometheus/rule-groups

**Description:** Get Prometheus rule groups

---

### GET /prometheus/metrics

**Description:** Query Prometheus metrics

---

### GET /prometheus/labels

**Description:** Get Prometheus labels

---

### GET /prometheus/label-values/{label_name}

**Description:** Get values for a specific label

---

### GET /prometheus/health

**Description:** Prometheus health check

---

### POST /prometheus/reload

**Description:** Reload Prometheus configuration

---

### POST /prometheus/rules

**Description:** Create a Prometheus rule

---

### PUT /prometheus/rules/{rule_name}

**Description:** Update a Prometheus rule

---

### DELETE /prometheus/rules/{rule_name}

**Description:** Delete a Prometheus rule

---

## Authentication

### POST /api/login

**Description:** Login endpoint (if authentication is enabled)

**Request Body:** Form data
- `username`: string
- `password`: string

---

### POST /api/logout

**Description:** Logout endpoint

---

## Metrics

### GET /metrics

**Description:** Prometheus metrics endpoint

**Query Parameters:** None

**Response:** Prometheus format

---

## Common Query Parameter Patterns

### Pagination

```bash
# Standard pagination
?limit=50&offset=100

# Default values
limit=100 (max: 1000)
offset=0
```

### Filtering

```bash
# Single filter
?name=HostDown

# Multiple filters
?alert_status=firing&severity=critical&processing_status=new

# Array parameters (for fingerprints)
?fingerprints=abc123&fingerprints=def456
```

---

## Response Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request successful |
| 201 | Created - Resource created successfully |
| 202 | Accepted - Request accepted for processing |
| 204 | No Content - Request successful, no content to return |
| 400 | Bad Request - Invalid request |
| 404 | Not Found - Resource not found |
| 500 | Internal Server Error - Server error |

---

## Complete URL Examples

### Alert Workflows

```bash
# 1. Send webhook from Alertmanager
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d @alertmanager_payload.json

# 2. Check alert status
curl "http://localhost:8000/api/v1/alerts?fingerprint=abc123"

# 3. Process alerts
curl -X POST "http://localhost:8000/api/v1/alerts/process"

# 4. Check execution history
curl "http://localhost:8000/api/v1/executions/550e8400-e29b-41d4-a716-446655440000"
```

### Recipe Management

```bash
# 1. Create recipe
curl -X POST http://localhost:8000/api/recipes/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "DiskFull",
    "st2_workflow_ref": "remediation.disk_cleanup_workflow"
  }'

# 2. List recipes
curl "http://localhost:8000/api/recipes/"

# 3. Get specific recipe
curl "http://localhost:8000/api/recipes/name/DiskFull"

# 4. Update recipe
curl -X PUT http://localhost:8000/api/recipes/1 \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description"}'

# 5. Delete recipe
curl -X DELETE "http://localhost:8000/api/recipes/1"
```

### Monitoring

```bash
# Health check
curl "http://localhost:8000/api/v1/health"

# Statistics
curl "http://localhost:8000/api/v1/stats"

# Prometheus metrics
curl "http://localhost:8000/metrics"
```

---

**Version:** 0.0.1  
**Date:** January 23, 2026  
**Status:** Production Ready
