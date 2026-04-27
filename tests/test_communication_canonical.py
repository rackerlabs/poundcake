from __future__ import annotations

from datetime import datetime, timezone

from api.models.models import Dish, DishIngredient, Ingredient, Order, RecipeIngredient
from api.services.communication_canonical import build_canonical_communication_context


def test_build_canonical_communication_context_includes_alert_links_and_route_config() -> None:
    now = datetime.now(timezone.utc)
    order = Order(
        id=7,
        req_id="REQ-7",
        fingerprint="fp-7",
        alert_status="firing",
        processing_status="processing",
        is_active=True,
        remediation_outcome="failed",
        clear_timeout_sec=300,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="filesystem-response",
        severity="warning",
        instance="host7",
        counter=2,
        labels={
            "alertname": "DiskFull",
            "group_name": "filesystem-response",
            "severity": "warning",
            "instance": "host7",
        },
        annotations={
            "summary": "Filesystem almost full",
            "description": "Usage exceeded the alert threshold.",
            "runbook_url": "https://docs.example.com/runbooks/filesystem",
            "dashboard_url": "https://grafana.example/d/fs",
        },
        raw_data={"generatorURL": "https://prometheus.example/graph?g0.expr=disk"},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )

    payload = {
        "title": "Alert requires attention",
        "description": "PoundCake escalated this alert.",
        "message": "Automated remediation failed.",
        "context": {
            "route_label": "Primary Core",
            "provider_config": {"account_number": "1234567", "queue": "Example Support"},
            "semantic_text": {
                "headline": "Alert requires attention",
                "summary": "PoundCake escalated this alert.",
                "detail": "Automated remediation failed.",
                "resolution": "",
            },
            "poundcake_policy": {
                "managed": True,
                "event": "escalation_open",
                "route_id": "core-primary",
                "label": "Primary Core",
            },
        },
    }

    canonical = build_canonical_communication_context(
        order=order,
        execution_target="rackspace_core",
        destination_target="primary-core",
        operation="open",
        execution_payload=payload,
    )

    assert canonical["route"]["provider_config"]["account_number"] == "1234567"
    assert canonical["alert"]["annotations"]["summary"] == "Filesystem almost full"
    assert canonical["text"]["detail"] == "Automated remediation failed."
    assert canonical["links"][0]["label"] == "Source"
    assert canonical["links"][1]["label"] == "Runbook"
    assert canonical["remediation"]["summary"]["total"] == 0


def test_build_canonical_communication_context_includes_correlation_summary() -> None:
    now = datetime.now(timezone.utc)
    order = Order(
        id=8,
        req_id="REQ-8",
        fingerprint="root-fp",
        alert_status="firing",
        processing_status="waiting_clear",
        is_active=True,
        remediation_outcome="none",
        clear_timeout_sec=None,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="kube-node-not-ready",
        severity="critical",
        instance="node-1",
        counter=3,
        labels={
            "alertname": "kube-node-not-ready-critical",
            "severity": "critical",
            "correlation_key": "node/node-1",
            "correlation_scope": "node",
            "affected_node": "node-1",
            "root_cause": "true",
        },
        annotations={"summary": "Node is not ready.", "description": "Node node-1 is not ready."},
        raw_data={
            "correlation": {
                "child_count": 2,
                "active_child_count": 1,
                "child_counts_by_group": {"kube-pod-not-ready": 2},
                "affected_namespaces": ["openstack"],
                "affected_workloads": ["openstack/nova-api-1"],
                "children": [
                    {
                        "fingerprint": "child-fp",
                        "alert_name": "kube-pod-not-ready-warning",
                        "group_name": "kube-pod-not-ready",
                        "status": "firing",
                    }
                ],
            }
        },
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )

    canonical = build_canonical_communication_context(
        order=order,
        execution_target="rackspace_core",
        destination_target="primary-core",
        operation="open",
        execution_payload={"context": {}},
    )

    assert canonical["correlation"]["root_cause"] is True
    assert canonical["correlation"]["child_count"] == 2
    assert "Correlated child alerts: 2 total, 1 active." in canonical["text"]["detail"]
    assert "Namespaces: openstack" in canonical["text"]["detail"]
    assert "Alert groups: kube-pod-not-ready=2" in canonical["text"]["detail"]


def test_build_canonical_communication_context_uses_node_label_when_instance_missing() -> None:
    now = datetime.now(timezone.utc)
    order = Order(
        id=11,
        req_id="REQ-11",
        fingerprint="fp-11",
        alert_status="firing",
        processing_status="new",
        is_active=True,
        remediation_outcome="none",
        clear_timeout_sec=None,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="node-memory-major-pages-faults",
        severity="warning",
        instance=None,
        counter=1,
        labels={
            "alertname": "NodeMemoryMajorPagesFaults",
            "group_name": "node-memory-major-pages-faults",
            "severity": "warning",
            "k8s_node_name": "472292-storage01",
            "host_name": "472292-storage01",
        },
        annotations={
            "summary": "Memory major page faults are occurring at a high rate.",
            "description": "Memory major pages are occurring at very high rate at , 500 major page faults per second.",
        },
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )

    canonical = build_canonical_communication_context(
        order=order,
        execution_target="rackspace_core",
        destination_target="primary-core",
        operation="open",
        execution_payload={"context": {}},
    )

    assert canonical["alert"]["instance"] == "472292-storage01"
    assert canonical["correlation"]["affected_node"] == "472292-storage01"
    assert canonical["correlation"]["affected_nodes"] == ["472292-storage01"]


