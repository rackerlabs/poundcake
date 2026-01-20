# Installing StackStorm with MariaDB Backend

## Overview

This guide installs StackStorm using MariaDB as the database backend, creating a unified database architecture where PoundCake and StackStorm share the same MariaDB instance.

## Architecture

```
                    ┌─────────────────────┐
                    │    MariaDB          │
                    │  (Single Database)  │
                    └─────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
        ┌───────▼──────┐        ┌──────▼──────┐
        │  StackStorm   │        │  PoundCake  │
        │    Tables     │        │   Tables    │
        └───────────────┘        └─────────────┘
        │                        │
        ├─ action_db             ├─ poundcake_api_calls
        ├─ execution_db          ├─ poundcake_alerts
        ├─ rule_db               │
        ├─ trigger_db            └─ Extension Tables:
        └─ webhook_db               ├─ poundcake_st2_action_extensions
                                    ├─ poundcake_st2_rule_extensions
                                    ├─ poundcake_st2_execution_extensions
                                    └─ poundcake_st2_webhook_extensions

Task Execution (Separate Systems):

┌─────────────────────────┐      ┌─────────────────────────┐
│      StackStorm         │      │      PoundCake          │
├─────────────────────────┤      ├─────────────────────────┤
│ RabbitMQ (NOT Redis)    │      │ Redis                   │
│ st2actionrunner         │      │ Celery Workers          │
│ (NOT Celery)            │      │                         │
└─────────────────────────┘      └─────────────────────────┘

IMPORTANT: StackStorm uses RabbitMQ + custom action runners
           PoundCake uses Redis + Celery workers
           They do NOT share task execution infrastructure
```

## Benefits of Unified Database

1. **Single Database** - One MariaDB instance for everything
2. **No Duplication** - StackStorm manages executions, we extend them
3. **Direct Queries** - PoundCake can query ST2 data directly
4. **ST2 UI Integration** - StackStorm UI shows our execution data
5. **Simplified Ops** - One database to backup, monitor, manage
6. **Request ID Linking** - Complete audit trail across both systems

## Prerequisites

- Ubuntu 20.04/22.04 or RHEL 7/8/9
- MariaDB 10.6+ already installed (from PoundCake setup)
- Root or sudo access
- Internet connectivity

## Installation Steps

### 1. Install StackStorm

```bash
# Add StackStorm repository
curl -sSL https://packages.stackstorm.com/public/st2-latest.key | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/st2-latest.gpg

# Add repository (Ubuntu/Debian)
echo "deb https://packages.stackstorm.com/public/st2-latest/deb stable main" | \
  sudo tee /etc/apt/sources.list.d/st2-latest.list

# Update and install
sudo apt-get update
sudo apt-get install -y st2
```

### 2. Configure StackStorm to Use MariaDB

#### Create StackStorm Database

```bash
# Connect to MariaDB
mysql -upoundcake -ppoundcake

# Create StackStorm database (separate from poundcake)
CREATE DATABASE stackstorm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# Create StackStorm user (or reuse poundcake user)
CREATE USER IF NOT EXISTS 'stackstorm'@'localhost' IDENTIFIED BY 'stackstorm_password';
GRANT ALL PRIVILEGES ON stackstorm.* TO 'stackstorm'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**Alternative:** Use same database with different schema/prefixes:
```sql
-- Option: Share poundcake database with st2_ table prefix
USE poundcake;
-- ST2 tables will be: st2_action_db, st2_execution_db, etc.
-- PoundCake tables: poundcake_api_calls, poundcake_alerts, etc.
```

#### Configure ST2 Database Connection

Edit `/etc/st2/st2.conf`:

```ini
[database]
# Use MariaDB instead of MongoDB
db_name = stackstorm
host = localhost
port = 3306
username = stackstorm
password = stackstorm_password
# Use MySQL backend
backend = mysql

[coordination]
# Optional: Use MariaDB for coordination
url = mysql://stackstorm:stackstorm_password@localhost:3306/stackstorm
```

**For shared database approach:**
```ini
[database]
db_name = poundcake
host = localhost
port = 3306
username = poundcake
password = poundcake
backend = mysql
# Use table prefix to separate ST2 tables
table_prefix = st2_
```

### 3. Initialize StackStorm Database

```bash
# Initialize ST2 database schema
sudo st2-setup-db

