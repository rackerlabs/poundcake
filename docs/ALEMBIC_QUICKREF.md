# Alembic Quick Reference

Quick command reference for PoundCake database migrations.

## Common Commands

```bash
# Upgrade to latest version
python scripts/migrate.py upgrade

# Downgrade one version
python scripts/migrate.py downgrade

# Check current version
python scripts/migrate.py current

# View migration history
python scripts/migrate.py history

# Create new migration (auto-detect changes)
python scripts/migrate.py create "description of change"

# Force stamp version (no migration execution)
python scripts/migrate.py stamp head
```

## Example Workflow

### Adding a New Column

```bash
# 1. Modify the model
# api/models/models.py
class Alert(Base):
    priority = Column(String(20), nullable=True)  # NEW

# 2. Generate migration
python scripts/migrate.py create "add priority to alerts"

# 3. Review generated file
cat alembic/versions/2026_*_add_priority_to_alerts.py

# 4. Apply migration
python scripts/migrate.py upgrade

# 5. Verify
python scripts/migrate.py current
```

## Production Deployment

```bash
# 1. Backup
mysqldump -u poundcake -p poundcake > backup_$(date +%Y%m%d).sql

# 2. Test on staging
DATABASE_URL=mysql+pymysql://user:pass@staging-db/poundcake \
  python scripts/migrate.py upgrade

# 3. Apply to production
python scripts/migrate.py upgrade

# 4. Rollback if needed
python scripts/migrate.py downgrade
```

## Files

- `alembic.ini` - Configuration
- `alembic/env.py` - Environment setup
- `alembic/versions/` - Migration scripts
- `scripts/migrate.py` - Management script

## Help

```bash
python scripts/migrate.py help
```

---

See **DATABASE_MIGRATIONS.md** for complete documentation.
