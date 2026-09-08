from __future__ import annotations

from api.services.workflow_repo_documents import (
    RepoActionReference,
    RepoWorkflowDocument,
    RepoWorkflowStep,
    dump_workflow_document,
    load_workflow_document,
    workflow_filename,
)
from types import SimpleNamespace

from api.services.workflow_repo_sync import (
    _document_to_create_payload,
    collect_workflow_export_files,
    is_system_workflow_recipe,
)


def test_workflow_document_round_trip() -> None:
    document = RepoWorkflowDocument(
        name="NodeFilesystemAlmostOutOfSpace",
        description="Expand or notify",
        enabled=True,
        recipe_ingredients=[
            RepoWorkflowStep(
                step_order=1,
                action=RepoActionReference(
                    service_type="k8s",
                    service_exec="pod_action",
                    task_key_template="k8s-pod-action",
                    destination_target="kubernetes",
                ),
                service_payload={"namespace": "openstack"},
            )
        ],
    )
    loaded = load_workflow_document(__import__("yaml").safe_load(dump_workflow_document(document)))
    assert loaded.name == document.name
    assert loaded.recipe_ingredients[0].action.task_key_template == "k8s-pod-action"
    assert workflow_filename(document.name) == "nodefilesystemalmostoutofspace.yaml"


def test_document_to_create_payload_resolves_active_templates() -> None:
    ingredient = SimpleNamespace(
        id=9,
        service_type="k8s",
        service_exec="pod_action",
        task_key_template="k8s-pod-action",
        destination_target="kubernetes",
        is_active=True,
    )
    document = RepoWorkflowDocument(
        name="demo",
        recipe_ingredients=[
            RepoWorkflowStep(
                step_order=1,
                action=RepoActionReference(
                    service_type="k8s",
                    service_exec="pod_action",
                    task_key_template="k8s-pod-action",
                ),
            )
        ],
    )
    payload = _document_to_create_payload(document, ingredients=[ingredient])
    assert payload.recipe_ingredients[0].ingredient_id == 9


def test_collect_workflow_export_files_skips_recipes_without_steps() -> None:
    ingredient = SimpleNamespace(
        service_type="k8s",
        service_exec="pod_action",
        task_key_template="k8s-pod-action",
        destination_target="kubernetes",
    )
    exportable = SimpleNamespace(
        name="NodeFilesystemAlmostOutOfSpace",
        description="Expand or notify",
        enabled=True,
        clear_timeout_sec=None,
        recipe_ingredients=[
            SimpleNamespace(
                step_order=1,
                on_success="continue",
                parallel_group=0,
                depth=0,
                run_phase="firing",
                run_condition="always",
                service_payload=None,
                service_exec_parameters_override=None,
                ingredient=ingredient,
            )
        ],
    )
    empty = SimpleNamespace(
        name="e2e-test-v2",
        description="leftover",
        enabled=True,
        clear_timeout_sec=None,
        recipe_ingredients=[],
    )
    files, skipped = collect_workflow_export_files([empty, exportable], directory="workflows")
    assert list(files) == ["workflows/nodefilesystemalmostoutofspace.yaml"]
    assert any("e2e-test-v2" in item for item in skipped)


def test_system_workflow_names_are_not_user_facing_exports() -> None:
    assert is_system_workflow_recipe(
        SimpleNamespace(name="operator-action:k8s:prometheus-rule-apply")
    )
    assert is_system_workflow_recipe(SimpleNamespace(name="plugin-health-check:github"))
    assert not is_system_workflow_recipe(SimpleNamespace(name="NodeFilesystemAlmostOutOfSpace"))
