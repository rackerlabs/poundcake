# Bakery

Bakery is PoundCake's ticketing system integration microservice. It acts as a translation layer between the PoundCake API and external ticketing systems, converting generic ticket requests into system-specific API calls and returning the results.

## Supported Ticketing Systems

| Mixer | Key | Actions |
|-------|-----|---------|
| ServiceNow | `servicenow` | create, update, close, comment, search |
| Jira | `jira` | create, update, close, comment, search |
| GitHub Issues | `github` | create, update, close, comment, search |
| PagerDuty | `pagerduty` | create, update, close, comment, search |
| Rackspace Core | `rackspace_core` | create, update, close, comment, search |

## Architecture

```
PoundCake API
     |
     | POST /api/v1/tickets
     v
  ┌──────────┐    ┌──────────────────┐    ┌──────────────────┐
  │  Bakery   │───>│  Mixer Factory   │───>│  ServiceNow      │
  │  FastAPI  │    │                  │    │  Jira             │
  │           │    │  get_mixer()     │    │  GitHub           │
  │           │    │  list_mixers()   │    │  PagerDuty        │
  └──────────┘    └──────────────────┘    │  Rackspace Core   │
       |                                   └──────────────────┘
       v                                            |
  ┌──────────┐                                      v
  │ MariaDB  │                              External Ticketing
  │          │                              System APIs
  └──────────┘
```

### Request Flow

1. PoundCake API sends a `POST /api/v1/tickets` request with a `correlation_id`, `mixer_type`, `action`, and `request_data`.
2. Bakery validates the request, persists it to MariaDB, and returns `202 Accepted` immediately.
3. A background task picks up the request, resolves the appropriate mixer via the Factory, and calls `mixer.process_request(action, data)`.
4. The mixer translates the request into the target system's API format and executes it.
5. The result is written to the `messages` table.
6. PoundCake API polls `GET /api/v1/messages?correlation_id=...` to retrieve the result.

### Mixers

Mixers are the modular integration layer. Each mixer implements the `BaseMixer` abstract class:

```python
class BaseMixer(ABC):
    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]: ...
    async def validate_credentials(self) -> bool: ...
```

Mixers are registered in `bakery/mixer/factory.py` via the `MIXER_REGISTRY` dict. Adding a new ticketing system means creating a new mixer class and adding it to the registry.

### Database Tables

| Table | Purpose |
|-------|---------|
| `ticket_requests` | Audit log of all requests with status tracking |
| `messages` | Response queue polled by PoundCake API |
| `mixer_configs` | Optional per-mixer dynamic configuration |

## API Endpoints

All endpoints are prefixed with `/api/v1`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check with database connectivity status |

### Tickets

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/tickets` | Submit a ticket request (returns 202) |
| `GET` | `/api/v1/tickets/{correlation_id}` | Get request status by correlation ID |

Bakery now exposes a stable internal `ticket_id` UUID to PoundCake API. External/provider-native
ticket numbers are stored only inside Bakery.

**POST /api/v1/tickets** request body:

```json
{
  "correlation_id": "uuid-from-poundcake",
  "mixer_type": "servicenow",
  "action": "create",
  "request_data": {
    "title": "Server disk full",
    "description": "Root partition at 95%",
    "urgency": "2",
    "impact": "2"
  }
}
```

### Messages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/messages` | Poll for response messages |
| `DELETE` | `/api/v1/messages/{message_id}` | Delete a message |
| `POST` | `/api/v1/messages/cleanup` | Remove old retrieved messages |

**GET /api/v1/messages** query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `correlation_id` | string | Filter by correlation ID |
| `mixer_type` | string | Filter by mixer type |
| `status` | string | Filter by status (success, error) |
| `limit` | int | Max results (default 100, max 1000) |

## Mixer-Specific Request Data

### ServiceNow

**create:**
```json
{
  "title": "Incident title",
  "description": "Incident details",
  "urgency": "3",
  "impact": "3"
}
```

**search:**
```json
{
  "query": "state=1^priority=1",
  "limit": 20,
  "offset": 0,
  "fields": ["number", "short_description", "state"]
}
```

### Jira

