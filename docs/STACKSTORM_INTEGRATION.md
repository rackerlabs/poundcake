# StackStorm Integration Guide

## Overview

PoundCake API integrates with **StackStorm** for automated alert remediation. StackStorm executes the actual remediation actions while PoundCake tracks execution state and maintains audit trails.

## Architecture

```
Alert Received
    ↓
PoundCake API (Webhook)
    ↓
Match Custom Action Bucket (CAB)
    ↓
For each step in workflow:
    ├─> Create action_executions record
    ├─> Call StackStorm API
    ├─> StackStorm executes action
    ├─> Track st2_execution_id
    └─> Update action_executions with results
```

## Database Schema

### Actions Table

StackStorm-specific fields:

```sql
- st2_action_ref      VARCHAR(200)  -- StackStorm action reference (e.g., "core.local")
- st2_pack            VARCHAR(100)  -- StackStorm pack name  
- st2_parameters      JSON          -- Parameter mapping to StackStorm
- use_stackstorm      BOOLEAN       -- Execute via StackStorm (vs local)
```

**Example:**
```sql
INSERT INTO actions (name, st2_action_ref, st2_pack, use_stackstorm) VALUES
('st2_linux_service_action', 'linux.service', 'linux', TRUE);
```

### Custom Action Buckets Table

Workflow-level StackStorm integration:

```sql
- st2_workflow_name   VARCHAR(200)  -- StackStorm workflow name
- st2_workflow_pack   VARCHAR(100)  -- Pack containing workflow
- st2_workflow_params JSON          -- Workflow parameters
- use_stackstorm      BOOLEAN       -- Use ST2 workflow vs individual actions
```

### Action Executions Table

Tracks StackStorm execution state:

```sql
- st2_execution_id             VARCHAR(100)  -- StackStorm execution ID
- st2_liveaction_id            VARCHAR(100)  -- StackStorm liveaction ID
- st2_action_execution_status  VARCHAR(50)   -- ST2 status
- st2_result                   JSON          -- Result from ST2
- executed_via_stackstorm      BOOLEAN       -- Was this run via ST2?
```

## Integration Modes

### Mode 1: Individual Actions via StackStorm

Each action in a workflow is executed via StackStorm.

**Workflow:**
```
Step 1: st2_network_ping (ST2: network.ping)
Step 2: st2_linux_service_action (ST2: linux.service restart)
Step 3: st2_slack_post_message (ST2: slack.post_message)
```

**Database:**
- `custom_action_buckets.use_stackstorm = FALSE`
- Each `action.use_stackstorm = TRUE`
- Individual ST2 execution per step

### Mode 2: Entire Workflow via StackStorm

The complete workflow is a StackStorm workflow/action-chain.

**Workflow:**
```
custom_action_bucket: "host_down_remediation"
  st2_workflow_name: "remediation.host_down"
  st2_workflow_pack: "remediation"
  use_stackstorm: TRUE
```

**Database:**
- `custom_action_buckets.use_stackstorm = TRUE`
- Single ST2 execution for entire workflow
- Individual steps tracked for audit

### Mode 3: Hybrid

Mix of StackStorm and local actions.

**Workflow:**
```
Step 1: Local ping test
Step 2: st2_linux_service_action (StackStorm)
Step 3: Local log_event
```

## StackStorm Action Mapping

### Core Pack Actions

| PoundCake Action | StackStorm Ref | Description |
|-----------------|----------------|-------------|
| st2_core_local | core.local | Execute local shell command |
| st2_core_remote | core.remote | Execute remote shell command |
| st2_core_http | core.http | Make HTTP request |

### Linux Pack Actions

| PoundCake Action | StackStorm Ref | Description |
|-----------------|----------------|-------------|
| st2_linux_service_action | linux.service | Control systemd services |
| st2_linux_check_loadavg | linux.check_loadavg | Check system load |
| st2_linux_check_diskspace | linux.check_diskspace | Check disk space |

### Network Pack Actions

| PoundCake Action | StackStorm Ref | Description |
|-----------------|----------------|-------------|
| st2_network_ping | network.ping | Ping host |
| st2_network_port_check | network.port_check | Check if port is open |

### Notification Pack Actions

