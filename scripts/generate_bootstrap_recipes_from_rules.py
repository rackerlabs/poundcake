#!/usr/bin/env python3
"""Generate bootstrap recipe catalog entries from temp Prometheus rule files."""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIRS = [PROJECT_ROOT / "temp" / "node", PROJECT_ROOT / "temp" / "kubernetes"]
OUTPUT_DIR = PROJECT_ROOT / "config" / "bootstrap" / "recipes"


def collect_group_names() -> set[str]:
    names: set[str] = set()
    for input_dir in INPUT_DIRS:
        for path in sorted(input_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            rule_map = payload.get("additionalPrometheusRulesMap")
            if not isinstance(rule_map, dict):
                continue
            for value in rule_map.values():
                groups = (value or {}).get("groups", [])
                if not isinstance(groups, list):
                    continue
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    name = group.get("name")
                    if isinstance(name, str) and name:
                        names.add(name)
    return names


def render_recipe_payload(group_name: str) -> dict:
    return {
        "apiVersion": "poundcake/v1",
        "kind": "RecipeCatalogEntry",
        "recipe": {
            "name": group_name,
            "description": f"Bootstrap-generated recipe for alert group {group_name}",
            "enabled": True,
            "recipe_ingredients": [
                {
                    "execution_engine": "bakery",
                    "execution_target": "tickets.create",
                    "step_order": 1,
                    "run_phase": "resolving",
                    "on_success": "continue",
                    "parallel_group": 0,
                    "depth": 0,
                    "execution_parameters_override": None,
                }
            ],
        },
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUTPUT_DIR.glob("*.yaml"):
        existing.unlink()

    names = sorted(collect_group_names())
    for name in names:
        payload = render_recipe_payload(name)
        target = OUTPUT_DIR / f"{name}.yaml"
        target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    print(f"generated={len(names)} output_dir={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