**create:**
```json
{
  "project_key": "OPS",
  "title": "Issue summary",
  "description": "Issue details",
  "issue_type": "Task"
}
```

**search:**
```json
{
  "jql": "project = OPS AND status = Open",
  "limit": 20,
  "offset": 0,
  "fields": ["summary", "status", "assignee"]
}
```

### GitHub Issues

**create:**
```json
{
  "owner": "org-name",
  "repo": "repo-name",
  "title": "Issue title",
  "description": "Issue body",
  "labels": ["bug"],
  "assignees": ["username"]
}
```

**search** (full-text):
```json
{
  "owner": "org-name",
  "repo": "repo-name",
  "query": "disk space",
  "state": "open",
  "limit": 20
}
```

**search** (filter):
```json
{
  "owner": "org-name",
  "repo": "repo-name",
  "state": "open",
  "labels": ["bug", "critical"],
  "limit": 20,
  "page": 1
}
```

### PagerDuty

**create:**
```json
{
  "service_id": "PXXXXXX",
  "from_email": "user@example.com",
  "title": "Incident title",
  "description": "Incident details",
  "urgency": "high"
}
```

**search:**
```json
{
  "statuses": ["triggered", "acknowledged"],
  "service_ids": ["PXXXXXX"],
  "since": "2024-01-01T00:00:00Z",
  "until": "2024-01-31T23:59:59Z",
  "limit": 20,
  "offset": 0
}
```

### Rackspace Core

Rackspace Core uses the CTKAPI query endpoint. Authentication is token-based and handled transparently by the mixer.

**create:**
```json
{
  "account_number": "123456",
  "queue": "Support",
  "subcategory": "General",
  "subject": "Ticket subject",
  "body": "Ticket description",
  "source": "Bakery",
  "severity": "Normal"
}
```

**update:**
```json
{
  "ticket_number": "240101-00001",
  "attributes": {
    "severity": "High",
    "queue": "Escalations"
  }
}
```

**close:**
```json
{
  "ticket_number": "240101-00001",
  "status": "Solved"
}
```

**comment:**
```json
{
  "ticket_number": "240101-00001",
  "comment": "Comment text here"
}
```

**search** (direct lookup):
```json
{
  "ticket_number": "240101-00001",
  "attributes": ["ticket_number", "subject", "status", "queue"]
}
```

**search** (where conditions):
```json
{
  "where_conditions": [
    {"field": "queue", "op": "eq", "value": "Support"},
    {"field": "status", "op": "ne", "value": "Solved"}
  ],
  "attributes": ["ticket_number", "subject", "status"]
}
```

**search** (queue view):
```json
{
  "queue_label": "Support"
}
```

## Response Format

All mixer responses follow a consistent format.

**Single ticket operations** (create, update, close, comment):
```json
{
  "success": true,
  "ticket_id": "3ec48de0-ef52-4c2b-b45c-b58f0ca5c1ef",
  "data": { ... }
}
```

For `update`, `close`, `comment`, and `find`, `request_data.ticket_id` must be this Bakery
internal UUID (not the external ticket number).

**Search operations:**
```json
{
  "success": true,
  "data": {
    "results": [ ... ],
    "count": 10,
    "total": 42
  }
}
```

**Errors:**
```json
{
  "success": false,
  "error": "Description of what went wrong"
}
```

## Configuration

