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

# Timer Service

The Timer service monitors StackStorm execution completions and updates oven status.

## Purpose

The Timer service:
1. Polls for ovens with `processing_status = "processing"`
2. Checks StackStorm execution status for each ingredient
3. Updates ingredient completion status and timing
4. Marks ovens as complete when all ingredients finish
5. Tracks SLA metrics (expected vs actual time)

## Architecture

### Key Concepts

**Monitoring:** Continuous polling of active ovens
- Checks StackStorm for execution status updates
- Updates ingredient status (succeeded, failed, timeout)
- Calculates actual time to completion

**Completion Tracking:** Determines when ovens are done
- All ingredients must reach terminal state (succeeded/failed)
- Updates oven `processing_status` to "complete" or "failed"
- Records final completion time

**SLA Tracking:** Performance monitoring
- Compares `expected_time_to_completion` vs `actual_time_to_completion`
- Identifies tasks that exceed SLA
- Provides data for optimization

## Components

### timer.py

Main service file that runs continuously.

**Functions:**
- `timer_loop()` - Main service loop
- `process_timers()` - Process all active ovens
- `update_oven_completion(oven_id)` - Check and update oven completion status
- `check_st2_execution_status(execution_id)` - Query StackStorm for execution status
- `update_ingredient_completion()` - Update ingredient status and timing
- `calculate_oven_status()` - Determine overall oven status
- `log()` - Function-level structured logging

