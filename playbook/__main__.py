"""Run a project:  python -m playbook samples/01-saas-inbound [--out out/] [--as-of 2026-10-14]

A project folder holds:
  project.yaml   name, sources, schema (field types), dedupe keys, brief/CRM fields
  rules.yaml     scores, computed fields, staged rules
  plays.yaml     the sales-play library
  packages.yaml  (optional) packaged offers, add-ons, discounts
  data/          the raw intake files
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from .intake import run_intake
from .packager import package_outputs
from .rules import run_rules, validate_rules


def load_project(project_dir: Path) -> dict:
    def y(name: str, required: bool = True) -> dict:
        p = project_dir / name
        if not p.exists():
            if required:
                raise SystemExit(f"missing {p}")
            return {}
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = {"project": y("project.yaml"), "rules": y("rules.yaml"),
           "plays": y("plays.yaml").get("plays", {}), "packages": y("packages.yaml", required=False)}
    return cfg


def run(project_dir: Path, out_root: Path, as_of: date | None = None, quiet: bool = False) -> dict:
    cfg = load_project(project_dir)
    problems = validate_rules(cfg["rules"], cfg["plays"], cfg["packages"])
    if problems:
        raise SystemExit("rule problems:\n  " + "\n  ".join(problems))
    as_of = as_of or (date.fromisoformat(str(cfg["project"]["as_of"])) if cfg["project"].get("as_of") else date.today())
    cfg["project"]["as_of"] = as_of.isoformat()

    records, stats = run_intake(project_dir, cfg["project"])
    run_rules(records, cfg["rules"], as_of)
    out_dir = out_root / project_dir.name
    zip_path = package_outputs(out_dir, cfg, records, cfg["plays"], stats, as_of)

    if not quiet:
        plays = Counter(cfg["plays"][r["_plays"][0]]["name"] if r["_plays"] else "(none)" for r in records)
        print(f"\n{cfg['project']['name']}")
        print(f"  intake   {stats['raw']} records from {len(stats['sources'])} sources -> {stats['deduped']} {cfg['project'].get('record_noun', 'account')}s, "
              f"{stats['issues']} data issues")
        print("  plays    " + ", ".join(f"{k}: {v}" for k, v in plays.most_common()))
        print(f"  output   {out_dir}/index.html")
        print(f"  bundle   {zip_path}")
    return {"records": records, "stats": stats, "out_dir": out_dir, "zip": zip_path}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="playbook", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects", nargs="+", type=Path, help="one or more project folders")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--as-of", type=date.fromisoformat, help="run date (defaults to project.yaml as_of, else today)")
    a = ap.parse_args(argv)
    for p in a.projects:
        if not (p / "project.yaml").exists():
            sys.exit(f"{p} is not a project folder (no project.yaml)")
        run(p, a.out, a.as_of)


if __name__ == "__main__":
    main()