| PoundCake Action | StackStorm Ref | Description |
|-----------------|----------------|-------------|
| st2_slack_post_message | slack.post_message | Send Slack notification |
| st2_email_send | email.send | Send email |

## Parameter Mapping

### Template Variables

Actions support Jinja2-style template variables:

```json
{
  "action": "st2_linux_service_action",
  "st2_parameters": {
    "hosts": "{{alert.instance}}",
    "service": "{{parameters.service_name}}",
    "action": "restart"
  }
}
```

Available variables:
- `{{alert.instance}}` - Alert instance
- `{{alert.alert_name}}` - Alert name
- `{{alert.severity}}` - Alert severity
- `{{alert.labels.KEY}}` - Alert labels
- `{{parameters.KEY}}` - Step parameters
- `{{config.KEY}}` - Configuration values

### Example: Service Restart

**PoundCake CAB Step:**
```json
{
  "action_id": 5,
  "step_order": 1,
  "parameters": {
    "service_name": "nginx"
  }
}
```

**StackStorm Execution:**
```json
{
  "action": "linux.service",
  "parameters": {
    "hosts": "server-01:9100",  // from alert.instance
    "service": "nginx",           // from parameters
    "action": "restart"
  }
}
```

## Setup Instructions

### 1. Initialize Database with StackStorm Support

```bash
python api/scripts/init_database.py
```

This creates tables with StackStorm integration fields.

### 2. Seed StackStorm Actions

```bash
python api/scripts/seed_stackstorm_actions.py
```

This adds pre-configured StackStorm actions:
- 9 StackStorm-integrated actions
- Mapped to common ST2 packs
- Ready to use in workflows

### 3. Configure StackStorm Connection

**Environment Variables:**
```bash
# .env
ST2_API_URL=https://st2.example.com/api
ST2_AUTH_URL=https://st2.example.com/auth
ST2_API_KEY=your_api_key_here
ST2_STREAM_URL=wss://st2.example.com/stream
```

### 4. Create StackStorm-Enabled Workflow

**SQL:**
```sql
INSERT INTO custom_action_buckets 
(name, alert_name_pattern, use_stackstorm, st2_workflow_name, st2_workflow_pack)
VALUES 
('st2_host_down', 'HostDown', TRUE, 'remediation.host_down', 'remediation');
```

**Or use individual ST2 actions:**
```sql
INSERT INTO custom_action_buckets 
(name, alert_name_pattern, use_stackstorm)
VALUES 
('host_down_workflow', 'HostDown', FALSE);

INSERT INTO custom_action_bucket_steps 
(bucket_id, action_id, step_order, parameters)
VALUES 
(1, 5, 1, '{"service_name": "nginx"}'),  -- st2_linux_service_action
(1, 6, 2, '{"channel": "#alerts"}');      -- st2_slack_post_message
```

## Execution Flow

### Step-by-Step

**1. Alert Received:**
```bash
curl -X POST /api/v1/webhook -d '{
  "alerts": [{
    "labels": {"alertname": "HostDown", "instance": "server-01:9100"},
    "status": "firing"
  }]
}'
```

**2. PoundCake Processing:**
- Generate `request_id`
- Create `api_calls` record
- Create `alerts` record
- Match workflow: "host_down_workflow"

**3. For Each Step:**

**Step 1: Execute via StackStorm**
```python
# Create action_executions record
execution = ActionExecution(
    request_id="abc-123",
    alert_id=1,
    bucket_id=1,
    action_id=5,  # st2_linux_service_action
    step_order=1,
    status="pending",
    parameters={"service_name": "nginx"},
    executed_via_stackstorm=True
)

# Call StackStorm API
import requests
st2_response = requests.post(
    f"{ST2_API_URL}/executions",
    headers={"St2-Api-Key": ST2_API_KEY},
    json={
        "action": "linux.service",
        "parameters": {
            "hosts": "server-01",
            "service": "nginx",
            "action": "restart"
        }
    }
)

# Update execution record
execution.st2_execution_id = st2_response["id"]
execution.st2_liveaction_id = st2_response["liveaction"]["id"]
execution.status = "running"
```