def _make_recipe_ingredient(
    *,
    ingredient_id: int,
    step_order: int,
    execution_purpose: str,
    execution_engine: str,
    execution_target: str,
    task_key_template: str,
    now: datetime,
) -> RecipeIngredient:
    ingredient = Ingredient(
        id=ingredient_id,
        execution_target=execution_target,
        destination_target="",
        task_key_template=task_key_template,
        execution_engine=execution_engine,
        execution_purpose=execution_purpose,
        execution_id=None,
        execution_payload=None,
        execution_parameters=None,
        is_default=False,
        is_blocking=True,
        expected_duration_sec=60,
        timeout_duration_sec=300,
        retry_count=0,
        retry_delay=5,
        on_failure="stop",
        created_at=now,
        updated_at=now,
        deleted=False,
        deleted_at=None,
    )
    return RecipeIngredient(
        id=ingredient_id + 1000,
        recipe_id=99,
        ingredient_id=ingredient_id,
        step_order=step_order,
        on_success="continue",
        parallel_group=0,
        depth=0,
        execution_parameters_override=None,
        run_phase="firing",
        run_condition="always",
        recipe=None,
        ingredient=ingredient,
    )


def test_build_canonical_communication_context_includes_remediation_steps_and_excerpts() -> None:
    now = datetime.now(timezone.utc)
    order = Order(
        id=8,
        req_id="REQ-8",
        fingerprint="fp-8",
        alert_status="resolved",
        processing_status="complete",
        is_active=False,
        remediation_outcome="succeeded",
        clear_timeout_sec=300,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=True,
        alert_group_name="filesystem-response",
        severity="critical",
        instance="host8",
        counter=1,
        labels={
            "alertname": "DiskFull",
            "group_name": "filesystem-response",
            "severity": "critical",
            "instance": "host8",
        },
        annotations={
            "summary": "Filesystem almost full",
            "description": "Usage exceeded the alert threshold.",
        },
        raw_data={"generatorURL": "https://prometheus.example/graph?g0.expr=disk"},
        starts_at=now,
        ends_at=now,
        created_at=now,
        updated_at=now,
    )

    remediation_first = _make_recipe_ingredient(
        ingredient_id=200,
        step_order=1,
        execution_purpose="remediation",
        execution_engine="stackstorm",
        execution_target="linux.cleanup",
        task_key_template="cleanup_var",
        now=now,
    )
    remediation_second = _make_recipe_ingredient(
        ingredient_id=201,
        step_order=2,
        execution_purpose="remediation",
        execution_engine="stackstorm",
        execution_target="linux.verify",
        task_key_template="verify_var",
        now=now,
    )
    comms_step = _make_recipe_ingredient(
        ingredient_id=202,
        step_order=3,
        execution_purpose="comms",
        execution_engine="bakery",
        execution_target="discord",
        task_key_template="notify_discord",
        now=now,
    )

    dish = Dish(
        id=10,
        req_id="REQ-8",
        execution_ref="wf-10",
        order_id=order.id,
        recipe_id=99,
        run_phase="firing",
        processing_status="complete",
        execution_status="succeeded",
        started_at=now,
        completed_at=now,
        expected_duration_sec=120,
        actual_duration_sec=90,
        result=None,
        error_message=None,
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )
    dish.dish_ingredients = [
        DishIngredient(
            id=100,
            dish_id=dish.id,
            recipe_ingredient_id=remediation_first.id,
            task_key="step_1_cleanup_var",
            execution_engine="stackstorm",
            execution_target="linux.cleanup",
            destination_target="",
            execution_ref="task-1",
            execution_payload=None,
            execution_parameters=None,
            attempt=0,
            execution_status="succeeded",
            started_at=now,
            completed_at=now,
            canceled_at=None,
            result={"stdout": "Before cleanup: /var is 95% full"},
            error_message=None,
            deleted=False,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            recipe_ingredient=remediation_first,
        ),
        DishIngredient(
            id=101,
            dish_id=dish.id,
            recipe_ingredient_id=remediation_second.id,
            task_key="step_2_verify_var",
            execution_engine="stackstorm",
            execution_target="linux.verify",
            destination_target="",
            execution_ref="task-2",
            execution_payload=None,
            execution_parameters=None,
            attempt=0,
            execution_status="succeeded",
            started_at=now,
            completed_at=now,
            canceled_at=None,
            result={"stdout": "After cleanup: /var is 40% full"},
            error_message=None,
            deleted=False,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            recipe_ingredient=remediation_second,
        ),
        DishIngredient(
            id=102,
            dish_id=dish.id,
            recipe_ingredient_id=comms_step.id,
            task_key="step_3_notify_discord",
            execution_engine="bakery",
            execution_target="discord",
            destination_target="alerts",
            execution_ref="task-3",
            execution_payload=None,
            execution_parameters=None,
            attempt=0,
            execution_status="succeeded",
            started_at=now,
            completed_at=now,
            canceled_at=None,
            result={"message": "sent"},
            error_message=None,
            deleted=False,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            recipe_ingredient=comms_step,
        ),
    ]
    order.dishes = [dish]

    canonical = build_canonical_communication_context(
        order=order,
        execution_target="rackspace_core",
        destination_target="primary-core",
        operation="close",
        execution_payload={"context": {}},
    )

    assert canonical["remediation"]["summary"] == {
        "total": 2,
        "succeeded": 2,
        "failed": 0,
        "skipped": 0,
        "incomplete": 0,
    }
    assert len(canonical["remediation"]["steps"]) == 2
    assert canonical["remediation"]["before_excerpt"].startswith("stdout:\nBefore cleanup")
    assert canonical["remediation"]["after_excerpt"].startswith("stdout:\nAfter cleanup")
    assert canonical["remediation"]["latest_completed_step"]["task_key"] == "step_2_verify_var"


