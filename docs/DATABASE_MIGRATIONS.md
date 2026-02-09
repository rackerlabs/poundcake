# Database Migrations

PoundCake uses Alembic. The initial migration defines all tables including `dish_ingredients`.

Key column naming conventions:
- `expected_duration_sec`
- `timeout_duration_sec`

Examples:
- `ingredients.expected_duration_sec`
- `dishes.expected_duration_sec`

Commands:

```bash
python scripts/migrate.py current
python scripts/migrate.py upgrade
python scripts/migrate.py create "description"
```