**4. Poll StackStorm for Status:**
```python
# Poll ST2 execution
st2_status = requests.get(
    f"{ST2_API_URL}/executions/{execution.st2_execution_id}",
    headers={"St2-Api-Key": ST2_API_KEY}
)

# Update execution
execution.st2_action_execution_status = st2_status["status"]  # succeeded/failed
execution.st2_result = st2_status["result"]
execution.status = "success" if st2_status["status"] == "succeeded" else "failure"
execution.completed_at = datetime.utcnow()
```

**5. Continue to Next Step**

## Querying Execution Data

### Get StackStorm Execution Details

```sql
SELECT 
    ae.request_id,
    ae.step_order,
    a.name as action_name,
    a.st2_action_ref,
    ae.st2_execution_id,
    ae.st2_action_execution_status,
    ae.status,
    ae.st2_result
FROM action_executions ae
JOIN actions a ON ae.action_id = a.id
WHERE ae.executed_via_stackstorm = TRUE
  AND ae.request_id = 'abc-123'
ORDER BY ae.step_order;
```

### Get Failed StackStorm Executions

```sql
SELECT 
    ae.st2_execution_id,
    a.name,
    ae.error_message,
    ae.st2_result,
    ae.created_at
FROM action_executions ae
JOIN actions a ON ae.action_id = a.id
WHERE ae.executed_via_stackstorm = TRUE
  AND ae.status = 'failure'
ORDER BY ae.created_at DESC
LIMIT 10;
```

### Get All Executions for ST2 Execution ID

```sql
SELECT * FROM action_executions
WHERE st2_execution_id = '5f9e8a7b6c5d4e3f2a1b0c9d';
```

## StackStorm Webhook Integration

StackStorm can send execution updates back to PoundCake.

### Configure ST2 Webhook

**In StackStorm (st2.conf):**
```yaml
[webhook]
host = poundcake-api.example.com
port = 8000
url = /api/v1/stackstorm/webhook
```

### PoundCake Webhook Endpoint

**POST /api/v1/stackstorm/webhook**

Receives ST2 execution status updates:

```json
{
  "execution_id": "5f9e8a7b6c5d4e3f2a1b0c9d",
  "status": "succeeded",
  "result": {
    "stdout": "Service restarted successfully",
    "return_code": 0
  },
  "liveaction": {
    "id": "5f9e8a7b6c5d4e3f2a1b0c9e"
  }
}
```

**PoundCake Handler:**
```python
@router.post("/stackstorm/webhook")
async def receive_st2_webhook(webhook: ST2WebhookPayload, db: Session):
    # Find execution by ST2 execution ID
    execution = db.query(ActionExecution).filter(
        ActionExecution.st2_execution_id == webhook.execution_id
    ).first()
    
    if execution:
        execution.st2_action_execution_status = webhook.status
        execution.st2_result = webhook.result
        execution.status = map_st2_status(webhook.status)
        execution.completed_at = datetime.utcnow()
        db.commit()
```

## Monitoring & Debugging

### Check StackStorm Connection

```bash
curl -H "St2-Api-Key: $ST2_API_KEY" \
     https://st2.example.com/api/v1/actions
```

### View Action Execution in StackStorm

```bash
st2 execution get 5f9e8a7b6c5d4e3f2a1b0c9d
```

### Cross-Reference PoundCake and StackStorm

**In PoundCake:**
```sql
SELECT st2_execution_id FROM action_executions 
WHERE request_id = 'abc-123' AND step_order = 1;
-- Returns: 5f9e8a7b6c5d4e3f2a1b0c9d
```

**In StackStorm:**
```bash
st2 execution get 5f9e8a7b6c5d4e3f2a1b0c9d
```

### Common Issues

**1. StackStorm Action Not Found**
```
Error: Action 'linux.service' not found
```
**Solution:** Install StackStorm pack:
```bash
st2 pack install linux
```

**2. Authentication Failed**
```
Error: Unauthorized (401)
```
**Solution:** Generate API key:
```bash
st2 apikey create -k -m '{"used_by": "poundcake"}'
```

**3. Parameter Mismatch**
```
Error: Required parameter 'hosts' missing
```
**Solution:** Check st2_parameters mapping in action definition.

## Best Practices

### 1. Use StackStorm for All Remediation

