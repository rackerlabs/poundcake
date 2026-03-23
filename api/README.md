# API

FastAPI service exposing PoundCake endpoints.

## Flow Diagram

```mermaid
flowchart LR
  Client["Operator or Worker"] --> Auth["Auth + Routing"]
  Auth --> API["FastAPI Endpoints"]
  API --> Orders["Orders / Dishes APIs"]
  API --> Cook["/api/v1/cook/*"]
  Cook --> Engines["StackStorm or Bakery"]
```

## Key Endpoints

- `/api/v1/webhook` - Alertmanager intake
- `/api/v1/orders` - Orders CRUD
- `/api/v1/recipes` - Recipes CRUD
- `/api/v1/ingredients` - Ingredients CRUD
- `/api/v1/dishes` - Dishes query and updates
- `/api/v1/dishes/{dish_id}/ingredients` - Dish ingredient results
- `/api/v1/cook/*` - Unified execution + StackStorm tooling

## Execution

`POST /api/v1/cook/execute` is engine-agnostic and supports `stackstorm` + `bakery`.
StackStorm action/workflow tooling remains available via `/api/v1/cook/*` endpoints.

## Environment

```bash
DATABASE_URL=mysql+pymysql://user:pass@poundcake-mariadb:3306/poundcake
POUNDCAKE_STACKSTORM_URL=http://poundcake-st2api:9101
POUNDCAKE_AUTH_DEV_USERNAME=admin
POUNDCAKE_AUTH_DEV_PASSWORD=change-me
POUNDCAKE_AUTH_SERVICE_TOKEN=shared-internal-key
```

When auth is enabled, all API endpoints except `/api/v1/health` and `/api/v1/auth/login` require
authentication. Internal services should send either `X-Auth-Token` or
`Authorization: Bearer <internal-api-key>`.
