# Migration Guide: Complex → Simple Architecture

## Overview

This guide helps you migrate from the complex architecture (with CABs and actions tables) to the simplified architecture (just linking to StackStorm).

## What's Changing

### Removed (Complex → Simple)

**Database Tables:**
- ❌ `actions` table
- ❌ `custom_action_buckets` table
- ❌ `custom_action_bucket_steps` table
- ❌ `poundcake_st2_action_extensions` table
- ❌ `poundcake_st2_rule_extensions` table
- ❌ `poundcake_st2_execution_extensions` table
- ❌ `poundcake_st2_webhook_extensions` table

**Code:**
- ❌ Complex CAB processing logic
- ❌ Action parameter templating
- ❌ Step-by-step execution

### Kept (Simplified)

**Database Tables:**
- ✅ `poundcake_api_calls` - Webhook tracking with request_id
- ✅ `poundcake_alerts` - Alert data
- ✅ `poundcake_st2_execution_link` - Simple link to ST2 (NEW)

**Components:**
- ✅ FastAPI webhook receiver
- ✅ Celery + Redis for async processing
- ✅ MariaDB database
- ✅ StackStorm integration

## Architecture Comparison

### Old (Complex)

```
Alert → PoundCake
         ↓
      Lookup CAB
         ↓
    Execute Actions (in CAB steps)
         ↓
   Store action_executions
         ↓
  Optionally call ST2 API for some actions
```

**Problems:**
- Duplicating ST2's workflow engine
- Maintaining two workflow systems
- Complex schema (8+ tables)

### New (Simple)

```
Alert → PoundCake
         ↓
    Store in database
         ↓
    Queue Celery task
         ↓
    Determine ST2 workflow
         ↓
    Call ST2 API (pass request_id)
         ↓
    Store link (request_id ↔ st2_execution_id)
         ↓
    ST2 executes workflow
```

**Benefits:**
- Use ST2's workflow engine (what it's designed for)
- Much simpler (3 tables)
- No duplication
- Full ST2 power (ActionChains, Mistral, Orquesta)

## Migration Steps

### Step 1: Backup Current Data

```bash
# Backup entire database
mysqldump -upoundcake -ppoundcake poundcake > \
  /backup/poundcake_before_migration_$(date +%Y%m%d).sql

# Backup specific tables
mysqldump -upoundcake -ppoundcake poundcake \
  actions \
  custom_action_buckets \
  custom_action_bucket_steps \
  action_executions \
  > /backup/old_tables_$(date +%Y%m%d).sql
```

### Step 2: Document Your Current Workflows

Before removing CABs, document them as StackStorm workflows.

**Example: Old CAB**
```
CAB: host_down_auto_fix
Steps:
  1. ping_test (action: network_ping)
  2. restart_service (action: service_restart)
  3. notify_slack (action: slack_notify)
```

**Convert to ST2 Workflow:**
```yaml
# /opt/stackstorm/packs/remediation/actions/workflows/host_down.yaml
version: 1.0
description: Host down remediation (converted from PoundCake CAB)

input:
  - instance
  - alert_name
  - poundcake_request_id

tasks:
  ping_test:
    action: network.ping
    input:
      target: <% ctx().instance %>
      count: 5
    next:
      - when: <% succeeded() %>
        publish:
          - ping_result: <% result() %>
        do: notify_success
      - when: <% failed() %>
        do: restart_service
  
  restart_service:
    action: linux.service
    input:
      hosts: <% ctx().instance %>
      service: nginx
      action: restart
    next:
      - do: notify_slack
  
  notify_slack:
    action: slack.post_message
    input:
      channel: "#alerts"
      message: |
        Alert: <% ctx().alert_name %>
        Instance: <% ctx().instance %>
        Request ID: <% ctx().poundcake_request_id %>
        Actions completed
```

Register with StackStorm:
```bash
st2 action create /opt/stackstorm/packs/remediation/actions/workflows/host_down.yaml
```

### Step 3: Stop Services

```bash
# Stop PoundCake
docker-compose down

# Stop Celery workers
# (if running outside Docker)
pkill -f "celery.*worker"
```

### Step 4: Install StackStorm (if not already)

```bash
# Install StackStorm with MariaDB
curl -sSL https://packages.stackstorm.com/install.sh | bash

# Configure for MariaDB
sudo vi /etc/st2/st2.conf
# [database]
# backend = mysql
# db_name = poundcake  # or separate 'stackstorm' database

# Initialize ST2 database
sudo st2-setup-db

# Start ST2
sudo st2ctl start
```