All configuration is via environment variables. In Kubernetes, non-sensitive values are set directly in the deployment spec from `values.yaml`, and all credentials are injected via Kubernetes Secrets.

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `production` | Environment name (development enables debug) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DATABASE_HOST` | `bakery-mariadb` | MariaDB hostname |
| `DATABASE_PORT` | `3306` | MariaDB port |
| `DATABASE_USER` | `bakery` | Database username |
| `DATABASE_PASSWORD` | (required) | Database password (from Secret) |
| `DATABASE_NAME` | `bakery` | Database name |
| `MESSAGE_RETENTION_HOURS` | `24` | Hours to keep retrieved messages |
| `MAX_MESSAGES_PER_POLL` | `100` | Max messages returned per poll |
| `MIXER_TIMEOUT_SEC` | `30` | HTTP timeout for mixer API calls |
| `MIXER_MAX_RETRIES` | `3` | Max retry attempts for failed calls |

### Mixer Credentials

All credentials are stored in Kubernetes Secrets. Each mixer supports two modes:

1. **Existing Secret** -- reference a pre-created Secret by name via `existingSecret` in values.yaml
2. **Chart-managed Secret** -- provide values directly in values.yaml (chart creates the Secret)

| Variable | Mixer | Description |
|----------|-------|-------------|
| `SERVICENOW_URL` | ServiceNow | Instance URL |
| `SERVICENOW_USERNAME` | ServiceNow | Username |
| `SERVICENOW_PASSWORD` | ServiceNow | Password (Secret) |
| `JIRA_URL` | Jira | Instance URL |
| `JIRA_USERNAME` | Jira | Username |
| `JIRA_API_TOKEN` | Jira | API token (Secret) |
| `GITHUB_TOKEN` | GitHub | Personal access token (Secret) |
| `PAGERDUTY_API_KEY` | PagerDuty | API key (Secret) |
| `RACKSPACE_CORE_URL` | Rackspace Core | CTKAPI base URL (default: `https://ws.core.rackspace.com`) |
| `RACKSPACE_CORE_USERNAME` | Rackspace Core | Username |
| `RACKSPACE_CORE_PASSWORD` | Rackspace Core | Password (Secret) |

## Deployment

### Helm

Bakery is deployed as part of the PoundCake Helm chart. Enable it in `values.yaml`:

```yaml
bakery:
  enabled: true
```

The chart creates:
- **Deployment** with health/readiness probes
- **Service** (ClusterIP on port 8000)
- **Secret** for mixer credentials
- **MariaDB** instance (via MariaDB Operator) with database, user, and grants
- **Job** for database initialization (runs migrations on install/upgrade)

### Docker Image

The image is built via GitHub Actions and pushed to:

```
ghcr.io/aedan/poundcake-bakery
```

The Dockerfile uses a multi-stage build:
1. **Builder stage** -- installs Python dependencies from `bakery/requirements.txt`
2. **Runtime stage** -- copies only the virtual environment and `bakery/` application code

The final image contains no git history, tests, documentation, or development dependencies.

### Local Development

```bash
# From repo root
cd bakery

# Install dependencies
pip install -r requirements.txt

# Set required environment variables
export DATABASE_HOST=localhost
export DATABASE_PORT=3306
export DATABASE_USER=bakery
export DATABASE_PASSWORD=bakery
export DATABASE_NAME=bakery

# Run the application
python -m bakery.main
```

The application starts on `http://localhost:8000` with auto-reload enabled when `ENVIRONMENT=development`.

## Project Structure

```
bakery/
├── Dockerfile              # Multi-stage container build
├── requirements.txt        # Runtime Python dependencies
├── __init__.py             # Version (1.0.0)
├── main.py                 # FastAPI application entry point
├── config.py               # Environment variable configuration
├── database.py             # SQLAlchemy engine and session management
├── db_init.py              # Database initialization script (K8s Job)
├── models.py               # SQLAlchemy models (Message, TicketRequest, MixerConfig)
├── schemas.py              # Pydantic request/response schemas
├── alembic.ini             # Alembic migration configuration
├── alembic/
│   ├── env.py              # Alembic environment
│   ├── script.py.mako      # Migration template
│   └── versions/
│       └── 001_initial_schema.py
├── api/
│   ├── __init__.py
│   ├── health.py           # GET /health
│   ├── messages.py         # GET/DELETE /messages, POST /messages/cleanup
│   └── tickets.py          # POST /tickets, GET /tickets/{id}
└── mixer/
    ├── __init__.py
    ├── base.py             # BaseMixer ABC
    ├── factory.py          # MIXER_REGISTRY, get_mixer(), list_mixers()
    ├── servicenow.py       # ServiceNowMixer
    ├── jira.py             # JiraMixer
    ├── github.py           # GitHubMixer
    ├── pagerduty.py        # PagerDutyMixer
    └── rackspace_core.py   # RackspaceCoreMixer (CTKAPI)
```