# This creates ST2 tables:
# - action_db (or st2_action_db with prefix)
# - execution_db
# - liveaction_db
# - rule_db
# - trigger_db
# - webhook_db
# - etc.
```

### 4. Configure StackStorm Services

```bash
# Setup authentication
sudo st2-setup-auth

# Register default content (packs, actions, rules)
sudo st2ctl reload --register-all

# Start StackStorm services
sudo st2ctl start

# Enable st2 services on boot
sudo systemctl enable st2api st2stream st2auth st2actionrunner st2notifier \
  st2resultstracker st2rulesengine st2sensorcontainer st2garbagecollector st2scheduler
```

### 5. Verify StackStorm Installation

```bash
# Check services
sudo st2ctl status

# Test API
st2 --version
st2 action list

# Check database connection
mysql -ustackstorm -pstackstorm_password stackstorm -e "SHOW TABLES;"

# Should see tables like:
# - action_db
# - execution_db  
# - liveaction_db
# - rule_db
# - trigger_db
# - webhook_db
```

### 6. Install Required StackStorm Packs

```bash
# Install packs for remediation actions
st2 pack install linux
st2 pack install network  
st2 pack install slack
st2 pack install email
st2 pack install http
st2 pack install jenkins

# Verify installation
st2 action list --pack linux
st2 action list --pack network
```

### 7. Create StackStorm API Key for PoundCake

```bash
# Create API key for PoundCake to call ST2
st2 apikey create -k -m '{"used_by": "poundcake-api"}'

# Save the output, you'll need it for PoundCake .env
# Example output: abcdef1234567890abcdef1234567890
```

### 8. Configure PoundCake Integration

Edit PoundCake `.env`:

```bash
# StackStorm connection
ST2_API_URL=http://localhost:9101/v1
ST2_AUTH_URL=http://localhost:9100/tokens
ST2_API_KEY=abcdef1234567890abcdef1234567890
ST2_STREAM_URL=ws://localhost:9102/v1/stream

# Database (shared or separate)
DATABASE_URL=mysql+pymysql://poundcake:poundcake@localhost:3306/poundcake

# ST2 Database (if separate)
ST2_DATABASE_URL=mysql+pymysql://stackstorm:stackstorm_password@localhost:3306/stackstorm
```

### 9. Initialize PoundCake Extension Tables

```bash
# Run PoundCake database initialization
# This creates our extension tables that link to ST2
cd /path/to/poundcake-api
python api/scripts/init_unified_database.py

# This creates:
# - poundcake_api_calls
# - poundcake_alerts
# - poundcake_st2_action_extensions
# - poundcake_st2_rule_extensions
# - poundcake_st2_execution_extensions
# - poundcake_st2_webhook_extensions
```

### 10. Verify Unified Database

```bash
# Check all tables in database
mysql -upoundcake -ppoundcake poundcake -e "SHOW TABLES;"

# Should see both ST2 and PoundCake tables:
# ST2 Tables:
#   action_db, execution_db, rule_db, etc.
# PoundCake Tables:
#   poundcake_api_calls, poundcake_alerts
# Extension Tables:
#   poundcake_st2_action_extensions, etc.

# Query example: Get ST2 actions with PoundCake metadata
mysql -upoundcake -ppoundcake poundcake -e "
SELECT 
    a.name,
    a.pack,
    ext.action_type,
    ext.is_active
FROM action_db a
LEFT JOIN poundcake_st2_action_extensions ext ON a.id = ext.st2_action_id;
"
```

## Database Schema Details

### StackStorm Native Tables

**action_db** - Action definitions
```sql
id, name, pack, description, enabled, entry_point, 
runner_type, parameters, tags, metadata_file
```

**execution_db** - Completed executions
```sql
id, action, parameters, status, result, 
start_timestamp, end_timestamp, parent, context
```

**liveaction_db** - Running executions
```sql
id, action, parameters, status, start_timestamp,
callback, context
```

**rule_db** - Rule definitions
```sql
id, name, pack, description, enabled, trigger,
criteria, action, tags
```

**trigger_db** - Trigger definitions
```sql
id, name, pack, type, parameters
```

**webhook_db** - Webhook configurations
```sql
id, name, type, url
```

### PoundCake Extension Tables

**poundcake_st2_action_extensions**
- Links to: `action_db.id`
- Adds: action_type, expected_result_schema, parameter_templates, timeout_seconds

**poundcake_st2_rule_extensions** 
- Links to: `rule_db.id`
- Adds: cab_name, alert_name_pattern, severity_filter, stop_on_first_failure

**poundcake_st2_execution_extensions**
- Links to: `execution_db.id`
- Adds: request_id, alert_id, step_order, expected_result, result_matched

## Configuration Options

### Separate Databases (Recommended for Production)

**Pros:**
- Clear separation of concerns
- Independent backup/restore
- Easier to scale separately

**Setup:**
```bash
# Two databases
CREATE DATABASE poundcake;
CREATE DATABASE stackstorm;

