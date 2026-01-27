"""Refactored SQLAlchemy models - PoundCake v2.0 with Recipe/Oven architecture.

NEW ARCHITECTURE:
- Recipe: Defines PoundCake-specific tasks that map to StackStorm actions/workflows
- Oven: Executes recipes and tracks execution status
- Alerts: Stores and tracks alert auto-remediation status

NO MORE:
- Celery/Redis for async processing
- Complex task execution tracking
- Multiple execution link tables
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from api.core.database import Base

# ==============================================================================
# RECIPE TABLE - Defines tasks that map to StackStorm workflows
# ==============================================================================


class Recipe(Base):
    """Defines PoundCake-specific tasks that map to StackStorm actions/workflows.

    A recipe is a template that specifies:
    - What StackStorm workflow/action to execute
    - What sequence of tasks to perform (task_list)
    - Timing constraints for execution and cleanup
    """

    __tablename__ = "poundcake_recipes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Task list: comma-separated UUIDs representing task execution order
    # Example: "uuid1,uuid2,uuid3" for sequential execution
    task_list = Column(Text, nullable=True)

    # StackStorm workflow/action reference
    st2_workflow_ref = Column(String(256), nullable=False, index=True)

    # Timing constraints
    time_to_complete = Column(DateTime, nullable=True)  # Expected completion time
    time_to_clear = Column(DateTime, nullable=True)  # Time to clear/cleanup

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ovens = relationship("Oven", back_populates="recipe")

    __table_args__ = (
        Index("idx_recipe_name", "name"),
        Index("idx_recipe_st2_ref", "st2_workflow_ref"),
    )

    def __repr__(self) -> str:
        return f"<Recipe {self.name}>"


# ==============================================================================
# OVEN TABLE - Executes recipes and tracks execution
# ==============================================================================


class Oven(Base):
    """Performs actions defined in recipes and tracks execution status.

    The oven is the execution engine that:
    - Takes a recipe and executes it
    - Tracks the StackStorm execution
    - Links alerts to recipe executions
    - Manages execution lifecycle (new -> processing -> complete)
    """

    __tablename__ = "poundcake_ovens"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Request tracking (injected by pre_heat middleware)
    req_id = Column(String(36), nullable=False, index=True)

    # Foreign keys
    alert_id = Column(Integer, ForeignKey("poundcake_alerts.id"), nullable=True)
    recipe_id = Column(Integer, ForeignKey("poundcake_recipes.id"), nullable=False)
    
    # Task tracking - which task from recipe.task_list this oven represents
    task_id = Column(String(100), nullable=True, index=True)  # UUID from recipe.task_list

    # StackStorm execution tracking
    action_id = Column(String(100), nullable=True, index=True)  # ST2 execution ID
    action_result = Column(JSON, nullable=True)  # ST2 execution result

    # Status tracking
    status = Column(
        String(20), nullable=False, default="new", index=True
    )  # new, processing, complete

    # Timing
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    alert = relationship("Alert", back_populates="ovens")
    recipe = relationship("Recipe", back_populates="ovens")

    __table_args__ = (
        Index("idx_oven_req_id", "req_id"),
        Index("idx_oven_status", "status"),
        Index("idx_oven_alert_id", "alert_id"),
        Index("idx_oven_action_id", "action_id"),
        Index("idx_oven_task_id", "task_id"),
    )

    def __repr__(self) -> str:
        return f"<Oven req_id={self.req_id} status={self.status}>"


# ==============================================================================
# ALERTS TABLE - Stores and tracks alert auto-remediation
# ==============================================================================


class Alert(Base):
    """Stores and tracks alert auto-remediation status.

    Enhanced alert tracking that includes:
    - Full Alertmanager webhook payload
    - Processing status (internal PoundCake status)
    - Alert status from Alertmanager (firing/resolved)
    - Counter for alert occurrences
    - Optional ticket system integration
    """

    __tablename__ = "poundcake_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Request tracking
    req_id = Column(String(36), nullable=False, index=True)

    # Alertmanager fields - extracted from 'alerts' array
    fingerprint = Column(String(64), unique=True, nullable=False, index=True)

    # Alert status from Alertmanager (firing or resolved)
    alert_status = Column(String(20), nullable=False, index=True)  # firing, resolved

    # Fields extracted from labels and groupLabels
    alert_name = Column(String(200), nullable=False, index=True)  # labels.alertname
    group_name = Column(String(200), nullable=True, index=True)  # groupLabels.alertname for recipe matching
    severity = Column(String(50), nullable=True, index=True)  # labels.severity (optional)
    instance = Column(String(200), nullable=True, index=True)  # labels.instance (optional)
    prometheus = Column(String(200), nullable=True)  # labels.prometheus (optional)

    # Full labels and annotations as JSON
    labels = Column(JSON, nullable=True)
    annotations = Column(JSON, nullable=True)

    # Timing from Alertmanager
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    generator_url = Column(String(500), nullable=True)

    # Internal PoundCake processing status
    processing_status = Column(
        String(20), nullable=False, default="new", index=True
    )  # new, processing, complete, failed

    # Counter for alert occurrences
    counter = Column(Integer, nullable=False, default=1)

    # Ticket system integration
    ticket_number = Column(String(100), nullable=True, index=True)

    # Full raw payload from Alertmanager (the entire alert object)
    raw_data = Column(JSON, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ovens = relationship("Oven", back_populates="alert")

    __table_args__ = (
        Index("idx_alerts_req_id", "req_id"),
        Index("idx_alerts_processing_status", "processing_status"),
        Index("idx_alerts_alert_status", "alert_status"),
        Index("idx_alerts_alert_name", "alert_name"),
        Index("idx_alerts_group_name", "group_name"),
        Index("idx_alerts_severity", "severity"),
        Index("idx_alerts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Alert {self.alert_name} {self.fingerprint} {self.alert_status}>"


# ==============================================================================
# MODEL SUMMARY
# ==============================================================================

"""
SIMPLIFIED ARCHITECTURE v2.0:

