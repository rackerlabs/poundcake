from __future__ import annotations

import re
import tomllib
from pathlib import Path


def _dependency_name(spec: str) -> str:
    return re.split(r"[<>=\[]", spec, 1)[0].strip().lower()


def test_api_runtime_requirements_cover_project_dependencies():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    project_dependencies = {_dependency_name(spec) for spec in pyproject["project"]["dependencies"]}

    requirements = {
        _dependency_name(line)
        for line in (repo_root / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    missing = sorted(project_dependencies - requirements)
    assert missing == []
