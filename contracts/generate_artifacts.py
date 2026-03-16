"""Generate contract artifacts from canonical models and FastAPI apps."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.communications import (
    CommunicationAcceptedResponse,
    CommunicationCloseRequest,
    CommunicationCreateRequest,
    CommunicationNotifyRequest,
    CommunicationOperationListResponse,
    CommunicationOperationResponse,
    CommunicationResponse,
    CommunicationUpdateRequest,
)
from contracts.poundcake import (
    AppSettingsResponse,
    DeleteExecutionResponse,
    LabelListResponse,
    LabelValuesResponse,
    MetricsListResponse,
    PrometheusHealthResponse,
    PrometheusMutationResponse,
    PrometheusRuleListResponse,
    WorkflowRegistrationRequest,
    WorkflowRegistrationResponse,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs" / "contracts"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_model_schemas() -> dict[str, object]:
    model_index = {
        "communication-create": CommunicationCreateRequest,
        "communication-update": CommunicationUpdateRequest,
        "communication-notify": CommunicationNotifyRequest,
        "communication-close": CommunicationCloseRequest,
        "communication-accepted": CommunicationAcceptedResponse,
        "communication-resource": CommunicationResponse,
        "communication-operation": CommunicationOperationResponse,
        "communication-operation-list": CommunicationOperationListResponse,
        "app-settings": AppSettingsResponse,
        "prometheus-rule-list": PrometheusRuleListResponse,
        "prometheus-health": PrometheusHealthResponse,
        "prometheus-mutation": PrometheusMutationResponse,
        "metrics-list": MetricsListResponse,
        "label-list": LabelListResponse,
        "label-values": LabelValuesResponse,
        "workflow-registration-request": WorkflowRegistrationRequest,
        "workflow-registration-response": WorkflowRegistrationResponse,
        "delete-execution": DeleteExecutionResponse,
    }
    return {
        name: model.model_json_schema(mode="validation")
        for name, model in sorted(model_index.items())
    }


def build_openapi() -> dict[str, object]:
    from api.main import app as poundcake_app
    from bakery.main import app as bakery_app

    return {
        "poundcake-openapi.json": poundcake_app.openapi(),
        "bakery-openapi.json": bakery_app.openapi(),
    }


def generate_model_schemas() -> None:
    _write_json(DOCS_DIR / "shared-models.json", build_model_schemas())


def generate_openapi() -> None:
    for filename, payload in build_openapi().items():
        _write_json(DOCS_DIR / filename, payload)


def main() -> None:
    generate_model_schemas()
    generate_openapi()


if __name__ == "__main__":
    main()