# PoundCake .env
DATABASE_URL=mysql+pymysql://poundcake:poundcake@localhost:3306/poundcake
ST2_DATABASE_URL=mysql+pymysql://stackstorm:stackstorm@localhost:3306/stackstorm
```

**Queries across databases:**
```sql
SELECT 
    p.request_id,
    s.action as st2_action,
    s.status
FROM poundcake.poundcake_st2_execution_extensions p
JOIN stackstorm.execution_db s ON p.st2_execution_id = s.id;
```

### Shared Database (Simpler for Small Deployments)

**Pros:**
- Single backup
- Simpler queries (no cross-database joins)
- Easier development

**Setup:**
```bash
# One database with prefixed tables
CREATE DATABASE poundcake;

# ST2 config
[database]
db_name = poundcake
table_prefix = st2_

# Tables: st2_action_db, st2_execution_db, poundcake_api_calls, etc.
```

## StackStorm Web UI Access

```bash
# Install ST2 Web UI
sudo apt-get install -y st2web

# Configure nginx (comes with st2web)
sudo systemctl restart nginx

# Access UI
# URL: https://your-server-ip
# Login with credentials from st2-setup-auth
```

The ST2 Web UI will show:
- All actions (including those registered by PoundCake)
- All executions (with our request_id in context)
- Rules (our CABs mapped to ST2 rules)
- Execution history

## Backup Strategy

### Backup Both Systems

```bash
#!/bin/bash
# Backup script for unified database

DATE=$(date +%Y%m%d_%H%M%S)

# Backup PoundCake + ST2 database
mysqldump -upoundcake -ppoundcake poundcake > \
  /backup/poundcake_st2_unified_${DATE}.sql

# Or backup separately if using separate databases
mysqldump -upoundcake -ppoundcake poundcake > \
  /backup/poundcake_${DATE}.sql
  
mysqldump -ustackstorm -pstackstorm_password stackstorm > \
  /backup/stackstorm_${DATE}.sql
```

### Restore

```bash
# Restore unified database
mysql -upoundcake -ppoundcake poundcake < \
  /backup/poundcake_st2_unified_20260114_120000.sql
  
# Restart services
sudo st2ctl restart
docker-compose restart api
```

## Monitoring

### Check ST2 Service Health

```bash
# Check all ST2 services
sudo st2ctl status

# Check ST2 API
curl -H "St2-Api-Key: $ST2_API_KEY" http://localhost:9101/v1/actions

# Check database connections
mysql -ustackstorm -pstackstorm_password -e "SELECT 1;"
```

### Monitor Database Size

```bash
# Check database sizes
mysql -upoundcake -ppoundcake -e "
SELECT 
    table_schema AS 'Database',
    SUM(data_length + index_length) / 1024 / 1024 AS 'Size (MB)'
FROM information_schema.tables 
WHERE table_schema IN ('poundcake', 'stackstorm')
GROUP BY table_schema;
"

# Check table sizes
mysql -upoundcake -ppoundcake poundcake -e "
SELECT 
    table_name,
    ROUND(((data_length + index_length) / 1024 / 1024), 2) AS 'Size (MB)'
FROM information_schema.TABLES 
WHERE table_schema = 'poundcake'
ORDER BY (data_length + index_length) DESC;
"
```

### View Execution Metrics

```bash
# ST2 execution count
st2 execution list --last 10

# Database query
mysql -upoundcake -ppoundcake poundcake -e "
SELECT 
    DATE(start_timestamp) as date,
    COUNT(*) as execution_count,
    SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as success,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM execution_db
WHERE start_timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY DATE(start_timestamp)
ORDER BY date DESC;
"
```

## Troubleshooting

### ST2 Can't Connect to MariaDB

```bash
# Check MariaDB is running
sudo systemctl status mariadb

