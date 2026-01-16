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
    
    __table_args__ = (
        Index("idx_api_calls_created_at", "created_at"),
    )
    
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
    status = Column(String(20), nullable=False)
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


class TaskResult(Base):
    """Track Celery task execution results linked to request_id.
    
    This provides complete traceability from webhook to task execution.
    Stores task state, results, and links to request_id for audit trail.
    """
    
    __tablename__ = "poundcake_task_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Celery task tracking
    task_id = Column(String(155), unique=True, nullable=False, index=True)  # Celery task UUID
    task_name = Column(String(155), nullable=False, index=True)  # Task function name
    
    # Link to PoundCake request
    request_id = Column(String(36), nullable=False, index=True)  # Our request tracking
    alert_id = Column(Integer, ForeignKey("poundcake_alerts.id"), nullable=True)  # Which alert
    
    # Task execution state
    status = Column(String(50), nullable=False, index=True)  # PENDING, STARTED, SUCCESS, FAILURE, RETRY
    result = Column(JSON, nullable=True)  # Task result data
    traceback = Column(Text, nullable=True)  # Error traceback if failed
    
    # Task parameters (for retry/debugging)
    args = Column(JSON, nullable=True)  # Positional arguments
    kwargs = Column(JSON, nullable=True)  # Keyword arguments
    
    # Timing
    date_created = Column(DateTime, default=datetime.utcnow, nullable=False)
    date_started = Column(DateTime, nullable=True)
    date_done = Column(DateTime, nullable=True)
    
    # Worker info
    worker = Column(String(100), nullable=True)  # Which worker executed this
    
    __table_args__ = (
        Index("idx_task_results_request_id", "request_id"),
        Index("idx_task_results_status", "status"),
        Index("idx_task_results_task_name", "task_name"),
        Index("idx_task_results_alert_id", "alert_id"),
        Index("idx_task_results_created", "date_created"),
    )
    
    def __repr__(self) -> str:
        return f"<TaskResult task_id={self.task_id} status={self.status} request_id={self.request_id}>"


# ==============================================================================
# THAT'S IT! Just 4 tables.
# ==============================================================================

"""
SIMPLIFIED ARCHITECTURE:

┌─────────────────────────────────────────┐
│         MariaDB Database                │
├─────────────────────────────────────────┤
│                                         │
│ PoundCake Tables (4):                   │
│   poundcake_api_calls                   │
│   poundcake_alerts                      │
│   poundcake_st2_execution_link          │
│   poundcake_task_results (NEW)          │
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
