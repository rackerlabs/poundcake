# Oven Service

The Oven service is responsible for orchestrating task execution with dependency management.

## Purpose

The Oven service:
1. Polls for ovens with `processing_status = "new"`
2. Evaluates task dependencies using `is_blocking` logic
3. Starts StackStorm executions for ready tasks
4. Updates oven and ingredient status
5. Handles task orchestration with proper sequencing

## Architecture

### Key Concepts

**Oven:** Represents a complete remediation workflow execution
- Created when an alert matches a recipe
- Contains multiple ingredients (tasks)
- Tracks overall execution status

**Ingredient:** Represents a single task within an oven
- Has a specific order (`task_order`)
- Can be blocking or non-blocking (`is_blocking`)
- References a StackStorm action (`st2_action`)
- Tracks execution status and timing

**Dependency Logic:**
- **Blocking tasks** (`is_blocking=true`): Must complete before next task starts
- **Non-blocking tasks** (`is_blocking=false`): Can run in parallel with other non-blocking tasks
- Tasks are executed in `task_order` sequence, respecting blocking dependencies

### Example Workflow

Recipe with 5 ingredients:
```
1. Check connectivity     (blocking)   ← Must complete first
2. Check service A        (non-blocking) ↘
3. Check service B        (non-blocking)  → Can run in parallel
4. Restart services       (blocking)   ← Waits for 2 and 3
5. Verify recovery        (blocking)   ← Waits for 4
```

## Components

### oven.py

Main service file that runs continuously.

**Functions:**
- `oven_loop()` - Main service loop
- `process_ovens()` - Process all ready ovens
- `can_start_oven(oven_id)` - Check if oven can start (all dependencies met)
- `start_st2_execution(ingredient)` - Start StackStorm execution for an ingredient
- `update_ingredient_status()` - Update ingredient execution status
- `log()` - Function-level structured logging

**Configuration (Environment Variables):**
- `POUNDCAKE_API_URL` - PoundCake API endpoint (default: http://api:8000)
- `OVEN_INTERVAL` - Polling interval in seconds (default: 5)
- `ST2_API_URL` - StackStorm API endpoint
- `ST2_API_KEY` - StackStorm API key for authentication
- `LOG_LEVEL` - Logging level (default: INFO)

## Running

### In Docker Compose (Normal Operation)
The oven service runs automatically when you start PoundCake:
```bash
docker compose up -d
```

### Standalone (Development)
```bash
export POUNDCAKE_API_URL=http://localhost:8000
export ST2_API_URL=http://localhost:9101/v1
export ST2_API_KEY=your-api-key
export OVEN_INTERVAL=5

python oven/oven.py
```

### Viewing Logs
```bash
# Follow logs
docker logs -f poundcake-oven

# Filter by function
docker logs poundcake-oven | grep "can_start_oven"
docker logs poundcake-oven | grep "start_st2_execution"
```

## Function-Level Logging

Every log message includes the function name for easy debugging:

```
[2026-02-02 15:30:00] oven.process_ovens: Processing 3 ovens
[2026-02-02 15:30:00] oven.can_start_oven: Checking oven abc123 [oven_id=abc123]
[2026-02-02 15:30:00] oven.start_st2_execution: Starting execution [ingredient_id=xyz, st2_action=core.local]
```

**Log format:**
```
[timestamp] oven.function_name: message [key=value key=value]
```

## Dependency Management

### Blocking Logic

The `can_start_oven()` function implements sophisticated dependency checking:

1. **Check previous blocking task:** If the previous task is blocking and not complete, wait
2. **Check all previous non-blocking tasks:** All non-blocking tasks must complete before starting the next blocking task
3. **Allow parallel non-blocking tasks:** Multiple non-blocking tasks can run simultaneously

### Example Execution Flow

```
Time  Task                     Status      Action
----  ----------------------  ----------  -------------------------
T0    1. Check connectivity   new         → Start (first task)
T5    1. Check connectivity   running     → Wait
T10   1. Check connectivity   succeeded   → Complete
      2. Check service A      new         → Start (non-blocking)
      3. Check service B      new         → Start (non-blocking)
T15   2. Check service A      running     → Wait
      3. Check service B      running     → Wait
T20   2. Check service A      succeeded   → Complete
      3. Check service B      succeeded   → Complete
      4. Restart services     new         → Start (blocking, deps met)
T25   4. Restart services     running     → Wait
T30   4. Restart services     succeeded   → Complete
      5. Verify recovery      new         → Start (final task)
```

## Database Schema

The oven service interacts with these tables:

### poundcake_ovens
```sql
CREATE TABLE poundcake_ovens (
    id INT PRIMARY KEY,
    req_id VARCHAR(255),
    alert_id INT,
    recipe_id INT,
    recipe_name VARCHAR(255),
    processing_status ENUM('new', 'processing', 'complete', 'failed'),
    ...
)
```

### poundcake_ingredients
```sql
CREATE TABLE poundcake_ingredients (
    id INT PRIMARY KEY,
    oven_id INT,
    task_id VARCHAR(255),
    task_order INT,
    is_blocking BOOLEAN,
    st2_action VARCHAR(255),
    st2_execution_id VARCHAR(255),
    st2_execution_status VARCHAR(50),
    expected_time_to_completion INT,
    actual_time_to_completion INT,
    ...
)
```

## Error Handling

The oven service includes comprehensive error handling:

1. **API Communication Errors:** Retries with exponential backoff
2. **StackStorm Errors:** Logs error and updates ingredient status
3. **Database Errors:** Logs and continues with next oven
4. **Unexpected Errors:** Logs stack trace and continues service

## Monitoring

### Key Metrics to Watch

1. **Ovens processed per cycle:** Should be > 0 when alerts are active
2. **Execution start failures:** Should be minimal
3. **Average processing time:** Compare to recipe expectations
4. **Stuck ovens:** Ovens in "processing" for extended periods

### Health Checks

```bash
# Check if service is running
docker compose ps poundcake-oven

# Check recent activity
docker logs --tail 50 poundcake-oven

# Check for errors
docker logs poundcake-oven | grep ERROR

# Check specific oven
docker logs poundcake-oven | grep "oven_id=abc123"
```

## Development

### Testing Locally

1. Start dependencies:
   ```bash
   docker compose up -d mariadb mongodb stackstorm-api
   ```

2. Run API:
   ```bash
   docker compose up -d api
   ```

3. Run oven service locally:
   ```bash
   export POUNDCAKE_API_URL=http://localhost:8000
   export ST2_API_URL=http://localhost:9101/v1
   export ST2_API_KEY=your-key
   python oven/oven.py
   ```

### Adding Features

When adding new features to the oven service:

1. Add function-level logging to all new functions
2. Update this README with new functionality
3. Add error handling for new failure modes
4. Test with both blocking and non-blocking ingredients
5. Verify logs are clear and actionable

## Related Services

- **API Service:** Provides oven and ingredient data via REST API
- **Timer Service:** Monitors StackStorm executions and updates completion status
- **StackStorm:** Executes the actual remediation actions

## Related Documentation

- **Architecture:** `../docs/ARCHITECTURE.md`
- **API Endpoints:** `../docs/API_ENDPOINTS.md`
- **Database Schema:** `../docs/DATABASE_MIGRATIONS.md`
- **Troubleshooting:** `../docs/TROUBLESHOOTING.md`
