"""Turn an intake from the web form (web/intake.html) into pipeline input.

    python tools/import_intake.py path/to/intake_<customer>.json [--project samples/01-isv-inventory]

The JSON is what the form's "Download full intake (JSON)" button saves, or a document read from
the form's saved-intakes store. This script:

  1. writes  <project>/data/intake_<customer>.csv   (one row per product line, schema field names)
  2. appends the customer, with its cloud commitments, to <project>/reference/customers.yaml
     unless a customer with that name is already there (it never edits existing entries)
  3. prints what it did; run `python -m playbook <project>` afterwards to produce the deliverables
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import yaml

COLUMNS = ["customer", "product", "edition", "vendor", "department", "licenses", "active_users", "unit_cost_monthly",
           "annual_cost", "renewal_date", "term_months", "auto_renew", "notice_days", "purchased_via", "business_owner",
           "use_case", "criticality", "satisfaction", "open_to_alternatives", "considering", "switch_reason",
           "desired_outcome", "notes"]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "intake").lower()).strip("-")[:40] or "intake"


def annual(line: dict) -> float | None:
    if line.get("annualCost") not in (None, ""):
        return float(line["annualCost"])
    if line.get("unitMonthly") and line.get("licenses"):
        return float(line["unitMonthly"]) * 12 * float(line["licenses"])
    return None


def blank(v):
    return "" if v is None else v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("intake", type=Path)
    ap.add_argument("--project", type=Path, default=Path("samples/01-isv-inventory"))
    a = ap.parse_args(argv)
    return write_intake(json.loads(a.intake.read_text(encoding="utf-8")), a.project)


def write_intake(intake: dict, project: Path) -> int:
    """Write one intake (the web form's JSON shape) into a pipeline project. Returns an exit code."""
    class A:  # keep the body below unchanged
        pass
    a = A()
    a.project = project
    cust = intake.get("customer") or {}
    name = (cust.get("name") or "").strip()
    if not name:
        print("The intake has no customer name; fill it in on the form first.", file=sys.stderr)
        return 1
    lines = intake.get("lines") or []
    if not lines:
        print("The intake has no product lines.", file=sys.stderr)
        return 1

    out = a.project / "data" / f"intake_{slug(name)}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for l in lines:
            w.writerow([name, l.get("product"), blank(l.get("edition")), blank(l.get("vendor")), blank(l.get("department")),
                        blank(l.get("licenses")), blank(l.get("activeUsers")), blank(l.get("unitMonthly")), blank(annual(l)),
                        blank(l.get("renewalDate")), blank(l.get("termMonths")), blank(l.get("autoRenew")),
                        blank(l.get("noticeDays")), blank(l.get("purchasedVia")), blank(l.get("owner")),
                        blank(l.get("useCase")), blank(l.get("criticality")), blank(l.get("satisfaction")),
                        blank(l.get("openToAlternatives")), blank(l.get("evaluating")), blank(l.get("switchReason")),
                        blank(l.get("desiredOutcome")), blank(l.get("notes"))])
    print(f"wrote {out} ({len(lines)} lines)")

    ref = a.project / "reference" / "customers.yaml"
    existing = yaml.safe_load(ref.read_text(encoding="utf-8")) or {}
    names = {e["customer"].lower() for e in existing.get("entries", [])}
    if name.lower() in names:
        print(f"{name} is already in {ref}; left it unchanged")
    else:
        entry = {"customer": name}
        aliases = [x.strip().lower() for x in (cust.get("aliases") or "").split(",") if x.strip()]
        if aliases:
            entry["aliases"] = aliases
        for src, dst in (("industry", "industry"), ("employees", "employees")):
            if cust.get(src) not in (None, ""):
                entry[dst] = cust[src]
        if cust.get("sponsorName"):
            entry["exec_contact"] = cust["sponsorName"] + (f" ({cust['sponsorTitle']})" if cust.get("sponsorTitle") else "")
        lead = (intake.get("opportunity") or {}).get("accountLead")
        if lead:
            entry["account_lead"] = lead
        for key, prefix in (("aws", "aws"), ("azure", "azure")):
            c = (intake.get("commitments") or {}).get(key) or {}
            if c.get("has") == "Yes":
                if c.get("annual") not in (None, ""):
                    entry[f"{prefix}_commit_annual"] = c["annual"]
                entry[f"{prefix}_commit_remaining"] = c.get("remaining")
                entry[f"{prefix}_commit_end"] = c.get("end")
        block = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True)
        text = ref.read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join("  " + ln for ln in block.rstrip("\n").splitlines()) + "\n"
        ref.write_text(text, encoding="utf-8")
        yaml.safe_load(ref.read_text(encoding="utf-8"))  # fail loudly if the append broke the file
        print(f"added {name} to {ref}")
    print(f"next: python -m playbook {a.project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
