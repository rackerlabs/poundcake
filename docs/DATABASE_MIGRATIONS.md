# Database Migrations

PoundCake uses Alembic, but during alpha we keep one full-schema baseline revision.

Current policy:

- fresh installs only
- do not add chained Alembic revisions
- if schema changes are needed, edit the single baseline migration file

Baseline files:

- PoundCake API: `alembic/versions/2026_02_03_1600_initial_schema.py`
- Helm-shipped API copy: `helm/files/poundcake-alembic/versions/2026_02_03_1600_initial_schema.py`

Key column naming conventions still in use:

- `expected_duration_sec`
- `timeout_duration_sec`

Examples:

- `ingredients.expected_duration_sec`
- `dishes.expected_duration_sec`

Commands:

```bash
python api/migrate.py current
python api/migrate.py history
python api/migrate.py upgrade
```