def test_build_canonical_communication_context_includes_failure_excerpt() -> None:
    now = datetime.now(timezone.utc)
    order = Order(
        id=9,
        req_id="REQ-9",
        fingerprint="fp-9",
        alert_status="firing",
        processing_status="failed",
        is_active=True,
        remediation_outcome="failed",
        clear_timeout_sec=300,
        clear_deadline_at=None,
        clear_timed_out_at=None,
        auto_close_eligible=False,
        alert_group_name="filesystem-response",
        severity="critical",
        instance="host9",
        counter=1,
        labels={
            "alertname": "DiskFull",
            "group_name": "filesystem-response",
            "severity": "critical",
            "instance": "host9",
        },
        annotations={
            "summary": "Filesystem almost full",
            "description": "Usage exceeded the alert threshold.",
        },
        raw_data={},
        starts_at=now,
        ends_at=None,
        created_at=now,
        updated_at=now,
    )

    remediation_first = _make_recipe_ingredient(
        ingredient_id=210,
        step_order=1,
        execution_purpose="remediation",
        execution_engine="stackstorm",
        execution_target="linux.cleanup",
        task_key_template="cleanup_var",
        now=now,
    )
    remediation_second = _make_recipe_ingredient(
        ingredient_id=211,
        step_order=2,
        execution_purpose="remediation",
        execution_engine="stackstorm",
        execution_target="linux.verify",
        task_key_template="verify_var",
        now=now,
    )

    dish = Dish(
        id=11,
        req_id="REQ-9",
        execution_ref="wf-11",
        order_id=order.id,
        recipe_id=99,
        run_phase="firing",
        processing_status="failed",
        execution_status="failed",
        started_at=now,
        completed_at=now,
        expected_duration_sec=120,
        actual_duration_sec=90,
        result=None,
        error_message="workflow failed",
        retry_attempt=0,
        created_at=now,
        updated_at=now,
    )
    dish.dish_ingredients = [
        DishIngredient(
            id=110,
            dish_id=dish.id,
            recipe_ingredient_id=remediation_first.id,
            task_key="step_1_cleanup_var",
            execution_engine="stackstorm",
            execution_target="linux.cleanup",
            destination_target="",
            execution_ref="task-10",
            execution_payload=None,
            execution_parameters=None,
            attempt=0,
            execution_status="succeeded",
            started_at=now,
            completed_at=now,
            canceled_at=None,
            result={"stdout": "Cleanup started"},
            error_message=None,
            deleted=False,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            recipe_ingredient=remediation_first,
        ),
        DishIngredient(
            id=111,
            dish_id=dish.id,
            recipe_ingredient_id=remediation_second.id,
            task_key="step_2_verify_var",
            execution_engine="stackstorm",
            execution_target="linux.verify",
            destination_target="",
            execution_ref="task-11",
            execution_payload=None,
            execution_parameters=None,
            attempt=0,
            execution_status="failed",
            started_at=now,
            completed_at=now,
            canceled_at=None,
            result={"stderr": "Permission denied while cleaning /var"},
            error_message="Cleanup command failed",
            deleted=False,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            recipe_ingredient=remediation_second,
        ),
    ]
    order.dishes = [dish]

    canonical = build_canonical_communication_context(
        order=order,
        execution_target="rackspace_core",
        destination_target="primary-core",
        operation="open",
        execution_payload={"context": {}},
    )

    assert canonical["remediation"]["summary"] == {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "skipped": 0,
        "incomplete": 0,
    }
    assert canonical["remediation"]["after_excerpt"] == ""
    assert "Cleanup command failed" in canonical["remediation"]["failure_excerpt"]
    assert "Permission denied" in canonical["remediation"]["failure_excerpt"]
