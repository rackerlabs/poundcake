from pathlib import Path


def _migration_filenames(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.py") if path.name != "__init__.py")


def test_helm_alembic_migration_matches_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_versions = repo_root / "alembic/versions"
    helm_versions = repo_root / "helm/files/poundcake-alembic/versions"

    source_files = _migration_filenames(source_versions)
    helm_files = _migration_filenames(helm_versions)
    assert source_files == ["2026_02_03_1600_initial_schema.py"]
    assert source_files == helm_files

    for filename in source_files:
        source = source_versions / filename
        helm_copy = helm_versions / filename
        assert source.read_text(encoding="utf-8") == helm_copy.read_text(encoding="utf-8")


def test_bakery_uses_a_single_baseline_migration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bakery_versions = repo_root / "bakery/alembic/versions"

    assert _migration_filenames(bakery_versions) == ["001_initial_schema.py"]
