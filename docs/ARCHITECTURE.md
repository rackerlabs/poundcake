# Simplified Architecture: PoundCake + StackStorm

## The Problem

Our initial design was too complex:
- We created `actions` table → StackStorm already has `action_db`
- We created `custom_action_buckets` → StackStorm already has workflows
- We created `custom_action_bucket_steps` → StackStorm workflows define steps
- **We were duplicating StackStorm's workflow engine!**

## The Solution: Radically Simplified

**PoundCake's ONLY job:**
1. Receive Alertmanager webhooks
2. Generate unique `request_id` for tracking
3. Store alert data
4. Trigger StackStorm (passing `request_id`)
5. Track the link: `request_id` ↔ `st2_execution_id`

**StackStorm's job:**
1. Define ALL workflows (ActionChains, Mistral, Orquesta)
2. Define ALL actions  
3. Execute remediation
4. Store results

## Database Schema

### PoundCake Tables (Only 3!)

**1. `poundcake_api_calls`**
```sql
id, request_id (unique), method, path, 
headers, body, status_code, created_at
```
Tracks webhook requests with unique request_id.

**2. `poundcake_alerts`**
```sql
id, api_call_id, fingerprint, alert_name, 
severity, labels, st2_rule_matched, created_at
```
Stores Alertmanager alert data.

**3. `poundcake_st2_execution_link`**
```sql
id, request_id, alert_id, st2_execution_id,
st2_rule_ref, st2_action_ref, created_at
```
**This is the key table!** Links PoundCake request_id to StackStorm execution_id.

### StackStorm Tables (ST2 Manages)

- `action_db` - Actions (python, shell, http, etc.)
- `execution_db` - Completed executions
- `liveaction_db` - Running executions  
- `rule_db` - Rules (trigger conditions)
- `workflow_db` - Workflows/ActionChains
- `trigger_db` - Trigger definitions

## Architecture Diagram

```
┌────────────────────────────────────────────────┐
│          MariaDB Database                      │
├────────────────────────────────────────────────┤
│                                                │
│ PoundCake (3 tables):                          │
│   ├─ poundcake_api_calls (request_id)         │
│   ├─ poundcake_alerts                          │
│   └─ poundcake_st2_execution_link ←──┐        │
│                                       │        │
│ StackStorm (managed by ST2):         │        │
│   ├─ action_db                        │        │
│   ├─ execution_db ←───────────────────┘        │
│   ├─ rule_db                                   │
│   └─ workflow_db                               │
└────────────────────────────────────────────────┘
```

## Data Flow

### Step 1: Alert Received
```
POST /api/v1/webhook (Alertmanager)
  ↓
PoundCake generates request_id: "abc-123"
  ↓
Create poundcake_api_calls (request_id: abc-123)
Create poundcake_alerts (alert data)
```

### Step 2: Trigger StackStorm
```python
# PoundCake calls StackStorm API
response = requests.post("http://st2api:9101/v1/executions", json={
    "action": "remediation.host_down_workflow",  # ST2 workflow
    "parameters": {
        "alert_name": alert.alert_name,
        "instance": alert.instance,
        "poundcake_request_id": "abc-123"  # ← Pass our request_id
    }
})

st2_execution_id = response.json()["id"]  # e.g., "5f9e8a7b..."
```

### Step 3: Store Link
```python
# Create simple link
link = ST2ExecutionLink(
    request_id="abc-123",
    alert_id=42,
    st2_execution_id="5f9e8a7b...",
    st2_rule_ref="remediation.host_down_rule",
    st2_action_ref="remediation.host_down_workflow"
)
db.add(link)
db.commit()
```

### Step 4: StackStorm Executes
```
StackStorm:
  ├─ Receives execution request
  ├─ Queues via RabbitMQ
  ├─ st2actionrunner executes workflow
  ├─ Workflow runs multiple actions
  ├─ Stores results in execution_db
  └─ Status: succeeded/failed
```

### Step 5: Query Complete History
```sql
SELECT 
    api.request_id,
    alert.alert_name,
    alert.severity,
    link.st2_execution_id,
    exec.action as st2_workflow,
    exec.status,
    exec.result,
    exec.start_timestamp,
    exec.end_timestamp
FROM poundcake_api_calls api
JOIN poundcake_alerts alert ON alert.api_call_id = api.id
JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
JOIN execution_db exec ON exec.id = link.st2_execution_id
WHERE api.request_id = 'abc-123';
```

Output:
```
request_id | alert_name | st2_workflow              | status    | result
-----------|------------|---------------------------|-----------|--------
abc-123    | HostDown   | remediation.host_down_wf  | succeeded | {...}
```

## StackStorm Workflow Example

Define workflows entirely in StackStorm:

```yaml
# /opt/stackstorm/packs/remediation/actions/workflows/host_down.yaml
version: 1.0
description: Host down remediation workflow

input:
  - alert_name
  - instance  
  - poundcake_request_id  # ← We pass this

tasks:
  ping_test:
    action: network.ping
    input:
      target: <% ctx().instance %>
      count: 5
    next:
      - when: <% failed() %>
        do: notify_team
  
  notify_team:
    action: slack.post_message
    input:
      channel: "#alerts"
      message: |
        Alert: <% ctx().alert_name %>
        Instance: <% ctx().instance %>
        PoundCake Request: <% ctx().poundcake_request_id %>
        Ping test failed - host is down
```

