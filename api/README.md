# API Service

The API service is the main FastAPI application providing REST endpoints for PoundCake.

## Purpose

The API service:
1. Receives alert webhooks from Prometheus Alertmanager
2. Provides REST API for managing recipes, alerts, and ovens
3. Handles the "pre_heat" function to create ovens from alerts
4. Manages database schema via Alembic migrations
5. Exposes health checks and metrics

## Architecture

### Key Components

**FastAPI Application:**
- REST API endpoints
- Background task processing
- Request ID tracking (pre_heat middleware)
- Health checks and metrics

**Database Management:**
- SQLAlchemy ORM models
- Alembic migrations
- Automatic schema initialization on startup

**Services:**
- `pre_heat` - Creates ovens from alerts
- `stackstorm_service` - Integrates with StackStorm
- `prometheus_service` - Metrics collection

## Running

### In Docker Compose (Normal Operation)
```bash
docker compose up -d
```

The API automatically runs database migrations on startup.

### Standalone (Development)
```bash
export DATABASE_URL=mysql+pymysql://poundcake:poundcake@localhost:3306/poundcake
export ST2_API_URL=http://localhost:9101/v1
export ST2_API_KEY=your-api-key

uvicorn api.main:app --reload
```

## Database Migrations

### Automatic Migration (Greenfield Deployments)

For development with greenfield deployments, the API **automatically runs migrations on startup**:

```python
# api/core/database.py
def init_db():
    """Run Alembic migrations to latest version."""
    command.upgrade(alembic_cfg, "head")

# api/main.py
@app.on_event("startup")
async def startup_event():
    init_db()  # Auto-run migrations
```

**What this means:**
- Fresh database? → Migrations create all tables on first API startup
- No manual migration commands needed for greenfield deployments
- Schema is always up-to-date

### Creating New Migrations (Development)

When you modify database models, create a new migration:

```bash
# Create migration for schema changes
python api/migrate.py create "add new column to alerts table"

# The API will automatically apply it on next startup
docker compose restart api
```

### Manual Migration Management (Advanced)

The `api/migrate.py` script provides manual control when needed:

```bash
# Check current schema version
python api/migrate.py current

# Show migration history
python api/migrate.py history

# Manually upgrade (not needed for greenfield)
python api/migrate.py upgrade head

# Create new migration
python api/migrate.py create "description"

# Rollback (development only)
python api/migrate.py downgrade -1
```

### When to Use migrate.py

**Use it for:**
- Creating NEW migrations when you modify models
- Debugging schema issues
- Checking migration history

**Don't need it for:**
- Normal greenfield deployments (auto-migrates)
- Fresh database setup (auto-migrates)
- Production deployments without schema changes

## Directory Structure

```
api/
├── api/                    # Route handlers
│   ├── routes.py          # Main API routes
│   ├── ovens.py           # Oven management endpoints
│   ├── recipes.py         # Recipe management endpoints
│   ├── alerts.py          # Alert management endpoints
│   ├── health.py          # Health check endpoints
│   └── prometheus.py      # Metrics endpoint
│
├── core/                   # Core functionality
│   ├── config.py          # Configuration management
│   ├── database.py        # Database setup & migrations
│   ├── logging.py         # Logging configuration
│   └── middleware.py      # Request ID middleware
│
├── models/                 # SQLAlchemy models
│   └── models.py          # Database models (Alert, Recipe, Oven, Ingredient)
│
├── schemas/                # Pydantic schemas
│   └── schemas.py         # API request/response schemas
│
├── services/               # Business logic
│   ├── pre_heat.py        # Alert → Oven creation
│   ├── stackstorm_service.py  # StackStorm integration
│   └── prometheus_service.py  # Metrics collection
│
├── main.py                 # Application entry point
└── migrate.py              # Migration management script
```

## API Endpoints

### Core Endpoints
- `POST /api/v1/webhook` - Receive Alertmanager webhooks
- `GET /api/v1/alerts` - Query alerts with filters
- `POST /api/v1/alerts/process` - Execute recipes for alerts

### Recipe Management
- `POST /api/recipes/` - Create recipe
- `GET /api/recipes/` - List recipes
- `GET /api/recipes/{id}` - Get recipe by ID
- `PUT /api/recipes/{id}` - Update recipe
- `DELETE /api/recipes/{id}` - Delete recipe

### Oven Management
- `GET /api/v1/ovens` - List ovens
- `GET /api/v1/ovens/{id}` - Get oven details
- `GET /api/v1/ovens/{id}/ingredients` - Get oven ingredients

### Health & Monitoring
- `GET /api/v1/health` - Full health check
- `GET /api/v1/health/live` - Liveness probe
- `GET /api/v1/health/ready` - Readiness probe
- `GET /api/v1/stats` - System statistics
- `GET /metrics` - Prometheus metrics

See `docs/API_ENDPOINTS.md` for complete documentation.

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname

# StackStorm
ST2_API_URL=http://st2api:9101/v1
ST2_API_KEY=your-api-key

# Application
LOG_LEVEL=INFO
DEBUG=false
```

## Development

### Adding New Endpoints

1. Create route handler in `api/api/`
2. Register route in `api/api/routes.py`
3. Add Pydantic schemas if needed
4. Test the endpoint

### Modifying Database Schema

1. Edit models in `api/models/models.py`
2. Create migration:
   ```bash
   python api/migrate.py create "description of change"
   ```
3. Restart API to apply:
   ```bash
   docker compose restart api
   ```

### Testing

```bash
# Run tests
pytest tests/

# Test specific endpoint
pytest tests/test_api_health.py

# With coverage
pytest --cov=api tests/
```

## Logging

The API uses structured JSON logging:

```python
logger.info("Processing alert", 
    alert_id=alert.id,
    req_id=req_id,
    alertname=alert.alertname
)
```

View logs:
```bash
docker logs -f poundcake-api
```

## Monitoring

### Health Checks

```bash
# Full health check
curl http://localhost:8000/api/v1/health

# Quick liveness
curl http://localhost:8000/api/v1/health/live
```

### Metrics

```bash
# Prometheus metrics
curl http://localhost:8000/metrics
```

### Database

```bash
# Check migration version
python api/migrate.py current

# Check database connection
docker exec poundcake-mariadb mysql -upoundcake -ppoundcake -e "SHOW DATABASES;"
```

## Troubleshooting

### Issue: API won't start

**Check logs:**
```bash
docker logs poundcake-api
```

**Common causes:**
- Database connection failed
- Migration errors
- Port 8000 already in use

### Issue: Migration errors

**Check migration status:**
```bash
python api/migrate.py current
python api/migrate.py history
```

**Reset database (dev only):**
```bash
docker compose down -v
docker compose up -d
# Migrations run automatically
```

### Issue: StackStorm integration not working

**Check configuration:**
```bash
docker exec poundcake-api env | grep ST2
```

**Test connection:**
```bash
docker exec poundcake-api curl http://st2api:9101/v1
```

## Related Services

- **Oven Service:** Processes ovens created by API
- **Timer Service:** Monitors executions started by oven service
- **StackStorm:** Executes remediation workflows

## Related Documentation

- **API Endpoints:** `../docs/API_ENDPOINTS.md`
- **Architecture:** `../docs/ARCHITECTURE.md`
- **Database Migrations:** `../docs/DATABASE_MIGRATIONS.md`
- **Troubleshooting:** `../docs/TROUBLESHOOTING.md`
