# API

FastAPI service exposing PoundCake endpoints.

## Key Endpoints

- `/api/v1/webhook` - Alertmanager intake
- `/api/v1/orders` - Orders CRUD
- `/api/v1/recipes` - Recipes CRUD
- `/api/v1/ingredients` - Ingredients CRUD
- `/api/v1/dishes` - Dishes query and updates
- `/api/v1/dishes/{dish_id}/ingredients` - Dish ingredient results
- `/api/v1/cook/*` - StackStorm bridge

## StackStorm

StackStorm access is via `/api/v1/cook/*` endpoints. Use `config/st2_api_key` for auth.

## Environment

```bash
DATABASE_URL=mysql+pymysql://user:pass@poundcake-mariadb:3306/poundcake
POUNDCAKE_STACKSTORM_URL=http://poundcake-st2api:9101
POUNDCAKE_AUTH_DEV_USERNAME=admin
POUNDCAKE_AUTH_DEV_PASSWORD=change-me
POUNDCAKE_AUTH_INTERNAL_API_KEY=shared-internal-key
```

When auth is enabled, all API endpoints except `/api/v1/health` and `/api/v1/auth/login` require
authentication. Internal services should send `X-Internal-API-Key`.
