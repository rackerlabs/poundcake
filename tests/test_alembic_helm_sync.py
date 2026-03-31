from pathlib import Path


def _migration_filenames(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.py") if path.name != "__init__.py")


def test_helm_alembic_migration_matches_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_versions = repo_root / "alembic/versions"

    source_files = _migration_filenames(source_versions)
    assert source_files == ["2026_02_03_1600_initial_schema.py"]

    helm_versions = repo_root / "helm/files/poundcake-alembic/versions"
    assert _migration_filenames(helm_versions) == []


def test_poundcake_repo_no_longer_contains_in_repo_bakery_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    assert not (repo_root / "bakery").exists()


def test_helm_chart_version_reset_to_0_1_0() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    chart = (repo_root / "helm/Chart.yaml").read_text(encoding="utf-8")

    assert "version: 0.1.0" in chart
    assert 'appVersion: "0.1.0"' in chart