┌─────────────────────────────────────────┐
│         MariaDB Database                │
├─────────────────────────────────────────┤
│                                         │
│ PoundCake Tables (3):                   │
│   poundcake_recipes                     │
│   poundcake_ovens                       │
│   poundcake_alerts                      │
│                                         │
│ StackStorm Tables (ST2 manages):       │
│   action_db                             │
│   execution_db                          │
│   liveaction_db                         │
│   rule_db                               │
│   trigger_db                            │
│   workflow_db                           │
└─────────────────────────────────────────┘

DATA FLOW:

1. Alertmanager → PoundCake Webhook (pre_heat middleware generates req_id)
   Create: poundcake_alerts (req_id: abc-123, status: new)

2. PoundCake → Determine Recipe
   Query: SELECT * FROM poundcake_recipes WHERE name MATCHES alert_name
   
3. PoundCake → Create Oven
   Create: poundcake_ovens
   {
     req_id: "abc-123",
     alert_id: 42,
     recipe_id: 5,
     status: "new"
   }

4. PoundCake → StackStorm API (synchronous execution)
   POST /v1/executions
   {
     "action": recipe.st2_workflow_ref,
     "parameters": {
       "alert_data": {...},
       "req_id": "abc-123"
     }
   }
   
   Response: { "id": "5f9e8a7b..." }

5. Update Oven
   Update: poundcake_ovens
   {
     action_id: "5f9e8a7b...",
     action_result: {...},
     status: "complete",
     ended_at: datetime.utcnow()
   }

6. Query Complete History
   SELECT 
       alert.req_id,
       alert.alert_name,
       recipe.name as recipe_name,
       oven.action_id as st2_execution_id,
       oven.status,
       oven.action_result
   FROM poundcake_alerts alert
   JOIN poundcake_ovens oven ON oven.alert_id = alert.id
   JOIN poundcake_recipes recipe ON recipe.id = oven.recipe_id
   WHERE alert.req_id = 'abc-123';

BENEFITS:

✅ NO Redis/Celery - Synchronous processing
✅ Cleaner Architecture - Recipe/Oven metaphor
✅ Better Tracking - req_id from pre_heat middleware
✅ Counter Support - Track alert occurrences
✅ Ticket Integration - Link to external ticket systems
✅ State Management - Track firing/clear states

REMOVED:

❌ Redis broker
❌ Celery workers
❌ Flower monitoring
❌ Async task complexity
❌ Task execution tracking table
❌ API call tracking table
❌ ST2 execution link table
"""
