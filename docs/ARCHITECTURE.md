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
2. `prep-chef` claims orders and calls `/api/v1/orders/{order_id}/dispatch`.
3. `chef` claims dishes, registers the workflow, and executes it via `/api/v1/cook/execute` (`execution_engine=stackstorm`).
4. `timer` polls StackStorm and updates `dishes` and `dish_ingredients`.
5. `dishwasher` syncs StackStorm actions/packs into the database.

## Unified Dispatch Order Diagram

```mermaid
flowchart TD
  A["Alertmanager webhook (firing)"] --> B["API pre_heat upserts Order<br/>processing_status=new"]
  B --> C["prep-chef polls Orders(new,resolving)"]
  C --> D["POST /api/v1/orders/{order_id}/dispatch"]

  D --> E{"order.processing_status"}
  E -->|new| F["Dispatch run_phase=firing"]
  E -->|resolving| G["Dispatch run_phase=resolving"]
  E -->|other| H["409 not dispatchable"]

  F --> I["Create/reuse firing Dish<br/>seed phase-eligible dish_ingredients<br/>(can include StackStorm + Bakery comms)"]
  G --> J["Create/reuse resolving Dish<br/>seed Bakery comms only<br/>(inject fallback comms if recipe has none)"]

  I --> K["Dish status=new"]
  J --> K

  K --> L["chef claims dish -> processing"]
  L --> M["chef loads dish_ingredients"]
  M --> N{"stackstorm pending rows? (firing only)"}

  N -->|yes| O["Filter recipe to stackstorm rows<br/>POST /cook/workflows/register<br/>POST /cook/execute (stackstorm)<br/>PATCH dish.execution_ref"]
  N -->|no| P{"bakery pending rows?"}

  O --> Q["timer polls /cook/executions*"]
  Q --> R["POST /dishes/{id}/ingredients/bulk<br/>upsert stackstorm task status/result"]
  R --> P

  P -->|yes| S["Execute bakery rows via /cook/execute (per row)<br/>upsert each dish_ingredient in place"]
  P -->|no| T["Finalize dish"]

  S --> T

  T --> U{"dish.run_phase"}
  U -->|firing| V["Dish terminal -> order moves to resolving"]
  U -->|resolving| W["Dish terminal -> order complete/failed"]

  X["Alertmanager webhook (resolved)"] --> Y["pre_heat sets order.processing_status=resolving"]
  Y --> C
```

## Order Workflow Graph (States + Bakery Calls)

```mermaid
stateDiagram-v2
    [*] --> new: firing webhook\nPOST /api/v1/webhook -> pre_heat creates order

    new --> processing: prep-chef cook\nPOST /api/v1/orders/{order_id}/dispatch
    processing --> resolving: dish terminal (non-catch-all)\nPATCH /api/v1/dishes/{dish_id}

    new --> resolving: resolved webhook\npre_heat transition check
    processing --> resolving: resolved webhook\npre_heat transition check
    resolving --> resolving: resolved webhook (idempotent)\npre_heat keeps resolving
    resolving --> processing: re-fire while resolving\npre_heat sets processing

    resolving --> complete: resolve success\nPOST /api/v1/orders/{order_id}/dispatch
    resolving --> failed: resolve blocking failure\nPOST /api/v1/orders/{order_id}/dispatch
    new --> canceled: manual order update\nPUT/PATCH /api/v1/orders/{order_id}
    processing --> canceled: manual order update\nPUT/PATCH /api/v1/orders/{order_id}
    resolving --> canceled: manual order update\nPUT/PATCH /api/v1/orders/{order_id}

    note right of processing
      Dish-terminal communication sync:
      - PoundCake executes Bakery communication actions through /api/v1/cook/execute
      - canonical operations are open, notify, update, and close
      - Bakery maps those provider-neutral actions to provider-native create/comment/update/close calls
      - asynchronous Bakery operations are polled until terminal state
    end note

    note right of resolving
      Resolved-webhook communication sync:
      - resolve-phase dispatch seeds communication-only Bakery work in resolving
      - if a recipe has no resolving communication route, fallback comms is injected
      - successful auto-remediation communicates on the resolved path instead of opening a firing-phase ticket
      - final remote communication state is refreshed back onto the PoundCake order
    end note

    note right of complete
      Terminal order statuses:
      complete | failed | canceled
      - immutable in order update logic
      - cannot transition to another terminal status
    end note
```
