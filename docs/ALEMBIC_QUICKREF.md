# Alembic Quick Reference

Quick command reference for PoundCake database migrations.

## Common Commands

```bash
# Upgrade to latest version
python api/migrate.py upgrade

# Downgrade one version
python api/migrate.py downgrade

# Check current version
python api/migrate.py current

# View migration history
python api/migrate.py history

# Create new migration (auto-detect changes)
python api/migrate.py create "description of change"

# Force stamp version (no migration execution)
python api/migrate.py stamp head
```

## Example Workflow

### Adding a New Column

```bash
# 1. Modify the model
# api/models/models.py
class Alert(Base):
    priority = Column(String(20), nullable=True)  # NEW

# 2. Generate migration
python api/migrate.py create "add priority to alerts"

# 3. Review generated file
cat alembic/versions/2026_*_add_priority_to_alerts.py

# 4. Apply migration
python api/migrate.py upgrade

# 5. Verify
python api/migrate.py current
```

## Production Deployment

```bash
# 1. Backup
mysqldump -u poundcake -p poundcake > backup_$(date +%Y%m%d).sql

# 2. Test on staging
DATABASE_URL=mysql+pymysql://user:pass@staging-db/poundcake \
  python api/migrate.py upgrade

# 3. Apply to production
python api/migrate.py upgrade

# 4. Rollback if needed
python api/migrate.py downgrade
```

## Files

- `alembic.ini` - Configuration
- `alembic/env.py` - Environment setup
- `alembic/versions/` - Migration scripts
- `api/migrate.py` - Management script

## Help

```bash
python api/migrate.py help
```

---

See **DATABASE_MIGRATIONS.md** for complete documentation.
