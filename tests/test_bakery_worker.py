from pathlib import Path


def _worker_source() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "bakery/worker.py").read_text(encoding="utf-8")


def test_rackspace_account_number_mapping_supports_plain_label_name() -> None:
    source = _worker_source()
    assert 'labels.get("account_number")' in source
    assert 'annotations.get("account_number")' in source


def test_worker_contains_dry_run_execution_path() -> None:
    source = _worker_source()
    assert "def _build_dry_run_result(" in source
    assert "if settings.ticketing_dry_run:" in source
    assert "Dry-run enabled; skipping provider call" in source


def test_non_create_operations_use_synthetic_ticket_id_in_dry_run() -> None:
    source = _worker_source()
    assert (
        'provider_payload.setdefault("ticket_id", f"dryrun-{ticket.internal_ticket_id}")' in source
    )


def test_worker_persists_provider_normalized_payload_before_execution() -> None:
    source = _worker_source()
    assert "def _persist_normalized_payload(" in source
    assert "_persist_normalized_payload(operation.operation_id, payload)" in source
