"""Embed the current ISV catalog into the web intake form.

    python tools/build_intake_page.py      # web/intake_template.html -> web/intake.html

Run it after tools/build_catalog.py so the form's product picker matches the catalog.
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
cat = yaml.safe_load((ROOT / "samples/01-isv-inventory/reference/isv_catalog.yaml").read_text(encoding="utf-8"))["entries"]
mini = [{"n": e["product"], "al": e.get("aliases", []), "v": e["vendor"], "c": e["category"], "a": e["aws_marketplace"],
         "m": e["azure_marketplace"], "alt": e["alternatives"][:4], "pa": e["partner_alternatives"],
         "cb": e.get("covered_by"), "cs": e.get("covered_by_suites", [])} for e in cat]
blob = json.dumps(mini, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
tpl = (ROOT / "web/intake_template.html").read_text(encoding="utf-8")
(ROOT / "web/intake.html").write_text(tpl.replace("__CATALOG__", blob), encoding="utf-8")
print(f"web/intake.html written with {len(mini)} catalog products")