Register in StackStorm:
```bash
st2 action create /opt/stackstorm/packs/remediation/actions/workflows/host_down.yaml
```

## Benefits

### Simplicity
- ✅ **Only 3 PoundCake tables** (was 7+)
- ✅ **No workflow duplication**
- ✅ **No action duplication**
- ✅ **No maintenance of workflow engine**

### Use StackStorm's Full Power
- ✅ **ActionChains** - Simple sequential workflows
- ✅ **Mistral workflows** - Complex workflows with branching
- ✅ **Orquesta workflows** - Native ST2 workflow engine
- ✅ **All ST2 action runners** - python, shell, http, ansible, etc.
- ✅ **ST2 UI** - Visual workflow editor
- ✅ **ST2 Pack Exchange** - 100+ community packs

### Complete Audit Trail
- ✅ **request_id tracks everything**
- ✅ **Query across systems** via simple link table
- ✅ **Full ST2 execution details** in execution_db
- ✅ **Alert context** in poundcake_alerts

### Operational Benefits
- ✅ **One workflow system** (StackStorm)
- ✅ **One UI** for workflows (ST2 web UI)
- ✅ **Standard ST2 tools** (st2 CLI, API)
- ✅ **Leverage ST2 community** (packs, workflows, actions)

## Example Queries

### Get Complete Remediation History
```sql
SELECT 
    api.request_id,
    api.created_at as webhook_received,
    alert.alert_name,
    alert.severity,
    alert.instance,
    link.st2_execution_id,
    exec.action as st2_workflow,
    exec.status as execution_status,
    exec.start_timestamp as started,
    exec.end_timestamp as completed,
    TIMESTAMPDIFF(SECOND, exec.start_timestamp, exec.end_timestamp) as duration_sec
FROM poundcake_api_calls api
JOIN poundcake_alerts alert ON alert.api_call_id = api.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
LEFT JOIN execution_db exec ON exec.id = link.st2_execution_id
ORDER BY api.created_at DESC
LIMIT 20;
```

### Get Workflow Success Rates
```sql
SELECT 
    exec.action as workflow,
    COUNT(*) as total_executions,
    SUM(CASE WHEN exec.status = 'succeeded' THEN 1 ELSE 0 END) as succeeded,
    SUM(CASE WHEN exec.status = 'failed' THEN 1 ELSE 0 END) as failed,
    ROUND(AVG(TIMESTAMPDIFF(SECOND, exec.start_timestamp, exec.end_timestamp)), 2) as avg_duration_sec
FROM execution_db exec
JOIN poundcake_st2_execution_link link ON exec.id = link.st2_execution_id
GROUP BY exec.action
ORDER BY total_executions DESC;
```

### Get All Executions for Alert
```sql
SELECT 
    alert.fingerprint,
    alert.alert_name,
    api.request_id,
    link.st2_execution_id,
    exec.action,
    exec.status
FROM poundcake_alerts alert
JOIN poundcake_api_calls api ON alert.api_call_id = api.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
LEFT JOIN execution_db exec ON exec.id = link.st2_execution_id
WHERE alert.fingerprint = 'your-alert-fingerprint';
```

## Creating Workflows in StackStorm

### Option 1: ActionChain (Simple)
```yaml
# /opt/stackstorm/packs/remediation/actions/chains/simple_restart.yaml
chain:
  - name: "notify_start"
    ref: "slack.post_message"
    parameters:
      channel: "#alerts"
      message: "Starting service restart for {{instance}}"
  
  - name: "restart_service"
    ref: "linux.service"
    parameters:
      hosts: "{{instance}}"
      service: "nginx"
      action: "restart"
  
  - name: "notify_complete"
    ref: "slack.post_message"
    parameters:
      channel: "#alerts"
      message: "Service restart completed"
```

### Option 2: Orquesta Workflow (Complex)
```yaml
# /opt/stackstorm/packs/remediation/actions/workflows/advanced.yaml
version: 1.0

input:
  - instance
  - alert_name

tasks:
  check_health:
    action: network.ping
    input:
      target: <% ctx().instance %>
    next:
      - when: <% succeeded() %>
        do: service_healthy
      - when: <% failed() %>
        do: restart_service
  
  service_healthy:
    action: slack.post_message
    input:
      message: "Host is healthy, no action needed"
  
  restart_service:
    action: linux.service
    input:
      hosts: <% ctx().instance %>
      action: restart
    next:
      - do: verify_restart
  
  verify_restart:
    action: network.ping
    input:
      target: <% ctx().instance %>
```

## Setup Instructions

### 1. Install StackStorm with MariaDB
```bash
# Install StackStorm
curl -sSL https://packages.stackstorm.com/install.sh | bash

# Configure for MariaDB
sudo vi /etc/st2/st2.conf
# Set: backend = mysql

# Initialize ST2 database
sudo st2-setup-db

# Start services
sudo st2ctl start
```

