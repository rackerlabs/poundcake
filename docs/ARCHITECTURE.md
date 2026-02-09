# PoundCake Architecture v0.0.1

## Overview

PoundCake is an auto-remediation framework that bridges Prometheus Alertmanager with StackStorm. It receives alerts from Alertmanager and automatically executes remediation workflows through StackStorm.

## Design Principles

1. **Fast Response**: Webhook returns 202 immediately, processes in background
2. **Complete Audit Trail**: Track alerts from webhook to execution
3. **Stateless Design**: No Redis/Celery dependency, scales horizontally
4. **Schema Versioning**: Alembic migrations for safe upgrades
5. **Clear Separation**: PoundCake handles routing, StackStorm handles execution

## Components

### FastAPI Application
- Webhook receiver with background processing
- RESTful API for alerts and recipes management
- Health checks and metrics endpoint
- Alembic-based schema migrations

### Database (MySQL/MariaDB)
- Three main tables: recipes, alerts, ovens
- Stores alert history and execution tracking
- Managed via Alembic migrations

### StackStorm Integration
- Executes remediation workflows
- Returns execution IDs for tracking
- Requires Redis and RabbitMQ

## Database Schema

### poundcake_recipes

Defines remediation workflows and their StackStorm mappings.

```sql
CREATE TABLE poundcake_recipes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(256) UNIQUE NOT NULL,
    description TEXT,
    task_list TEXT,  
    st2_workflow_ref VARCHAR(256) NOT NULL,
    time_to_complete DATETIME,
    time_to_clear DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    INDEX idx_recipe_name (name),
    INDEX idx_recipe_st2_ref (st2_workflow_ref)
);
```

### poundcake_alerts

Stores alert data from Alertmanager webhooks.

```sql
CREATE TABLE poundcake_alerts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    req_id VARCHAR(36) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    alert_status VARCHAR(20) NOT NULL,
    processing_status VARCHAR(20) NOT NULL,
    alert_name VARCHAR(256) NOT NULL,
    severity VARCHAR(20),
    instance VARCHAR(256),
    prometheus VARCHAR(256),
    labels JSON,
    annotations JSON,
    starts_at DATETIME,
    ends_at DATETIME,
    generator_url TEXT,
    raw_data JSON,
    counter INT NOT NULL DEFAULT 1,
    ticket_number VARCHAR(100),
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    INDEX idx_alert_fingerprint (fingerprint),
    INDEX idx_alert_name (alert_name),
    INDEX idx_alert_processing_status (processing_status),
    INDEX idx_alert_req_id (req_id)
);
```

### poundcake_ovens

Executes recipes and tracks StackStorm execution status.

