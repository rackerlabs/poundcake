# Alembic Quick Reference

Alpha rule:
- Keep one full-schema baseline revision per service.
- Edit the baseline file when schema changes are needed.
- Do not create chained revisions for fresh-install alpha work.
- Baseline startup must be restart-safe because MySQL/MariaDB DDL is not transactional.

```bash
# Current version
python api/migrate.py current

# Apply migrations
python api/migrate.py upgrade
```

Naming conventions:
- `expected_duration_sec`
- `timeout_duration_sec`
