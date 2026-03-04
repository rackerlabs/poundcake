# Architecture

## Summary

PoundCake is a stateless FastAPI service with background workers. The API accepts webhooks, stores orders in MariaDB, and workers orchestrate ingredient execution per dish across supported engines.

## Key Services

- **API**: Intake, CRUD, unified execution orchestration, and DB access.
- **Prep Chef**: Converts new orders into dishes.
- **Chef**: Claims dishes and triggers StackStorm workflows.
- **Timer**: Monitors workflow executions and persists results.
- **Dishwasher**: Syncs StackStorm actions/packs into Ingredients/Recipes.

## Data Model (Core)

- `orders`: Alert intake and processing status.
- `recipes`: Workflow templates and metadata.
- `ingredients`: StackStorm actions + default parameters.
- `recipe_ingredients`: Ordered list of ingredients per recipe.
- `dishes`: Execution instance of a recipe for an order.
- `dish_ingredients`: Per-task execution results and timestamps.

## Execution Flow

1. Alertmanager POSTs `/api/v1/webhook`.
2. `prep-chef` claims orders and calls `/api/v1/dishes/cook/{order_id}`.
3. `chef` claims dishes, registers the workflow, and executes it via `/api/v1/cook/execute` (`execution_engine=stackstorm`).
4. `timer` polls StackStorm and updates `dishes` and `dish_ingredients`.
5. `dishwasher` syncs StackStorm actions/packs into the database.

## Order Workflow Graph (States + Bakery Calls)

```mermaid
stateDiagram-v2
    [*] --> new: firing webhook\nPOST /api/v1/webhook -> pre_heat creates order

    new --> processing: prep-chef cook\nPOST /api/v1/dishes/cook/{order_id}
    processing --> resolving: dish terminal (non-catch-all)\nPATCH /api/v1/dishes/{dish_id}

    new --> resolving: resolved webhook\npre_heat transition check
    processing --> resolving: resolved webhook\npre_heat transition check
    resolving --> resolving: resolved webhook (idempotent)\npre_heat keeps resolving
    resolving --> processing: re-fire while resolving\npre_heat sets processing

    resolving --> complete: resolve success\nPOST /api/v1/orders/{order_id}/resolve
    resolving --> failed: resolve blocking failure\nPOST /api/v1/orders/{order_id}/resolve
    new --> canceled: manual order update\nPUT/PATCH /api/v1/orders/{order_id}
    processing --> canceled: manual order update\nPUT/PATCH /api/v1/orders/{order_id}
    resolving --> canceled: manual order update\nPUT/PATCH /api/v1/orders/{order_id}

    note right of processing
      Dish-terminal Bakery sync (_sync_bakery_for_terminal_dish):
      - POST /api/v1/tickets (create if missing)
      - PATCH /api/v1/tickets/{ticket_id} (reopen if confirmed_solved)
      - POST /api/v1/tickets/{ticket_id}/comments (execution summary)
      - GET /api/v1/operations/{operation_id} (poll loop)
    end note

    note right of resolving
      Resolved-webhook Bakery sync (pre_heat):
      - POST /api/v1/tickets/{ticket_id}/comments (clear note)
      - POST /api/v1/tickets/{ticket_id}/close (if auto-remediation succeeded)
      - GET /api/v1/operations/{operation_id} (poll loop)

      Resolve-phase comms (/orders/{id}/resolve):
      - tickets.create | tickets.update | tickets.comment | tickets.close
      - mapped Bakery endpoints + operation polling when operation_id is returned
    end note

    note right of complete
      Terminal order statuses:
      complete | failed | canceled
      - immutable in order update logic
      - cannot transition to another terminal status
    end note
```