# Test connection
mysql -ustackstorm -pstackstorm_password stackstorm -e "SELECT 1;"

# Check ST2 config
cat /etc/st2/st2.conf | grep -A 10 "\[database\]"

# Check logs
sudo tail -f /var/log/st2/*.log
```

### PoundCake Can't Query ST2 Tables

```bash
# Check database permissions
mysql -upoundcake -ppoundcake -e "SHOW GRANTS;"

# Grant access to ST2 tables if needed
mysql -uroot -p -e "
GRANT SELECT ON stackstorm.* TO 'poundcake'@'localhost';
FLUSH PRIVILEGES;
"

# Test query
mysql -upoundcake -ppoundcake -e "
SELECT * FROM stackstorm.action_db LIMIT 1;
"
```

### ST2 Actions Not Appearing

```bash
# Re-register actions
sudo st2ctl reload --register-actions

# Check action database
mysql -ustackstorm -pstackstorm_password stackstorm -e "
SELECT COUNT(*) FROM action_db;
"

# List actions via API
st2 action list
```

### Execution Tracking Not Working

```bash
# Check extension table exists
mysql -upoundcake -ppoundcake poundcake -e "
SHOW TABLES LIKE 'poundcake_st2_%';
"

# Check for foreign key constraints
mysql -upoundcake -ppoundcake poundcake -e "
SELECT * FROM information_schema.KEY_COLUMN_USAGE 
WHERE TABLE_SCHEMA = 'poundcake' 
AND REFERENCED_TABLE_NAME = 'execution_db';
"
```

## Performance Tuning

### MariaDB Configuration

Edit `/etc/mysql/mariadb.conf.d/50-server.cnf`:

```ini
[mysqld]
# Increase for ST2 + PoundCake workload
innodb_buffer_pool_size = 2G
innodb_log_file_size = 512M
max_connections = 200

# For execution_db table (many inserts)
innodb_flush_log_at_trx_commit = 2
innodb_write_io_threads = 8
```

Restart MariaDB:
```bash
sudo systemctl restart mariadb
```

### Index Optimization

```sql
-- Add indexes for common ST2 + PoundCake queries
USE poundcake;

-- Index on execution_db for our extension joins
CREATE INDEX idx_execution_id ON execution_db(id);
CREATE INDEX idx_execution_timestamp ON execution_db(start_timestamp);

-- Index on our extension table
CREATE INDEX idx_ext_request_id ON poundcake_st2_execution_extensions(request_id);
CREATE INDEX idx_ext_alert_id ON poundcake_st2_execution_extensions(alert_id);
```

## Security

### Database User Permissions

```sql
-- PoundCake user (read-only on ST2 tables)
CREATE USER 'poundcake_ro'@'localhost' IDENTIFIED BY 'readonly_password';
GRANT SELECT ON stackstorm.* TO 'poundcake_ro'@'localhost';
GRANT ALL ON poundcake.* TO 'poundcake_ro'@'localhost';

-- StackStorm user (full access to ST2 tables, read-only on PoundCake)
CREATE USER 'st2'@'localhost' IDENTIFIED BY 'st2_password';
GRANT ALL ON stackstorm.* TO 'st2'@'localhost';
GRANT SELECT ON poundcake.poundcake_alerts TO 'st2'@'localhost';
GRANT SELECT ON poundcake.poundcake_api_calls TO 'st2'@'localhost';

FLUSH PRIVILEGES;
```

### API Key Rotation

```bash
# Create new ST2 API key
st2 apikey create -k -m '{"used_by": "poundcake-api", "created": "2026-01-14"}'

# Update PoundCake .env
ST2_API_KEY=<new_key>

# Restart PoundCake
docker-compose restart api

# Delete old key
st2 apikey delete <old_key_id>
```

## Summary

You now have:
- ✅ StackStorm installed with MariaDB backend
- ✅ PoundCake extension tables linking to ST2
- ✅ Unified database architecture
- ✅ Complete execution tracking across both systems
- ✅ ST2 Web UI showing all execution data
- ✅ Single backup strategy

Next steps:
1. Create ST2 actions and rules
2. Map PoundCake CABs to ST2 rules
3. Test end-to-end alert remediation
4. Monitor execution tracking

The unified database provides the foundation for seamless integration between PoundCake's alert processing and StackStorm's remediation capabilities.