**Configuration (Environment Variables):**
- `POUNDCAKE_API_URL` - PoundCake API endpoint (default: http://api:8000)
- `TIMER_INTERVAL` - Polling interval in seconds (default: 10)
- `ST2_API_URL` - StackStorm API endpoint
- `ST2_API_KEY` - StackStorm API key for authentication
- `LOG_LEVEL` - Logging level (default: INFO)

## Running

### In Docker Compose (Normal Operation)
The timer service runs automatically when you start PoundCake:
```bash
docker compose up -d
```

### Standalone (Development)
```bash
export POUNDCAKE_API_URL=http://localhost:8000
export ST2_API_URL=http://localhost:9101/v1
export ST2_API_KEY=your-api-key
export TIMER_INTERVAL=10

python timer/timer.py
```

### Viewing Logs
```bash
# Follow logs
docker logs -f poundcake-timer

# Filter by function
docker logs poundcake-timer | grep "update_oven_completion"
docker logs poundcake-timer | grep "check_st2_execution_status"
```

## Function-Level Logging

Every log message includes the function name for easy debugging:

```
[2026-02-02 15:30:00] timer.process_timers: Processing 5 ovens
[2026-02-02 15:30:00] timer.update_oven_completion: Checking oven abc123 [oven_id=abc123]
[2026-02-02 15:30:00] timer.check_st2_execution_status: Execution succeeded [execution_id=xyz, status=succeeded]
```

**Log format:**
```
[timestamp] timer.function_name: message [key=value key=value]
```

## Execution Status Mapping

StackStorm execution statuses and their meanings:

### Terminal States (Execution Complete)
- `succeeded` - Execution completed successfully
- `failed` - Execution failed
- `timeout` - Execution exceeded time limit
- `canceled` - Execution was canceled
- `abandoned` - Execution was abandoned

### Active States (Execution Ongoing)
- `running` - Currently executing
- `scheduled` - Scheduled but not started
- `pending` - Waiting to start

### Status Transitions
```
pending → scheduled → running → succeeded/failed/timeout
                              ↘ canceled
                              ↘ abandoned
```

## Completion Logic

### Ingredient Completion

An ingredient is considered complete when:
1. StackStorm execution reaches a terminal state
2. `actual_time_to_completion` is calculated
3. `st2_execution_status` is updated

### Oven Completion

An oven is considered complete when:
1. **ALL** ingredients have reached terminal states
2. Overall oven status is determined:
   - `complete` - All ingredients succeeded
   - `failed` - One or more ingredients failed
3. Final completion time is recorded

### Example Completion Flow

```
Time  Ingredient             ST2 Status    Ingredient Status
----  --------------------  ------------  ------------------
T0    1. Check connectivity  running       processing
T5    1. Check connectivity  succeeded     complete [OK]
      2. Check service A     running       processing
      3. Check service B     running       processing
T10   2. Check service A     succeeded     complete [OK]
      3. Check service B     succeeded     complete [OK]
      4. Restart services    running       processing
T15   4. Restart services    succeeded     complete [OK]
      5. Verify recovery     running       processing
T20   5. Verify recovery     succeeded     complete [OK]

      → ALL ingredients complete
      → Oven status: complete
      → Total time: 20 seconds
```

## SLA Tracking

### Time Calculations

For each ingredient:
```
expected_time_to_completion = Set in recipe (e.g., 5 seconds)
actual_time_to_completion = execution_end_time - execution_start_time
sla_delta = actual_time_to_completion - expected_time_to_completion
```

### SLA Status
- **On-time:** `actual <= expected`
- **Over SLA:** `actual > expected`

### Example SLA Report
```
Ingredient: Check connectivity
Expected: 5s
Actual: 3s
Status: [OK] On-time (2s under)

Ingredient: Restart services
Expected: 30s
Actual: 45s
Status: ⚠ Over SLA (15s over)
```

## Database Updates

The timer service updates these fields:

### poundcake_ingredients
- `st2_execution_status` - Current StackStorm execution status
- `actual_time_to_completion` - Actual execution duration
- `completed_at` - Completion timestamp

### poundcake_ovens
- `processing_status` - Overall oven status (complete/failed)
- `completed_at` - Oven completion timestamp

## Error Handling

The timer service includes comprehensive error handling:

1. **StackStorm API Errors:** Logs and retries on next cycle
2. **PoundCake API Errors:** Logs and continues with next oven
3. **Missing Executions:** Logs warning if execution not found
4. **Unexpected Errors:** Logs stack trace and continues service

## Monitoring

### Key Metrics to Watch

1. **Ovens processed per cycle:** Should match active ovens
2. **Execution completion rate:** Percentage of successful completions
3. **Average completion time:** Compare to SLA expectations
4. **Stuck executions:** Executions in "running" for extended periods
5. **SLA violations:** Tasks consistently exceeding expected time

### Health Checks

```bash
# Check if service is running
docker compose ps poundcake-timer

# Check recent activity
docker logs --tail 50 poundcake-timer

# Check for errors
docker logs poundcake-timer | grep ERROR

# Check specific oven
docker logs poundcake-timer | grep "oven_id=abc123"

# Check SLA violations
docker logs poundcake-timer | grep "over SLA"
```

### Database Queries

```sql
-- Active ovens being monitored
SELECT req_id, recipe_name, processing_status, created_at
FROM poundcake_ovens
WHERE processing_status = 'processing';

-- Completed ovens in last hour
SELECT req_id, recipe_name,
       TIMESTAMPDIFF(SECOND, created_at, completed_at) as duration_seconds
FROM poundcake_ovens
WHERE processing_status = 'complete'
  AND completed_at > NOW() - INTERVAL 1 HOUR;

-- SLA violations
SELECT i.task_id, i.expected_time_to_completion,
       i.actual_time_to_completion,
       (i.actual_time_to_completion - i.expected_time_to_completion) as sla_delta
FROM poundcake_ingredients i
WHERE i.actual_time_to_completion > i.expected_time_to_completion
  AND i.st2_execution_status = 'succeeded';
```

## Development

### Testing Locally

1. Start dependencies:
   ```bash
   docker compose up -d mariadb mongodb stackstorm-api
   ```

2. Run API and Oven:
   ```bash
   docker compose up -d api oven
   ```

3. Run timer service locally:
   ```bash
   export POUNDCAKE_API_URL=http://localhost:8000
   export ST2_API_URL=http://localhost:9101/v1
   export ST2_API_KEY=your-key
   python timer/timer.py
   ```

### Testing Scenarios

**Test successful completion:**
1. Create an oven with all ingredients
2. Watch timer logs for status updates
3. Verify oven status changes to "complete"

**Test failure handling:**
1. Create an oven with failing ingredient
2. Watch timer detect failure
3. Verify oven status changes to "failed"

**Test SLA tracking:**
1. Create ingredients with tight SLA (expected_time_to_completion)
2. Execute slow-running actions
3. Verify SLA violations are detected and logged

### Adding Features

When adding new features to the timer service:

1. Add function-level logging to all new functions
2. Update this README with new functionality
3. Add error handling for new failure modes
4. Test with various StackStorm execution states
5. Verify SLA calculations are accurate

## Coordination with Oven Service

The timer and oven services work together:

```
Oven Service                Timer Service
------------                -------------
1. Create oven
2. Start ST2 executions
3. Set status="processing"  → 4. Monitor executions
                              5. Check ST2 status
                              6. Update ingredients
                              7. Update oven status
```

**Key principle:** The oven service starts executions, the timer service monitors completions.

## Troubleshooting

### Issue: Timer not updating completions

**Check:**
```bash
# Is timer running?
docker compose ps poundcake-timer

# Any errors in logs?
docker logs poundcake-timer | grep ERROR

# Can timer reach StackStorm?
docker exec poundcake-timer curl http://st2api:9101/v1

# Is ST2_API_KEY set?
docker exec poundcake-timer env | grep ST2_API_KEY
```

### Issue: Ovens stuck in "processing"

**Diagnose:**
```bash
# Check ingredient status
docker exec poundcake-mariadb mysql -upoundcake -ppoundcake poundcake -e \
  "SELECT oven_id, task_id, st2_execution_id, st2_execution_status
   FROM poundcake_ingredients
   WHERE oven_id IN (
     SELECT id FROM poundcake_ovens WHERE processing_status='processing'
   );"

# Check StackStorm execution status
docker exec stackstorm-api st2 execution list
```

### Issue: SLA tracking inaccurate

**Verify:**
1. Check ingredient `expected_time_to_completion` values
2. Verify StackStorm execution timestamps
3. Check timer logs for calculation details
4. Ensure system clocks are synchronized


## Related Services

- **API Service:** Provides oven and ingredient data via REST API
- **Timer Service:** Monitors StackStorm executions and updates completion status
- **StackStorm:** Executes the actual remediation actions

## Related Documentation

- **Architecture:** `../docs/ARCHITECTURE.md`
- **API Endpoints:** `../docs/API_ENDPOINTS.md`
- **Database Schema:** `../docs/DATABASE_MIGRATIONS.md`
- **Troubleshooting:** `../docs/TROUBLESHOOTING.md`
