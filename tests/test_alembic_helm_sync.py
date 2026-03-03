from pathlib import Path


def test_helm_alembic_migration_matches_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_versions = repo_root / "alembic/versions"
    helm_versions = repo_root / "helm/files/poundcake-alembic/versions"

    source_files = sorted(path.name for path in source_versions.glob("*.py"))
    helm_files = sorted(path.name for path in helm_versions.glob("*.py"))
    assert source_files == helm_files

    for filename in source_files:
        source = source_versions / filename
        helm_copy = helm_versions / filename
        assert source.read_text(encoding="utf-8") == helm_copy.read_text(encoding="utf-8")
