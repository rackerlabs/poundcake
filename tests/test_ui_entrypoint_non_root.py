from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_TEMPLATE = REPO_ROOT / "ui" / "nginx" / "nginx.conf"
UI_DOCKERFILE = REPO_ROOT / "ui" / "Dockerfile"
UI_ENTRYPOINT = REPO_ROOT / "ui" / "docker-entrypoint.sh"


def test_ui_template_listens_on_8080_only() -> None:
    content = UI_TEMPLATE.read_text(encoding="utf-8")
    assert "listen 8080;" in content
    assert re.search(r"^\s*listen\s+80\s*;", content, flags=re.MULTILINE) is None


def test_ui_dockerfile_uses_repo_managed_entrypoint() -> None:
    content = UI_DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/app/ui/docker-entrypoint.sh"]' in content
    assert 'CMD ["nginx", "-g", "daemon off;"]' in content
    assert "COPY ui/docker-entrypoint.sh /app/ui/docker-entrypoint.sh" in content
    assert "COPY ui/static /usr/share/nginx/html/legacy" in content
    assert "COPY ui/static/login.html /usr/share/nginx/html/login.html" not in content


def test_ui_entrypoint_enforces_non_root_safe_startup() -> None:
    content = UI_ENTRYPOINT.read_text(encoding="utf-8")
    assert "set -eu" in content
    assert "envsubst '${API_URL}'" in content
    assert "addr < 1024" in content
    assert "nginx -t" in content


def test_ui_nginx_routes_login_through_spa_shell() -> None:
    content = UI_TEMPLATE.read_text(encoding="utf-8")
    assert "location = /login" not in content
