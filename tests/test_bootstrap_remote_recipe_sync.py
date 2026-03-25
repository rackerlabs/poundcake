from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from api.services import bootstrap_remote_recipe_sync as sync


def _write_rule_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_refresh_bootstrap_recipe_catalog_from_remote_scans_nested_yaml(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    alerts_root = repo_root / "alerts"
    _write_rule_file(
        alerts_root / "team-a" / "cpu.yaml",
        {
            "spec": {
                "groups": [
                    {
                        "name": "team-a",
                        "rules": [
                            {"alert": "HighCPUUsage", "expr": "sum(rate(cpu[5m])) > 1"},
                        ],
                    }
                ]
            }
        },
    )
    _write_rule_file(
        alerts_root / "team-b" / "disk.yml",
        {
            "additionalPrometheusRulesMap": {
                "disk": {
                    "groups": [
                        {
                            "name": "team-b",
                            "rules": [
                                {"alert": "DiskFullSoon", "expr": "disk_free < 10"},
                            ],
                        }
                    ]
                }
            }
        },
    )
    (alerts_root / "team-b" / "ignore.txt").write_text("noop\n", encoding="utf-8")

    monkeypatch.setattr(sync, "_ensure_repo_checkout", lambda **_kwargs: repo_root)

    destination = tmp_path / "generated"
    stats = sync.refresh_bootstrap_recipe_catalog_from_remote(
        repo_url="https://github.com/rackerlabs/genestack-monitoring.git",
        branch="main",
        rules_path="alerts",
        destination_dir=str(destination),
    )

    assert stats["files_scanned"] == 2
    assert stats["rules_discovered"] == 2
    assert stats["generated"] == 2
    generated_files = sorted(path.name for path in destination.glob("*.yaml"))
    assert generated_files == ["diskfullsoon.yaml", "highcpuusage.yaml"]
    payload = yaml.safe_load((destination / "highcpuusage.yaml").read_text(encoding="utf-8"))
    assert payload["recipe"]["name"] == "HighCPUUsage"
    assert payload["recipe"]["recipe_ingredients"][0]["execution_target"] == "core"


def test_refresh_bootstrap_recipe_catalog_from_remote_rejects_conflicting_duplicate_alerts(
    monkeypatch, tmp_path
) -> None:
    repo_root = tmp_path / "repo"
    alerts_root = repo_root / "alerts"
    _write_rule_file(
        alerts_root / "a.yaml",
        {"groups": [{"rules": [{"alert": "SharedAlert", "expr": "up == 0"}]}]},
    )
    _write_rule_file(
        alerts_root / "nested" / "b.yaml",
        {"groups": [{"rules": [{"alert": "SharedAlert", "expr": "up == 1"}]}]},
    )
    monkeypatch.setattr(sync, "_ensure_repo_checkout", lambda **_kwargs: repo_root)

    with pytest.raises(sync.BootstrapRemoteRecipeSyncError):
        sync.refresh_bootstrap_recipe_catalog_from_remote(
            repo_url="https://github.com/rackerlabs/genestack-monitoring.git",
            branch="main",
            rules_path="alerts",
            destination_dir=str(tmp_path / "generated"),
        )


def test_repo_no_longer_tracks_source_controlled_bootstrap_recipes() -> None:
    recipes_dir = Path(__file__).resolve().parents[1] / "config" / "bootstrap" / "recipes"

    yaml_files = sorted(recipes_dir.glob("*.yaml")) if recipes_dir.exists() else []

    assert yaml_files == []