### Step 5: Run Database Migration

```sql
-- Connect to database
mysql -upoundcake -ppoundcake poundcake

-- Create new simple link table
CREATE TABLE IF NOT EXISTS poundcake_st2_execution_link (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL,
    alert_id INT,
    st2_execution_id VARCHAR(100) NOT NULL,
    st2_rule_ref VARCHAR(200),
    st2_action_ref VARCHAR(200),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_st2_exec_id (st2_execution_id),
    INDEX idx_alert_id (alert_id),
    FOREIGN KEY (alert_id) REFERENCES poundcake_alerts(id)
);

-- Migrate data from old execution tables (if you want history)
-- This maps old action_executions to new ST2 execution links
INSERT INTO poundcake_st2_execution_link 
    (request_id, alert_id, st2_execution_id, st2_action_ref)
SELECT 
    ae.request_id,
    NULL,  -- alert_id (may not have direct mapping)
    ae.st2_execution_id,  -- if you stored this
    a.name  -- old action name
FROM action_executions ae
LEFT JOIN actions a ON ae.action_id = a.id
WHERE ae.st2_execution_id IS NOT NULL;

-- Archive old tables (don't delete yet, in case you need them)
RENAME TABLE actions TO _archive_actions;
RENAME TABLE custom_action_buckets TO _archive_custom_action_buckets;
RENAME TABLE custom_action_bucket_steps TO _archive_custom_action_bucket_steps;
RENAME TABLE action_executions TO _archive_action_executions;

-- Drop extension tables (if using unified architecture)
DROP TABLE IF EXISTS poundcake_st2_action_extensions;
DROP TABLE IF EXISTS poundcake_st2_rule_extensions;
DROP TABLE IF EXISTS poundcake_st2_execution_extensions;
DROP TABLE IF EXISTS poundcake_st2_webhook_extensions;
```

### Step 6: Update Code

Replace old complex code with simplified version:

**Old:** `api/models/models.py` or `models_unified.py`  
**New:** `api/models/models_simple.py`

**Old:** `api/tasks/tasks.py` (complex CAB processing)  
**New:** `api/tasks/tasks_simple.py` (just trigger ST2)

**Old:** `api/api/v1/webhook.py` (complex)  
**New:** `api/api/v1/webhook_celery.py` (simple)

```bash
# Backup old code
cp api/models/models.py api/models/models_backup.py
cp api/tasks/tasks.py api/tasks/tasks_backup.py

# Use new simplified code
cp api/models/models_simple.py api/models/models.py
cp api/tasks/tasks_simple.py api/tasks/tasks.py
cp api/api/v1/webhook_celery.py api/api/v1/webhook.py
```

### Step 7: Update Docker Compose

```bash
# Backup old docker-compose
cp docker-compose.yml docker-compose-old.yml

# Use simplified version
cp docker-compose-simple.yml docker-compose.yml
```

### Step 8: Create ST2 Workflows

For each old CAB, create an ST2 workflow:

```bash
# Create pack directory
sudo mkdir -p /opt/stackstorm/packs/remediation/actions/workflows

# Create workflow YAML files
sudo vi /opt/stackstorm/packs/remediation/actions/workflows/host_down.yaml
# (paste workflow definition from Step 2)

# Register all workflows
cd /opt/stackstorm/packs/remediation/actions/workflows
for yaml in *.yaml; do
    st2 action create $yaml
done

# Verify
st2 action list --pack remediation
```

### Step 9: Create ST2 Rules

Create ST2 rules to match alerts (replaces CAB matching):

```yaml
# /opt/stackstorm/packs/remediation/rules/host_down.yaml
name: host_down_rule
pack: remediation
enabled: true
description: Trigger workflow when host is down

trigger:
  type: core.st2.webhook
  parameters:
    url: poundcake_alert

criteria:
  trigger.body.alert_name:
    pattern: "HostDown|NodeDown"
  trigger.body.severity:
    pattern: "critical|warning"

action:
  ref: remediation.host_down_workflow
  parameters:
    instance: "{{ trigger.body.instance }}"
    alert_name: "{{ trigger.body.alert_name }}"
    poundcake_request_id: "{{ trigger.body.request_id }}"
```

Register:
```bash
st2 rule create /opt/stackstorm/packs/remediation/rules/host_down.yaml
```

### Step 10: Update Environment Variables

