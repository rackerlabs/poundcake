"""Simplified SQLAlchemy models - PoundCake as thin wrapper over StackStorm.

This is a MUCH simpler architecture:
- PoundCake handles webhook ingestion and request_id tracking
- StackStorm handles ALL workflow and action execution
- One simple link table connects them

NO MORE:
- actions table (use ST2's action_db)
- custom_action_buckets table (use ST2 workflows)
- custom_action_bucket_steps table (use ST2 workflow definitions)
- Complex extension tables

MUCH SIMPLER!
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship
from api.core.database import Base

# ==============================================================================
# POUNDCAKE TABLES - Minimal webhook tracking
# ==============================================================================


class APICall(Base):
    """API request tracking with request_id.

    This is our entry point - tracks all incoming webhooks with unique request_id.
    """

    __tablename__ = "poundcake_api_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(36), unique=True, nullable=False, index=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    headers = Column(JSON, nullable=True)
    query_params = Column(JSON, nullable=True)
    body = Column(JSON, nullable=True)
    client_host = Column(String(100), nullable=True)
    status_code = Column(Integer, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    alerts = relationship("Alert", back_populates="api_call", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_api_calls_created_at", "created_at"),)

    def __repr__(self) -> str:
        return f"<APICall {self.request_id}>"


class Alert(Base):
    """Alertmanager alert data.

    Stores the alert, then triggers StackStorm with request_id in context.
    """

    __tablename__ = "poundcake_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_call_id = Column(Integer, ForeignKey("poundcake_api_calls.id"), nullable=False)
    fingerprint = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False)  # firing, resolved
    alert_name = Column(String(200), nullable=False, index=True)
    severity = Column(String(50), nullable=True, index=True)
    instance = Column(String(200), nullable=True, index=True)

    # Alert data
    labels = Column(JSON, nullable=True)
    annotations = Column(JSON, nullable=True)
    raw_data = Column(JSON, nullable=True)

    # Timing
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    generator_url = Column(String(500), nullable=True)

    # Processing status (for UI compatibility)
    processing_status = Column(
        String(50), nullable=False, default="pending", index=True
    )  # pending, processing, completed, failed
    task_id = Column(String(255), nullable=True)  # Celery task ID
    error_message = Column(Text, nullable=True)

    # Which ST2 rule will handle this
    st2_rule_matched = Column(String(200), nullable=True, index=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    api_call = relationship("APICall", back_populates="alerts")
    executions = relationship("ST2ExecutionLink", back_populates="alert")

    __table_args__ = (
        Index("idx_alerts_created_at", "created_at"),
        Index("idx_alerts_rule_matched", "st2_rule_matched"),
        Index("idx_alerts_processing_status", "processing_status"),
    )

    def __repr__(self) -> str:
        return f"<Alert {self.alert_name} {self.fingerprint}>"


# ==============================================================================
# LINK TABLE - The only connection needed to StackStorm
# ==============================================================================


class ST2ExecutionLink(Base):
    """Simple link between PoundCake request_id and StackStorm execution_id.

    This is ALL we need to track StackStorm executions!

    When we trigger ST2, we:
    1. Pass request_id in the execution parameters
    2. Get back st2_execution_id
    3. Store the link here

    Then we can query:
    - Complete audit trail by request_id
    - All ST2 execution details from execution_db
    - Join our alerts with ST2 executions
    """

    __tablename__ = "poundcake_st2_execution_link"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # PoundCake side
    request_id = Column(String(36), nullable=False, index=True)  # Our request tracking
    alert_id = Column(Integer, ForeignKey("poundcake_alerts.id"), nullable=True)  # Which alert

    # StackStorm side
    st2_execution_id = Column(String(100), nullable=False, index=True)  # ST2's execution_db.id
    st2_rule_ref = Column(String(200), nullable=True)  # Which ST2 rule triggered
    st2_action_ref = Column(String(200), nullable=True)  # Which ST2 action ran

    # When we created this link
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    alert = relationship("Alert", back_populates="executions")

    __table_args__ = (
        Index("idx_st2_link_request_id", "request_id"),
        Index("idx_st2_link_st2_exec_id", "st2_execution_id"),
        Index("idx_st2_link_alert_id", "alert_id"),
    )

    def __repr__(self) -> str:
        return f"<ST2ExecutionLink request={self.request_id} st2_exec={self.st2_execution_id}>"


# ==============================================================================
# TASK EXECUTION TRACKING
# ==============================================================================


class TaskExecution(Base):
    """Track Celery task executions for monitoring and debugging.

    Links Celery task IDs to alerts for task status queries.
    """

    __tablename__ = "poundcake_task_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    task_name = Column(String(255), nullable=False)
    alert_fingerprint = Column(String(64), nullable=True, index=True)
    status = Column(
        String(50), nullable=False, default="pending"
    )  # pending, started, success, failure
    args = Column(JSON, nullable=True)
    kwargs = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_task_exec_created_at", "created_at"),
        Index("idx_task_exec_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<TaskExecution {self.task_id} {self.status}>"


# ==============================================================================
# MAPPINGS - Alert to action mappings (database-backed)
# ==============================================================================


class Mapping(Base):
    """Alert-to-action mappings stored in database.

    Replaces YAML file-based mappings with database storage for easier management.
    The config field stores the full mapping configuration as JSON.
    """

    __tablename__ = "poundcake_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_name = Column(String(255), unique=True, nullable=False, index=True)
    handler = Column(String(100), nullable=False, default="yaml_config")
    config = Column(JSON, nullable=False)  # Full mapping config: actions, conditions, etc.
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_mapping_enabled", "enabled"),
        Index("idx_mapping_handler", "handler"),
    )

    def __repr__(self) -> str:
        return f"<Mapping {self.alert_name}>"


# ==============================================================================
# MODEL SUMMARY - 5 tables total
# ==============================================================================

"""
SIMPLIFIED ARCHITECTURE:

