"""Guardrails for UI static module wiring."""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_JS_ROOT = REPO_ROOT / "ui" / "static" / "assets" / "js"


def _imports_from(module_path: Path) -> list[str]:
    text = module_path.read_text(encoding="utf-8")
    return re.findall(r'import\s+[^"\n]+\s+from\s+"([^"]+)";', text)


def _resolve(module_path: Path, relative_import: str) -> Path:
    return (module_path.parent / relative_import).resolve()


def test_ui_modules_resolve_all_relative_imports() -> None:
    main_js = UI_JS_ROOT / "main.js"
    login_js = UI_JS_ROOT / "login.js"

    for module in (main_js, login_js):
        assert module.exists(), f"Expected module missing: {module}"
        for relative_import in _imports_from(module):
            if not relative_import.startswith("."):
                continue
            resolved = _resolve(module, relative_import)
            assert resolved.exists(), f"Missing imported module: {resolved}"


def test_ui_lib_modules_are_not_excluded_from_git_or_docker_context() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "!ui/static/assets/js/lib/" in gitignore
    assert "!ui/static/assets/js/lib/**" in gitignore
    assert "!ui/static/assets/js/lib/" in dockerignore
    assert "!ui/static/assets/js/lib/**" in dockerignore
