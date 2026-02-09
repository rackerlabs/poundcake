# Database Migrations with Alembic

PoundCake uses Alembic for database schema management and migrations. This allows for version-controlled schema changes and safe upgrades/downgrades.

**Version:** 0.0.1

---

## Overview

### Why Alembic?

- **Version Control:** Track database schema changes over time
- **Rollback Support:** Safely downgrade to previous versions
- **Team Collaboration:** Share schema changes through migrations
- **Production Safety:** Test migrations before applying to production
- **Auto-detection:** Automatically detect model changes

### Architecture

```
alembic/
├── versions/           # Migration scripts
│   └── 001_initial_schema.py
├── env.py             # Migration environment config
└── script.py.mako     # Migration template

alembic.ini            # Alembic configuration
api/migrate.py     # Migration management script
```

---

## Quick Start

### 1. Initial Setup (First Time)

Run migrations to create tables:

```bash
python api/migrate.py upgrade
```

This will:
- Create all tables (recipes, alerts, ovens)
- Create indexes
- Set up foreign key relationships

### 2. Check Current Version

```bash
python api/migrate.py current
```

Output:
```
Current database revision:
001 (head)
```

### 3. View Migration History

```bash
python api/migrate.py history
```

---

## Common Operations

### Upgrade Database

```bash
# Upgrade to latest version
python api/migrate.py upgrade

# Upgrade by one version
python api/migrate.py upgrade +1

# Upgrade to specific version
python api/migrate.py upgrade 002
```

### Downgrade Database

```bash
# Downgrade by one version
python api/migrate.py downgrade

# Downgrade by two versions
python api/migrate.py downgrade -2

# Downgrade to specific version
python api/migrate.py downgrade 001

# Downgrade to initial state (empty database)
python api/migrate.py downgrade base
```

### Check Status

```bash
# Current version
python api/migrate.py current

# Migration history
python api/migrate.py history
```

---

## Creating New Migrations

### Automatic Migration Generation

When you modify models, Alembic can auto-detect changes:

```bash
python api/migrate.py create "add status column to alerts"
```

This will:
1. Compare current models with database schema
2. Generate migration file with detected changes
3. Save to `alembic/versions/`

### Example: Adding a Column

**1. Modify the model:**

```python
# api/models/models.py
class Alert(Base):
    # ... existing columns ...
    priority = Column(String(20), nullable=True)  # NEW COLUMN
```

**2. Generate migration:**

```bash
python api/migrate.py create "add priority column to alerts"
```

**3. Review generated migration:**

```python
# alembic/versions/2026_01_23_1700-abc123_add_priority_column_to_alerts.py

def upgrade() -> None:
    op.add_column('poundcake_alerts', 
        sa.Column('priority', sa.String(length=20), nullable=True))

def downgrade() -> None:
    op.drop_column('poundcake_alerts', 'priority')
```

**4. Apply migration:**

```bash
python api/migrate.py upgrade
```

### Manual Migration Creation

For complex changes, create a manual migration:

```bash
# Create empty migration
alembic revision -m "complex schema change"
```

Then edit the generated file:

```python
def upgrade() -> None:
    # Add your custom migration logic
    op.execute("UPDATE poundcake_alerts SET status='active' WHERE status IS NULL")
    op.alter_column('poundcake_alerts', 'status', nullable=False)

def downgrade() -> None:
    # Add rollback logic
    op.alter_column('poundcake_alerts', 'status', nullable=True)
```

---

## Migration Best Practices

### 1. Always Test Migrations

```bash
# Test on development database first
DATABASE_URL=mysql+pymysql://user:pass@dev-db/poundcake \
  python api/migrate.py upgrade

# Verify it worked
python api/migrate.py current

# Test rollback
python api/migrate.py downgrade
```

### 2. Review Generated Migrations

**Always review auto-generated migrations before applying:**

```bash
# Generate migration
python api/migrate.py create "my changes"

# Review file in alembic/versions/
cat alembic/versions/2026_01_23_*.py

# Apply if looks good
python api/migrate.py upgrade
```

### 3. Keep Migrations Small

**Good:**
- One logical change per migration
- Clear migration message
- Tested upgrade and downgrade

**Bad:**
- Multiple unrelated changes
- Vague message like "update schema"
- Untested downgrade path

### 4. Data Migrations

When changing data, split into two migrations:

```python
# Migration 1: Add column with nullable=True
def upgrade():
    op.add_column('alerts', Column('status', String(20), nullable=True))

# Migration 2: Populate data and make non-nullable
def upgrade():
    op.execute("UPDATE alerts SET status='new' WHERE status IS NULL")
    op.alter_column('alerts', 'status', nullable=False)
```

### 5. Handle Existing Data

```python
def upgrade():
    # Add column as nullable first
    op.add_column('alerts', Column('priority', String(20), nullable=True))
    
    # Populate existing rows
    op.execute("UPDATE alerts SET priority='medium' WHERE priority IS NULL")
    
    # Now make it non-nullable if needed
    op.alter_column('alerts', 'priority', nullable=False)
```