**Good:**
```sql
-- All remediation via StackStorm
INSERT INTO actions (name, use_stackstorm, st2_action_ref)
VALUES ('restart_service', TRUE, 'linux.service');
```

**Bad:**
```sql
-- Mix of local and StackStorm for same task
INSERT INTO actions (name, use_stackstorm)
VALUES ('restart_service', FALSE);  -- Confusing!
```

### 2. Track Execution IDs

Always store ST2 execution IDs for debugging:

```python
execution.st2_execution_id = st2_response["id"]
execution.st2_liveaction_id = st2_response["liveaction"]["id"]
```

### 3. Handle Async Execution

StackStorm actions are async. Poll for status:

```python
while execution.status == "running":
    time.sleep(5)
    st2_status = get_st2_execution_status(execution.st2_execution_id)
    update_execution_status(execution, st2_status)
```

### 4. Map StackStorm Status

```python
def map_st2_status(st2_status):
    mapping = {
        "requested": "pending",
        "scheduled": "pending",
        "running": "running",
        "succeeded": "success",
        "failed": "failure",
        "timeout": "timeout",
        "abandoned": "failure",
        "canceling": "running",
        "canceled": "skipped"
    }
    return mapping.get(st2_status, "unknown")
```

### 5. Store Full ST2 Result

```python
execution.st2_result = {
    "stdout": st2_response["result"]["stdout"],
    "stderr": st2_response["result"]["stderr"],
    "return_code": st2_response["result"]["return_code"],
    "execution_time": st2_response["elapsed_seconds"]
}
```

## Example: Complete Integration

### 1. Define StackStorm Action in PoundCake

```sql
INSERT INTO actions (
    name, 
    description,
    action_type,
    st2_action_ref,
    st2_pack,
    use_stackstorm,
    st2_parameters
) VALUES (
    'restart_nginx',
    'Restart nginx service via StackStorm',
    'stackstorm',
    'linux.service',
    'linux',
    TRUE,
    '{"hosts": "{{alert.instance}}", "service": "nginx", "action": "restart"}'
);
```

### 2. Create Workflow

```sql
INSERT INTO custom_action_buckets (name, alert_name_pattern)
VALUES ('nginx_down_auto_restart', 'NginxDown');

INSERT INTO custom_action_bucket_steps (bucket_id, action_id, step_order)
VALUES (1, 1, 1);  -- restart_nginx action
```

### 3. Alert Triggers Workflow

```json
{
  "alerts": [{
    "labels": {"alertname": "NginxDown", "instance": "web-01:9100"}
  }]
}
```

### 4. PoundCake Calls StackStorm

```python
# PoundCake executes
execution = create_action_execution(...)
st2_exec = trigger_stackstorm_action(
    action_ref="linux.service",
    parameters={
        "hosts": "web-01",
        "service": "nginx",
        "action": "restart"
    }
)
execution.st2_execution_id = st2_exec["id"]
```

### 5. Track in Database

```sql
SELECT * FROM action_executions WHERE request_id = 'abc-123';
```

Output:
```
request_id | action_id | st2_execution_id              | status  | st2_result
-----------|-----------|-------------------------------|---------|------------
abc-123    | 1         | 5f9e8a7b6c5d4e3f2a1b0c9d     | success | {"return_code": 0, ...}
```

## Summary

### Integration Benefits

**Leverage StackStorm:**
- ✅ Mature remediation platform
- ✅ Large ecosystem of packs
- ✅ Visual workflow builder
- ✅ RBAC and security

**Maintain PoundCake:**
- ✅ Alert ingestion and matching
- ✅ Workflow orchestration
- ✅ Complete audit trail with request_id
- ✅ API for management

### Data Flow

```
Prometheus → Alertmanager → PoundCake API → StackStorm
                                  ↓              ↓
                             Database      Executes Actions
                             (Audit)       (Remediation)
```

### Key Tables

- **actions**: Maps to ST2 actions (st2_action_ref)
- **custom_action_buckets**: Can map to ST2 workflows (st2_workflow_name)
- **action_executions**: Tracks ST2 executions (st2_execution_id)

This architecture provides the best of both worlds: PoundCake's alert processing and audit trail with StackStorm's powerful remediation capabilities.
