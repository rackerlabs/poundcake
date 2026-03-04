from __future__ import annotations

from pathlib import Path

import scripts.generate_bootstrap_recipes_from_rules as gen


def _write_rule(path: Path, group_names: list[str]) -> None:
    groups = "\n".join([f"      - name: {name}\n        rules: []" for name in group_names])
    path.write_text(
        f"""
additionalPrometheusRulesMap:
  test:
    groups:
{groups}
""".strip() + "\n",
        encoding="utf-8",
    )


def test_collect_group_names_dedupes_across_dirs(tmp_path, monkeypatch) -> None:
    node_dir = tmp_path / "node"
    kube_dir = tmp_path / "kubernetes"
    node_dir.mkdir()
    kube_dir.mkdir()

    _write_rule(node_dir / "a.yaml", ["group-a", "group-b"])
    _write_rule(kube_dir / "b.yaml", ["group-b", "group-c"])

    monkeypatch.setattr(gen, "INPUT_DIRS", [node_dir, kube_dir])
    names = gen.collect_group_names()
    assert names == {"group-a", "group-b", "group-c"}


def test_main_generates_one_recipe_per_group_and_overwrites(tmp_path, monkeypatch) -> None:
    node_dir = tmp_path / "node"
    kube_dir = tmp_path / "kubernetes"
    out_dir = tmp_path / "recipes"
    node_dir.mkdir()
    kube_dir.mkdir()
    out_dir.mkdir()

    _write_rule(node_dir / "a.yaml", ["group-a"])
    _write_rule(kube_dir / "b.yaml", ["group-b"])
    (out_dir / "old.yaml").write_text("stale: true\n", encoding="utf-8")

    monkeypatch.setattr(gen, "INPUT_DIRS", [node_dir, kube_dir])
    monkeypatch.setattr(gen, "OUTPUT_DIR", out_dir)

    gen.main()

    files = sorted(p.name for p in out_dir.glob("*.yaml"))
    assert files == ["group-a.yaml", "group-b.yaml"]
    group_a = (out_dir / "group-a.yaml").read_text(encoding="utf-8")
    assert "kind: RecipeCatalogEntry" in group_a
    assert "execution_target: tickets.create" in group_a
    assert "run_phase: resolving" in group_a
