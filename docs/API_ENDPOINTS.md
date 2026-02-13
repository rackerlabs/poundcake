# API Endpoints

This document reflects the current PoundCake API surface.

## Base
- `GET /`
- `GET /metrics`

## Versioned API (prefix: `/api/v1`)

### Auth
- `POST /auth/login`
- `POST /auth/logout`

### System & Monitoring
- `GET /health`
- `GET /stats`
- `GET /settings`

### Prometheus
- `GET /prometheus/rules`
- `GET /prometheus/rule-groups`
- `GET /prometheus/metrics`
- `GET /prometheus/labels`
- `GET /prometheus/label-values/{label_name}`
- `GET /prometheus/health`
- `POST /prometheus/reload`
- `POST /prometheus/rules`
- `PUT /prometheus/rules/{rule_name}`
- `DELETE /prometheus/rules/{rule_name}`

### Cook (StackStorm)
- `POST /cook/execute`
- `GET /cook/executions/{execution_id}`
- `GET /cook/executions`
- `GET /cook/executions/{execution_id}/tasks`
- `PUT /cook/executions/{execution_id}` (cancel)
- `DELETE /cook/executions/{execution_id}` (delete record)
- `POST /cook/workflows/register`
- `POST /cook/sync`
- `GET /cook/actions`
- `GET /cook/actions/{action_ref:path}`
- `GET /cook/packs`

### Recipes
- `POST /recipes/`
- `GET /recipes/`
- `GET /recipes/{recipe_id}`
- `GET /recipes/by-name/{recipe_name}`
- `PUT /recipes/{recipe_id}`
- `PATCH /recipes/{recipe_id}`
- `DELETE /recipes/{recipe_id}`

### Ingredients
- `POST /ingredients/`
- `GET /ingredients/`
- `GET /ingredients/{ingredient_id}`
- `PUT /ingredients/{ingredient_id}`
- `PATCH /ingredients/{ingredient_id}`
- `DELETE /ingredients/{ingredient_id}`
- `GET /ingredients/by-name/{recipe_name}`
- `GET /ingredients/by-recipe/{recipe_id}`

### Orders
- `GET /orders`
- `POST /orders`
- `GET /orders/{order_id}`
- `PUT /orders/{order_id}`

### Dishes
- `POST /dishes/cook/{order_id}`
- `GET /dishes`
- `POST /dishes/{dish_id}/claim`
- `PUT /dishes/{dish_id}`
- `PATCH /dishes/{dish_id}`
- `GET /dishes/{dish_id}/ingredients`
- `POST /dishes/{dish_id}/ingredients/bulk`

### Webhook
- `POST /webhook`

## Debug (only when `settings.debug=true`)
- `GET /docs`
- `GET /redoc`
- `GET /openapi.json`