### 2. Initialize PoundCake (Simplified)
```bash
cd poundcake-api

# Initialize database (creates 3 tables only)
python src/app/scripts/init_simple_database.py

# Start services
docker-compose up -d
```

### 3. Create StackStorm Workflows
```bash
# Create pack directory
sudo mkdir -p /opt/stackstorm/packs/remediation/actions/workflows

# Create workflow YAML files
# (See examples above)

# Register with StackStorm
st2 action create /opt/stackstorm/packs/remediation/actions/workflows/*.yaml

# Verify
st2 action list --pack remediation
```

### 4. Create StackStorm Rules
```yaml
# /opt/stackstorm/packs/remediation/rules/host_down.yaml
name: host_down_rule
pack: remediation
enabled: true

trigger:
  type: core.st2.webhook
  parameters:
    url: poundcake_alert

criteria:
  trigger.body.alert_name:
    pattern: "HostDown"

action:
  ref: remediation.host_down_workflow
  parameters:
    alert_name: "{{ trigger.body.alert_name }}"
    instance: "{{ trigger.body.instance }}"
    poundcake_request_id: "{{ trigger.body.request_id }}"
```

Register:
```bash
st2 rule create /opt/stackstorm/packs/remediation/rules/host_down.yaml
```

### 5. Configure PoundCake to Trigger ST2
```python
# In PoundCake webhook handler
def process_alert(alert_data, request_id):
    # Store alert
    alert = Alert(...)
    db.add(alert)
    db.commit()
    
    # Trigger StackStorm
    response = requests.post(
        f"{ST2_API_URL}/webhooks/poundcake_alert",
        json={
            "alert_name": alert.alert_name,
            "instance": alert.instance,
            "severity": alert.severity,
            "request_id": request_id  # ← Pass request_id
        },
        headers={"St2-Api-Key": ST2_API_KEY}
    )
    
    # Store link
    if response.status_code == 200:
        st2_data = response.json()
        link = ST2ExecutionLink(
            request_id=request_id,
            alert_id=alert.id,
            st2_execution_id=st2_data["execution_id"]
        )
        db.add(link)
        db.commit()
```

## Comparison: Old vs New

### Old Architecture (Complex)
```
PoundCake Tables:
  ├─ poundcake_api_calls
  ├─ poundcake_alerts
  ├─ actions (duplicate of ST2)
  ├─ custom_action_buckets (duplicate of ST2)
  ├─ custom_action_bucket_steps (duplicate of ST2)
  ├─ poundcake_st2_action_extensions
  ├─ poundcake_st2_rule_extensions
  └─ poundcake_st2_execution_extensions

Total: 8 tables
```

### New Architecture (Simple)
```
PoundCake Tables:
  ├─ poundcake_api_calls
  ├─ poundcake_alerts
  └─ poundcake_st2_execution_link

Total: 3 tables
```

**Reduction: 8 → 3 tables (62% fewer!)**

## Migration Path

If you have the old complex architecture:

```sql
-- Export data
SELECT * FROM poundcake_st2_execution_extensions;

-- Drop old tables
DROP TABLE IF EXISTS poundcake_st2_execution_extensions;
DROP TABLE IF EXISTS poundcake_st2_rule_extensions;
DROP TABLE IF EXISTS poundcake_st2_action_extensions;
DROP TABLE IF EXISTS custom_action_bucket_steps;
DROP TABLE IF EXISTS custom_action_buckets;
DROP TABLE IF EXISTS actions;

-- Create new simple table
CREATE TABLE poundcake_st2_execution_link (
  id INT PRIMARY KEY AUTO_INCREMENT,
  request_id VARCHAR(36) NOT NULL,
  alert_id INT,
  st2_execution_id VARCHAR(100) NOT NULL,
  st2_rule_ref VARCHAR(200),
  st2_action_ref VARCHAR(200),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_request_id (request_id),
  INDEX idx_st2_exec_id (st2_execution_id)
);

-- Migrate data (if needed)
INSERT INTO poundcake_st2_execution_link 
  (request_id, alert_id, st2_execution_id)
SELECT request_id, alert_id, st2_execution_id 
FROM old_execution_extensions_backup;
```

## Summary

**What We Removed:**
- ❌ Actions table
- ❌ Custom Action Buckets (CABs)
- ❌ Action steps
- ❌ Complex extension tables

**What We Kept:**
- ✅ Webhook ingestion (PoundCake's job)
- ✅ request_id tracking (our unique value)
- ✅ Alert data storage
- ✅ Simple link to ST2 executions

**What We Gained:**
- ✅ 62% fewer tables (8 → 3)
- ✅ No workflow duplication
- ✅ Full ST2 power (ActionChains, Mistral, Orquesta)
- ✅ ST2 UI for workflow management
- ✅ ST2 Pack Exchange access
- ✅ Much simpler maintenance

**PoundCake's Role:**
Just a thin, tracking layer over StackStorm with request_id auditing.

**StackStorm's Role:**
Does ALL the workflow and action execution (what it's designed for).

This is the right architecture!
