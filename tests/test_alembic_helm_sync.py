from pathlib import Path


def _migration_filenames(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.py") if path.name != "__init__.py")


def test_helm_alembic_migration_matches_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_versions = repo_root / "alembic/versions"

    source_files = _migration_filenames(source_versions)
    assert source_files == ["2026_02_03_1600_initial_schema.py"]

    helm_versions = repo_root / "helm/files/poundcake-alembic/versions"
    helm_files = _migration_filenames(helm_versions)
    assert helm_files == source_files

    for filename in source_files:
        source_text = (source_versions / filename).read_text(encoding="utf-8")
        helm_text = (helm_versions / filename).read_text(encoding="utf-8")
        assert helm_text == source_text


def test_poundcake_repo_no_longer_contains_in_repo_bakery_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bakery_dir = repo_root / "bakery"

    if not bakery_dir.exists():
        return

    # Bakery was moved to a standalone repo. Local __pycache__ residue is harmless,
    # but no in-repo Bakery source/runtime files should remain here.
    unexpected_files = [
        path
        for path in bakery_dir.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    assert unexpected_files == []


def test_helm_chart_versions_match_current_release_metadata() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    chart = (repo_root / "helm/Chart.yaml").read_text(encoding="utf-8")

    assert "version: 0.2.108" in chart
    assert 'appVersion: "2.0.209"' in chart