```sql
CREATE TABLE poundcake_ovens (
    id INT PRIMARY KEY AUTO_INCREMENT,
    req_id VARCHAR(36) NOT NULL,
    alert_id INT,
    recipe_id INT NOT NULL,
    action_id VARCHAR(100),
    action_result JSON,
    status VARCHAR(20) NOT NULL,
    started_at DATETIME,
    ended_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    FOREIGN KEY (alert_id) REFERENCES poundcake_alerts(id),
    FOREIGN KEY (recipe_id) REFERENCES poundcake_recipes(id),
    INDEX idx_oven_req_id (req_id),
    INDEX idx_oven_alert_id (alert_id),
    INDEX idx_oven_recipe_id (recipe_id),
    INDEX idx_oven_action_id (action_id),
    INDEX idx_oven_status (status)
);
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   Alertmanager                          │
│              (Prometheus component)                     │
└────────────────────┬────────────────────────────────────┘
                     │ POST /api/v1/webhook
                     ▼
┌─────────────────────────────────────────────────────────┐
│                   PoundCake API                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  FastAPI Application                              │  │
│  │  - Webhook receiver (202 immediate response)      │  │
│  │  - Background processing (pre_heat)               │  │
│  │  - Recipe/Alert/Oven management                   │  │
│  │  - Health checks & metrics                        │  │
│  └─────────────────┬─────────────────────────────────┘  │
│                    │                                     │
│  ┌─────────────────▼─────────────────────────────────┐  │
│  │        MySQL/MariaDB Database                     │  │
│  │  - poundcake_recipes (workflow definitions)       │  │
│  │  - poundcake_alerts (alert history)               │  │
│  │  - poundcake_ovens (execution tracking)           │  │
│  └─────────────────┬─────────────────────────────────┘  │
└────────────────────┼─────────────────────────────────────┘
                     │ HTTP API call
                     ▼
┌─────────────────────────────────────────────────────────┐
│                    StackStorm                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │  st2api (API Server)                              │  │
│  │  - Receives execution requests                    │  │
│  │  - Returns execution ID                           │  │
│  └─────────────────┬─────────────────────────────────┘  │
│                    │                                     │
│  ┌─────────────────▼─────────────────────────────────┐  │
│  │  Workflow Engines                                 │  │
│  │  - Orquesta, Mistral, ActionChain                │  │
│  │  - Execute remediation steps                      │  │
│  └─────────────────┬─────────────────────────────────┘  │
│                    │                                     │
│  ┌─────────────────▼─────────────────────────────────┐  │
│  │  Message Queue (RabbitMQ)                         │  │
│  │  - Task distribution                              │  │
│  └───────────────────────────────────────────────────┘  │
│                                                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Redis                                            │  │
│  │  - Coordination and locking                       │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Target Systems                             │
│         (remediation actions executed here)             │
└─────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Webhook Reception

```
Alertmanager sends POST /api/v1/webhook
                ↓
PreHeatMiddleware generates req_id: "abc-123"
                ↓
Return 202 Accepted (request_id: "abc-123")
                ↓
Background Task: pre_heat()
  - Parse alerts from payload
  - Insert/update poundcake_alerts table
  - Set processing_status = "new"
```

**Key Points:**
- Response sent BEFORE processing (under 10ms)
- Background task creates own DB session
- Alert state tracked via processing_status

### 2. Alert Processing

```
POST /api/v1/alerts/process
                ↓
Query alerts WHERE processing_status = "new"
                ↓
For each alert:
  1. determine_recipe(alert_name) returns Recipe
  2. Create Oven (req_id, alert_id, recipe_id)
  3. execute_recipe(oven, recipe, alert)
     - Call ST2 API with recipe.st2_workflow_ref
     - Store ST2 execution_id in oven.action_id
  4. Update alert.processing_status = "processing"
                ↓
Return 202 Accepted with req_ids and execution_ids
```

### 3. Recipe Execution

```python
# PoundCake calls StackStorm API
response = requests.post(
    f"{ST2_API_URL}/v1/executions",
    json={
        "action": recipe.st2_workflow_ref,
        "parameters": {
            "alert_name": alert.alert_name,
            "req_id": req_id
        }
    }
)

st2_execution_id = response.json()["id"]
```

## Request ID Tracking

The `req_id` flows through the entire system:

```
Webhook (generates req_id)
    ↓
Alert (stores req_id)
    ↓
Oven (uses alert's req_id)
    ↓
StackStorm execution (receives req_id in parameters)
```

## Recipe Matching Logic

```python
def determine_recipe(alert_name: str, db: Session):
    # 1. Try exact match
    # 2. Try pattern matching
    # 3. Fallback to default recipe
```

## Deployment Patterns

### Docker Compose

Single-host deployment with all services.

### Kubernetes/Helm

Production deployment with horizontal scaling.

### Configuration

```bash
# Database
DATABASE_URL=mysql+pymysql://user:pass@host/db

# StackStorm
ST2_API_URL=http://stackstorm-api:9101/v1
ST2_API_KEY=your-api-key
```

## Version History

### v0.0.1 (Current)
- Alembic migrations for schema management
- FastAPI BackgroundTasks (no Celery/Redis)
- Recipe/Oven/Alert architecture
- Background webhook processing
- Complete audit trail via req_id

---

**Version:** 0.0.1  
**Last Updated:** January 23, 2026