┌─────────────────────────────────────────┐
│         MariaDB Database                │
├─────────────────────────────────────────┤
│                                         │
│ PoundCake Tables (3):                   │
│   poundcake_api_calls                   │
│   poundcake_alerts                      │
│   poundcake_st2_execution_link          │
│                                         │
│ StackStorm Tables (ST2 manages):       │
│   action_db                             │
│   execution_db                          │
│   liveaction_db                         │
│   rule_db                               │
│   trigger_db                            │
│   workflow_db (ActionChains)            │
└─────────────────────────────────────────┘

DATA FLOW:

1. Alertmanager → PoundCake Webhook
   Create: poundcake_api_calls (request_id: abc-123)
   Create: poundcake_alerts

2. PoundCake → StackStorm API
   POST /v1/executions
   {
     "action": "remediation.host_down_workflow",
     "parameters": {
       "alert_data": {...},
       "poundcake_request_id": "abc-123"  ← Pass request_id
     }
   }
   
   Response: { "id": "5f9e8a7b..." }  ← ST2 execution_id

3. Store Link
   Create: poundcake_st2_execution_link
   {
     request_id: "abc-123",
     st2_execution_id: "5f9e8a7b...",
     alert_id: 42
   }

4. Query Complete History
   SELECT 
       pc.request_id,
       alert.alert_name,
       link.st2_execution_id,
       st2.action,
       st2.status,
       st2.result
   FROM poundcake_api_calls pc
   JOIN poundcake_alerts alert ON alert.api_call_id = pc.id
   JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
   JOIN execution_db st2 ON st2.id = link.st2_execution_id
   WHERE pc.request_id = 'abc-123';

BENEFITS:

✅ MUCH SIMPLER - Just 3 PoundCake tables
✅ No Duplication - Use ST2's workflow engine
✅ No Maintenance - ST2 manages workflows, we just link
✅ Complete Audit Trail - request_id tracks everything
✅ ST2 UI Works - All workflow management in ST2
✅ Flexibility - Use ST2's full power (ActionChains, Mistral workflows, Orquesta)

WHAT WE REMOVED:

❌ actions table → Use ST2's action_db
❌ custom_action_buckets → Use ST2 workflows
❌ custom_action_bucket_steps → Use ST2 workflow definitions
❌ Complex extension tables → Just one simple link table

PoundCake's Role:

1. Receive Alertmanager webhooks
2. Generate unique request_id
3. Store alert data
4. Trigger StackStorm (pass request_id)
5. Track link (request_id ↔ st2_execution_id)
6. Provide query API for audit trail

StackStorm's Role:

1. Define all workflows (ActionChains, Mistral, Orquesta)
2. Define all actions (python, shell, http, etc.)
3. Execute remediation
4. Store execution results
5. Provide UI for workflow management

QUERIES:

-- Get all ST2 executions for a request
SELECT * FROM execution_db e
JOIN poundcake_st2_execution_link link ON e.id = link.st2_execution_id
WHERE link.request_id = 'abc-123';

-- Get all alerts and their ST2 executions
SELECT 
    a.alert_name,
    a.severity,
    ac.request_id,
    link.st2_execution_id
FROM poundcake_alerts a
JOIN poundcake_api_calls ac ON a.api_call_id = ac.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = a.id;

-- Get ST2 workflow success rate
SELECT 
    st2.action,
    COUNT(*) as total,
    SUM(CASE WHEN st2.status = 'succeeded' THEN 1 ELSE 0 END) as succeeded
FROM execution_db st2
JOIN poundcake_st2_execution_link link ON st2.id = link.st2_execution_id
GROUP BY st2.action;
"""
