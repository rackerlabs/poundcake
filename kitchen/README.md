# Kitchen Services

This directory contains the background workers that drive execution.

## Services

- **prep-chef**: Claims new orders and creates dishes.
- **chef**: Claims dishes and triggers workflow execution via `/api/v1/cook/execute` (`execution_engine=stackstorm`).
- **timer**: Monitors StackStorm workflow executions and updates dish/dish_ingredients.
- **dishwasher**: Syncs StackStorm actions/packs into Ingredients/Recipes.

## Flow (High Level)

1. Alertmanager posts `/api/v1/webhook`.
2. `prep-chef` polls `/api/v1/orders?processing_status=new` and calls `/api/v1/dishes/cook/{order_id}`.
3. `chef` claims dishes via `/api/v1/dishes/{dish_id}/claim` and executes via `/api/v1/cook/execute`.
4. `timer` polls `/api/v1/dishes?processing_status=processing` and writes results to `/api/v1/dishes/{dish_id}` and `/api/v1/dishes/{dish_id}/ingredients/bulk`.

## Environment Variables

- `POUNDCAKE_API_URL` - PoundCake API base URL (default: `http://poundcake:8080`; workers append `/api/v1`).
- `POLL_INTERVAL` - Poll interval in seconds.

## Debug Tips

- Verify StackStorm is running: `curl http://poundcake-st2api:9101/v1`
- List dishes: `curl http://localhost:8000/api/v1/dishes`
