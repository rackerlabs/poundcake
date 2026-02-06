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
POUNDCAKE_STACKSTORM_URL=http://stackstorm-api:9101
```
