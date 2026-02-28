from pathlib import Path


def test_helm_alembic_migration_matches_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "alembic/versions/2026_02_03_1600_initial_schema.py"
    helm_copy = repo_root / "helm/files/poundcake-alembic/2026_02_03_1600_initial_schema.py"

    assert source.read_text(encoding="utf-8") == helm_copy.read_text(encoding="utf-8")