```bash
# .env file
ST2_API_URL=http://localhost:9101/v1
ST2_API_KEY=your-st2-api-key-here

# Get ST2 API key
st2 apikey create -k -m '{"used_by": "poundcake-api"}'
# Copy the key to .env
```

### Step 11: Start Services

```bash
# Start PoundCake
docker-compose up -d

# Check services
docker-compose ps

# Check logs
docker-compose logs -f api
docker-compose logs -f celery

# Check ST2
sudo st2ctl status
```

### Step 12: Test Integration

```bash
# Send test alert
curl -X POST http://localhost:8000/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "HostDown",
        "instance": "server-01",
        "severity": "critical"
      },
      "annotations": {
        "description": "Host is down"
      },
      "fingerprint": "test123",
      "startsAt": "2026-01-14T12:00:00Z"
    }]
  }'

# Get request_id from response
REQUEST_ID="..."

# Check status
curl http://localhost:8000/api/v1/status/$REQUEST_ID | jq

# Check ST2 execution
st2 execution list

# Query database
mysql -upoundcake -ppoundcake poundcake -e "
SELECT 
    api.request_id,
    alert.alert_name,
    link.st2_execution_id,
    link.st2_action_ref
FROM poundcake_api_calls api
JOIN poundcake_alerts alert ON alert.api_call_id = api.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
WHERE api.request_id = '$REQUEST_ID';
"
```

### Step 13: Verify Complete Audit Trail

```sql
-- Get complete history for a request
SELECT 
    api.request_id,
    api.created_at as webhook_received,
    alert.alert_name,
    alert.severity,
    link.st2_execution_id,
    link.st2_action_ref,
    link.created_at as st2_triggered
FROM poundcake_api_calls api
JOIN poundcake_alerts alert ON alert.api_call_id = api.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
WHERE api.request_id = 'your-request-id';

-- If ST2 is in same database
SELECT 
    api.request_id,
    alert.alert_name,
    link.st2_execution_id,
    exec.action as st2_workflow,
    exec.status as st2_status,
    exec.result as st2_result
FROM poundcake_api_calls api
JOIN poundcake_alerts alert ON alert.api_call_id = api.id
JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
JOIN execution_db exec ON exec.id = link.st2_execution_id
WHERE api.request_id = 'your-request-id';
```

### Step 14: Cleanup (After Successful Migration)

```sql
-- After confirming everything works, remove archived tables
DROP TABLE IF EXISTS _archive_actions;
DROP TABLE IF EXISTS _archive_custom_action_buckets;
DROP TABLE IF EXISTS _archive_custom_action_bucket_steps;
DROP TABLE IF EXISTS _archive_action_executions;
```

## Rollback Plan

If you need to rollback:

```bash
# Stop services
docker-compose down

# Restore database
mysql -upoundcake -ppoundcake poundcake < \
  /backup/poundcake_before_migration_20260114.sql

# Restore old code
cp api/models/models_backup.py api/models/models.py
cp api/tasks/tasks_backup.py api/tasks/tasks.py

# Restore old docker-compose
cp docker-compose-old.yml docker-compose.yml

# Start services
docker-compose up -d
```

## Comparison Table

| Feature | Old (Complex) | New (Simple) |
|---------|---------------|--------------|
| Database Tables | 8+ | 3 |
| Workflow Engine | Custom (CABs) | StackStorm |
| Action Definitions | PoundCake | StackStorm |
| Workflow UI | None | ST2 Web UI |
| Complexity | High | Low |
| Maintenance | High | Low |
| ST2 Integration | Partial | Full |
| Community Packs | No | Yes (ST2 Pack Exchange) |

## Benefits

**Simplicity:**
- 62% fewer tables (8 → 3)
- Much less code
- No workflow duplication

**Power:**
- Full ST2 capabilities (ActionChains, Mistral, Orquesta)
- ST2 Pack Exchange (100+ community packs)
- ST2 Web UI for workflow management

**Maintenance:**
- Single workflow system (StackStorm)
- Standard ST2 tools
- Leverage ST2 community

**Audit Trail:**
- request_id tracks everything
- Simple link table
- Complete history via SQL joins

## Summary

**What We Removed:**
- Complex CAB system
- Actions table
- Extension tables

**What We Gained:**
- 62% simpler database
- Full StackStorm power
- Much easier maintenance
- Complete audit trail

**Migration Time:**
- Preparation: 1-2 hours
- Execution: 30-60 minutes
- Testing: 1-2 hours
- **Total: 2-4 hours**

The simplified architecture is the right way to integrate with StackStorm!
