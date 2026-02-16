"""Functional/config checks for chef/prep interval wiring."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_compose_prep_chef_uses_prep_interval_env() -> None:
    compose_path = REPO_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    prep_chef_env = compose["services"]["prep-chef"]["environment"]

    assert prep_chef_env["PREP_INTERVAL"] == "${PREP_INTERVAL:-5}"
    assert "PREP_INTERVAL" in prep_chef_env


def test_compose_chef_uses_chef_poll_interval_env() -> None:
    compose_path = REPO_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    chef_env = compose["services"]["chef"]["environment"]

    assert chef_env["CHEF_POLL_INTERVAL"] == "${CHEF_INTERVAL:-5}"


def test_helm_prep_chef_templates_use_prep_interval_env() -> None:
    prep_chef_template = (
        REPO_ROOT / "helm" / "poundcake" / "templates" / "prep-chef-deployment.yaml"
    ).read_text(encoding="utf-8")
    chef_template = (
        REPO_ROOT / "helm" / "poundcake" / "templates" / "chef-deployment.yaml"
    ).read_text(encoding="utf-8")

    assert "name: PREP_INTERVAL" in prep_chef_template
    assert "name: CHEF_POLL_INTERVAL" in chef_template
    assert "name: PREP_INTERVAL" in prep_chef_template
