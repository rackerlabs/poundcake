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
  "status": "created",
  "alert_id": 123,
  "message": "Alert created"
}
```

**Flow:**
1. Alertmanager posts to `/api/v1/webhook`
2. PreHeatMiddleware generates `req_id`
3. `pre_heat` parses the alert and creates/updates the alert record
4. PoundCake responds with 202 immediately

---

### GET /api/v1/alerts

**Description:** Get alerts with optional filtering

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `processing_status` | string | No | - | Filter by processing status (new/pending/processing/complete/failed) |
| `alert_status` | string | No | - | Filter by alert status (firing/resolved) |
| `req_id` | string | No | - | Filter by request ID |
| `alert_name` | string | No | - | Filter by alert name |
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
    "group_name": "HostDown",
    "severity": "critical",
    "instance": "host1.example.com",
    "prometheus": "prometheus/kube-prometheus-stack-prometheus",
    "labels": {},
    "annotations": {},
    "starts_at": "2026-01-23T12:00:00Z",
    "ends_at": null,
    "generator_url": "http://prometheus:9090",
    "counter": 1,
    "ticket_number": null,
    "raw_data": null,
    "created_at": "2026-01-23T12:00:00Z",
    "updated_at": "2026-01-23T12:00:00Z"
  }
]
```

**Examples:**
```bash
# Get all alerts
curl "http://localhost:8000/api/v1/alerts"

# Get alerts by request ID
curl "http://localhost:8000/api/v1/alerts?req_id=abc-123"

# Get firing alerts
curl "http://localhost:8000/api/v1/alerts?alert_status=firing"

# Get alerts with pagination
curl "http://localhost:8000/api/v1/alerts?limit=50&offset=100"
```

---

### GET /api/v1/alerts/{alert_id}

**Description:** Get a specific alert by ID

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `alert_id` | int | Yes | Alert ID |

**Query Parameters:** None

**Response:** 200 OK (same shape as GET /api/v1/alerts)

---

### PUT /api/v1/alerts/{alert_id}

**Description:** Update an alert (used by background services)

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `alert_id` | int | Yes | Alert ID |

**Request Body:** (all fields optional)
```json
{
  "alert_status": "resolved",
  "processing_status": "complete",
  "ends_at": "2026-01-23T12:05:00Z",
  "counter": 2,
  "ticket_number": "INC-12345"
}
```

**Response:** 200 OK (updated alert)

---

## Recipe Management

### POST /api/v1/recipes/

**Description:** Create a new recipe with ingredients

**Request Body:**
```json
{
  "name": "HostDown",
  "description": "Remediate host down alerts",
  "enabled": true,
  "ingredients": [
    {
      "task_id": "check_host",
      "task_name": "Check Host Connectivity",
      "task_order": 1,
      "is_blocking": true,
      "st2_action": "core.local",
      "parameters": { "cmd": "echo 'Step 1'" },
      "expected_time_to_completion": 10
    }
  ]
}
```

**Response:** 201 Created

---

### GET /api/v1/recipes/

**Description:** List all recipes

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | No | - | Filter by recipe name |
| `enabled` | bool | No | - | Filter by enabled status |
| `limit` | int | No | 100 | Maximum number of recipes to return (max: 1000) |
| `offset` | int | No | 0 | Number of recipes to skip |

**Response:** 200 OK

---

### GET /api/v1/recipes/{recipe_id}

**Description:** Get a specific recipe by ID (includes ingredients)

---

### GET /api/v1/recipes/by-name/{recipe_name}

**Description:** Get a specific recipe by name (includes ingredients)

---

### DELETE /api/v1/recipes/{recipe_id}

**Description:** Delete a recipe by ID

---

## Oven Management

### POST /api/v1/ovens/bake/{alert_id}

**Description:** Create ovens for an alert by matching `alert.group_name` to `recipe.name`.

**Response:** 200 OK
```json
{
  "status": "baked",
  "ovens_created": 2,
  "recipe_id": 7,
  "recipe_name": "HostDown"
}
```

---

### GET /api/v1/ovens

**Description:** List ovens with optional filtering

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `processing_status` | string | No | - | Filter by processing status (new/pending/processing/complete/failed) |
| `req_id` | string | No | - | Filter by request ID |
| `alert_id` | int | No | - | Filter by alert ID |
| `action_id` | string | No | - | Filter by StackStorm execution ID (24-char hex) |
| `limit` | int | No | 100 | Maximum number of ovens to return (max: 1000) |
| `offset` | int | No | 0 | Number of ovens to skip |

**Response:** 200 OK (includes ingredient details)

---

### PUT /api/v1/ovens/{oven_id}
### PATCH /api/v1/ovens/{oven_id}

**Description:** Update oven status, action ID, and timing fields

**Request Body:** (all fields optional)
```json
{
  "processing_status": "processing",
  "action_id": "6985306c2dd2cd3e4c48eed1",
  "st2_status": "succeeded",
  "started_at": "2026-01-23T12:00:00Z",
  "completed_at": "2026-01-23T12:01:00Z",
  "error_message": null
}
```

---

## StackStorm Bridge

### POST /api/v1/stackstorm/execute

**Description:** Execute a StackStorm action via the PoundCake API bridge

**Request Body:**
```json
{
  "action": "core.local",
  "parameters": { "cmd": "echo hello" }
}
```

**Response:** 200 OK (proxied StackStorm execution response)

---

## Health & Monitoring

### GET /api/v1/health

**Description:** Health check (DB + StackStorm)

### GET /api/v1/stats

**Description:** System statistics (alerts, recipes, ovens)

### GET /metrics

**Description:** Prometheus metrics endpoint (enabled when `metrics_enabled` is true)

---

## Auth

### POST /api/v1/auth/login

**Description:** Create a session when auth is enabled

**Request Body:**
```json
{
  "username": "admin",
  "password": "password"
}
```

**Response:** 200 OK
```json
{
  "session_id": "...",
  "username": "admin",
  "expires_at": "2026-01-23T12:00:00Z",
  "token_type": "Bearer"
}
```