---

## Production Deployment

### Safe Production Upgrade Process

**1. Backup Database**

```bash
mysqldump -u poundcake -p poundcake > backup_$(date +%Y%m%d).sql
```

**2. Test Migration on Staging**

```bash
# On staging environment
python api/migrate.py upgrade
```

**3. Verify Staging**

```bash
# Check version
python api/migrate.py current

# Test application
curl http://staging:8000/api/v1/health
```

**4. Apply to Production**

```bash
# On production environment
python api/migrate.py upgrade
```

**5. Verify Production**

```bash
python api/migrate.py current
curl http://production:8000/api/v1/health
```

### Rollback Plan

Always have a rollback plan:

```bash
# If something goes wrong, downgrade
python api/migrate.py downgrade

# Or restore from backup
mysql -u poundcake -p poundcake < backup_20260123.sql
```

---

## Docker Deployments

### Dockerfile Integration

The application automatically runs migrations on startup:

```python
# api/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()  # Runs: alembic upgrade head
    yield
```

### Manual Migration in Docker

```bash
# Run migrations in container
docker exec poundcake-api python api/migrate.py upgrade

# Check status
docker exec poundcake-api python api/migrate.py current
```

### Init Container Pattern (Kubernetes)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: poundcake-api
spec:
  initContainers:
  - name: migrate
    image: poundcake-api:latest
    command: ["python", "api/migrate.py", "upgrade"]
    env:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: poundcake-db
          key: url
  containers:
  - name: api
    image: poundcake-api:latest
```

---

## Troubleshooting

### Migration Failed

```bash
# Check current state
python api/migrate.py current

# View migration history
python api/migrate.py history

# Try to fix by stamping current version
python api/migrate.py stamp 001
```

### Database Out of Sync

```bash
# Force stamp to current code version
python api/migrate.py stamp head

# Or regenerate from scratch
python api/migrate.py downgrade base
python api/migrate.py upgrade head
```

### Merge Conflicts in Migrations

```bash
# List branches
alembic branches

# Merge branches
alembic merge -m "merge migrations" head1 head2
```

---

## Configuration

### alembic.ini

Main configuration file:

```ini
[alembic]
script_location = alembic
file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s
sqlalchemy.url = mysql+pymysql://poundcake:poundcake@localhost/poundcake
```

**Note:** `sqlalchemy.url` is overridden from environment variables in production.

### alembic/env.py

Environment configuration:

```python
# Import all models to ensure they're detected
from api.models.models import Alert, Recipe, Oven

# Set target metadata
target_metadata = Base.metadata

# Override URL from settings
config.set_main_option('sqlalchemy.url', settings.database_url)
```

---

## Migration File Structure

```python
"""add priority to alerts

Revision ID: abc123
Revises: 001
Create Date: 2026-01-23 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'abc123'
down_revision = '001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column('poundcake_alerts', 
        sa.Column('priority', sa.String(20), nullable=True))

def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column('poundcake_alerts', 'priority')
```

---

## Alembic Commands Reference

### Via api/migrate.py (Recommended)

```bash
python api/migrate.py upgrade       # Upgrade to head
python api/migrate.py downgrade     # Downgrade one version
python api/migrate.py current       # Show current version
python api/migrate.py history       # Show migration history
python api/migrate.py create "msg"  # Create new migration
python api/migrate.py stamp head    # Mark as current version
```

### Direct Alembic Commands

```bash
# Upgrade
alembic upgrade head
alembic upgrade +1
alembic upgrade 001

# Downgrade
alembic downgrade -1
alembic downgrade base

# Info
alembic current
alembic history
alembic show 001

# Create
alembic revision -m "message"
alembic revision --autogenerate -m "message"

# Stamp
alembic stamp head
```

---

## FAQ

### Q: Do I need to stop the application to run migrations?

**A:** For most migrations (adding columns, indexes), no. For breaking changes (removing columns, changing types), yes - take a maintenance window.

### Q: How do I reset the database?

```bash
# Downgrade to empty
python api/migrate.py downgrade base

# Upgrade back to latest
python api/migrate.py upgrade
```

### Q: Can I skip migrations?

**A:** No. Migrations must be applied in order. Use `stamp` if you need to mark a version without running it.

### Q: What if my migration fails halfway?

**A:** Most databases support transactional DDL. If migration fails, it rolls back. Check `python api/migrate.py current` and fix the migration.

### Q: How do I handle production with no downtime?

Use a multi-step process:
1. Deploy code compatible with old and new schema
2. Run migration
3. Deploy new code only using new schema

---

## Summary

[OK] **Use Alembic for all schema changes**  
[OK] **Test migrations before production**  
[OK] **Keep migrations small and focused**  
[OK] **Always review auto-generated migrations**  
[OK] **Backup before production migrations**  
[OK] **Document complex migrations**  

---

**Version:** 0.0.1  
**Date:** January 23, 2026  
**Status:** Production Ready
