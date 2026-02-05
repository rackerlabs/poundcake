# PoundCake Kitchen

This directory contains the **kitchen staff** - background services that handle the actual work of preparing and cooking alerts based on recipes.

## Kitchen Staff

### 🧑‍🍳 Chef (`chef.py`)

The head chef who executes actions from the oven queue.

**Responsibilities:**

- Polls for `new` tasks in the Oven queue
- Executes StackStorm actions via the API bridge
- Updates task status to `processing` when started
- Handles execution failures and updates error messages
- Monitors overall kitchen operations

**Environment Variables:**

- `POUNDCAKE_API_URL` - API endpoint (default: `http://api:8000`)
- `OVEN_POLL_INTERVAL` - How often to check for new tasks in seconds (default: `5`)
- `LOG_LEVEL` - Logging level (default: `INFO`)

**System Request ID:** `SYSTEM-CHEF`

### 👨‍🍳 Prep Chef (`prep_chef.py`)

The prep chef who prepares raw alerts for baking.

**Responsibilities:**

- Polls for `new` alerts from Alertmanager
- Triggers the `/bake` API endpoint to convert alerts into oven tasks
- Matches alerts to recipes based on `group_name`
- Ensures alerts are properly queued for the chef to execute

**Environment Variables:**

- `POUNDCAKE_API_URL` - API endpoint (default: `http://api:8000`)
- `OVEN_INTERVAL` - How often to poll for new alerts in seconds (default: `5`)
- `LOG_LEVEL` - Logging level (default: `INFO`)

**System Request ID:** `SYSTEM-PREP-CHEF`

### ⏱️ Timer (`timer.py`)

The kitchen timer that monitors when things are done cooking.

**Responsibilities:**

- Polls StackStorm for completed executions
- Matches completed executions to oven tasks
- Updates task status to `completed` or `failed`
- Tracks execution duration and results
- Monitors SLA compliance

**Environment Variables:**

- `POUNDCAKE_API_URL` - API endpoint (default: `http://api:8000/api/v1`)
- `ST2_API_URL` - StackStorm API endpoint (default: `http://stackstorm-api:9101/v1`)
- `TIMER_INTERVAL` - How often to check for completions in seconds (default: `10`)
- `SLA_BUFFER_PERCENT` - SLA buffer percentage (default: `0.2` = 20%)
- `LOG_LEVEL` - Logging level (default: `INFO`)

**System Request ID:** `SYSTEM-TIMER`

## Workflow

```
1. Alertmanager sends webhook → API receives alert
                                    ↓
2. Prep Chef polls API ────────→ Finds new alert
                                    ↓
3. Prep Chef calls /bake ──────→ Creates oven tasks from recipe
                                    ↓
4. Chef polls API ──────────────→ Finds new oven task
                                    ↓
5. Chef executes ──────────────→ Triggers StackStorm action
                                    ↓
6. Timer polls ST2 ─────────────→ Finds completed execution
                                    ↓
7. Timer updates oven ──────────→ Marks task as completed
```

## Logging

All kitchen services use standardized logging from `api.core.logging`:

- Format: `YYYY-MM-DD HH:MM:SS [req_id] LEVEL - function_name: message`
- Structured context via `extra` dictionary
- Request ID tracking throughout the workflow
- Function-level log messages for granular debugging

## Running Locally

```bash
# Run individual services (requires API to be running)
python3 kitchen/prep_chef.py
python3 kitchen/chef.py
python3 kitchen/timer.py
```

## Docker Deployment

Services are defined in `docker-compose.yml`:

```yaml
chef:        # Executes actions
prep_chef:   # Prepares alerts
timer:       # Monitors completions
```

Start all kitchen services:

```bash
docker compose up -d chef prep_chef timer
```

View kitchen logs:

```bash
docker compose logs -f chef prep_chef timer
```

## Troubleshooting

### Prep Chef not picking up alerts

- Check API is healthy: `curl http://localhost:8000/api/v1/health`
- Verify alerts exist: `curl http://localhost:8000/api/v1/alerts?processing_status=new`
- Check prep_chef logs: `docker compose logs prep_chef`

### Chef not executing tasks

- Verify oven tasks exist: `curl http://localhost:8000/api/v1/ovens?processing_status=new`
- Check StackStorm is running: `curl http://localhost:9101/v1`
- Check chef logs: `docker compose logs chef`

### Timer not updating completions

- Verify StackStorm executions are completing
- Check timer is connecting to both API and ST2
- Check timer logs: `docker compose logs timer`

## Architecture Notes

The kitchen is completely decoupled from the API:

- **API** = Stateful data layer (database, REST endpoints)
- **Kitchen** = Stateless workers (polling, execution, monitoring)

This separation allows:

- Independent scaling of API vs kitchen services
- Easy addition of new kitchen roles (e.g., sous_chef, dishwasher)
- Clear separation of concerns
- Fault tolerance (kitchen failures don't affect API)
