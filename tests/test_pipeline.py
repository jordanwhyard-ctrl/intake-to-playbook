"""Run with:  python -m unittest discover tests"""
import csv
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from playbook.__main__ import load_project, run
from playbook.intake import company_key, to_bool, to_date, to_list, to_number
from playbook.rules import evaluate, run_rules, validate_rules

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = sorted(p for p in (ROOT / "samples").iterdir() if (p / "project.yaml").exists())


def rec(**kw):
    base = {"_scores": {"fit": 0}, "_tags": [], "_plays": [], "_issues": []}
    base.update(kw)
    return base


class TestCoercion(unittest.TestCase):
    def test_numbers(self):
        cases = {"$1.2M": 1_200_000, "45k": 45_000, "1,250": 1250, "200-500": 350, "5k": 5000,
                 "$90k": 90_000, "n/a": None, "TBD": None, 12: 12}
        for raw, want in cases.items():
            self.assertEqual(to_number(raw), want, raw)

    def test_bool_date_list(self):
        self.assertTrue(to_bool("Yes"))
        self.assertFalse(to_bool("no"))
        self.assertIsNone(to_bool(""))
        self.assertEqual(to_date("10/09/2026"), "2026-10-09")
        self.assertEqual(to_date("13 Oct 2026"), "2026-10-13")
        self.assertIsNone(to_date("ASAP"))
        self.assertEqual(to_list("SSO; Audit trail, api"), ["sso", "audit trail", "api"])

    def test_company_key_matches_variants(self):
        self.assertEqual(company_key("Cedar & Pine Outfitters"), company_key("Cedar and Pine Outfitters"))
        self.assertEqual(company_key("Horizon Learning Co."), company_key("Horizon Learning"))
        self.assertEqual(company_key("Kesselwerk GmbH"), company_key("kesselwerk"))


class TestRules(unittest.TestCase):
    def test_operators(self):
        r = rec(employees=1200.0, title="VP Operations", interest=["sso", "api"], country="us")
        self.assertTrue(evaluate({"field": "employees", "gte": 1000}, r))
        self.assertTrue(evaluate({"field": "title", "matches": r"\bvp\b"}, r))
        self.assertTrue(evaluate({"field": "interest", "contains": "SSO"}, r))
        self.assertTrue(evaluate({"all": [{"field": "country", "in": ["US", "CA"]},
                                          {"not": {"field": "employees", "lt": 10}}]}, r))
        self.assertFalse(evaluate({"field": "missing_field", "gt": 0}, r))
        self.assertTrue(evaluate({"field": "missing_field", "missing": True}, r))

    def test_first_match_else_and_trace(self):
        cfg = {"scores": ["fit"], "stages": [{
            "name": "Route", "first_match": True,
            "rules": [{"id": "big", "when": {"field": "n", "gte": 10}, "then": {"play": "a", "score": {"fit": 5}}},
                      {"id": "also-big", "when": {"field": "n", "gte": 5}, "then": {"play": "b"}}],
            "else": {"then": {"play": "c"}}}]}
        big, small = rec(n=20), rec(n=1)
        run_rules([big, small], cfg, date(2026, 1, 1))
        self.assertEqual(big["_plays"], ["a"])          # stopped at first match
        self.assertEqual(big["score_total"], 5)
        self.assertEqual(small["_plays"], ["c"])        # fell through to else
        self.assertEqual([t["rule"] for t in big["_trace"]], ["big"])

    def test_validation_catches_typos(self):
        cfg = {"scores": ["fit"], "stages": [{"name": "S", "rules": [
            {"id": "x", "when": {"field": "a", "greaterthan": 1}, "then": {"play": "nope", "score": {"fitt": 1}}}]}]}
        problems = " | ".join(validate_rules(cfg, plays={"real": {}}, packages={}))
        self.assertIn("unknown play 'nope'", problems)
        self.assertIn("undeclared score 'fitt'", problems)
        self.assertIn("unknown operator 'greaterthan'", problems)


class TestSamples(unittest.TestCase):
    """Every sample must validate and run end to end, and key outcomes must hold."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.results = {p.name: run(p, Path(cls.tmp.name), quiet=True) for p in SAMPLES}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def by_company(self, sample, name):
        return next(r for r in self.results[sample]["records"] if r.get("company") == name)

    def test_samples_validate(self):
        for p in SAMPLES:
            cfg = load_project(p)
            self.assertEqual(validate_rules(cfg["rules"], cfg["plays"], cfg["packages"]), [], p.name)

    def test_every_record_gets_a_play_and_deliverables_exist(self):
        for name, res in self.results.items():
            out = res["out_dir"]
            for r in res["records"]:
                self.assertTrue(r["_plays"], f"{name} {r['id']} has no play")
            rdir = load_project(ROOT / "samples" / name)["project"].get("records_dir", "accounts")
            self.assertEqual(len(list((out / rdir).glob("*.md"))), len(res["records"]))
            for f in ("index.html", "crm_import.csv", "results.json", "data_quality.md"):
                self.assertTrue((out / f).exists(), f)
            with zipfile.ZipFile(res["zip"]) as z:
                self.assertIn(f"{out.name}/index.html", z.namelist())
            with (out / "crm_import.csv").open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), len(res["records"]))
            json.loads((out / "results.json").read_text())

    def line(self, customer, product):
        return next(r for r in self.results["01-isv-inventory"]["records"]
                    if r.get("customer") == customer and r.get("product") == product)

    def test_isv_catalog_matching_and_merge(self):
        slack = self.line("Northbeam Logistics", "Slack Business+")
        self.assertEqual(slack["_merged"], 3)                  # workbook row, duplicate row, usage export
        self.assertEqual(slack["active_users"], 388)
        self.assertEqual(slack["captured_as"], "Slack")
        okta = self.line("Brightwater Credit Union", "Okta Workforce Identity")   # captured as "Okta SSO" / "Brightwater CU"
        self.assertEqual(okta["category"], "Identity")
        unknown = next(r for r in self.results["01-isv-inventory"]["records"] if r.get("product") == "MatterDesk Pro")
        self.assertTrue(any("not found" in i for i in unknown["_issues"]))

    def test_isv_dates_and_plays(self):
        zoom = self.line("Northbeam Logistics", "Zoom Workplace Business")
        self.assertEqual(zoom["notice_deadline"], "2026-10-31")
        self.assertEqual(zoom["_plays"][0], "consolidate")     # Teams already owned via Microsoft 365 E3
        self.assertEqual(zoom["consolidate_onto"], "Microsoft Teams")
        webex = self.line("Halcyon Health Group", "Webex Suite")
        self.assertIn("notice-missed", webex["_tags"])
        sfdc = self.line("Northbeam Logistics", "Salesforce Sales Cloud")
        self.assertEqual(sfdc["_plays"][0], "competitive-swap")
        asana = self.line("Northbeam Logistics", "Asana Business")
        self.assertEqual(asana["consolidate_onto"], ["Smartsheet Business"])
        zendesk = self.line("Halcyon Health Group", "Zendesk Suite")
        self.assertEqual(zendesk["_plays"][0], "license-optimization")
        self.assertEqual(self.line("Halcyon Health Group", "Workday HCM")["_plays"][0], "monitor")

    def test_isv_marketplace_routing(self):
        dd = self.line("Ridgeline Software Co.", "Datadog")              # captured as "Datadog Enterprise"
        self.assertEqual(dd["marketplace_route"], "AWS Marketplace")
        self.assertEqual(dd["marketplace_drawdown"], 420000)
        self.assertIn("commit-expiring", dd["_tags"])                     # AWS commitment ends 2027-01-31
        self.assertIn("marketplace-private-offer", dd["_plays"])
        snow = self.line("Ridgeline Software Co.", "Snowflake")          # already bought via AWS Marketplace
        self.assertIsNone(snow.get("marketplace_route"))
        st = self.line("Halcyon Health Group", "ServiceNow ITSM")       # Azure MACC customer
        self.assertEqual(st["marketplace_route"], "Microsoft Marketplace")
        self.assertIsNone(self.line("Brightwater Credit Union", "Sophos Intercept X").get("marketplace_route"))  # no commitment
        okta = self.line("Ridgeline Software Co.", "Okta Workforce Identity")
        self.assertEqual(okta["_plays"][0], "marketplace-private-offer")
        self.assertEqual(okta["marketplace_margin"], 0.10)                # partner margin, not the 3% default

    def test_isv_catalog_evidence(self):
        import yaml
        cat = yaml.safe_load((ROOT / "samples/01-isv-inventory/reference/isv_catalog.yaml").read_text())["entries"]
        self.assertGreaterEqual(len(cat), 150)
        for e in cat:
            for side in ("aws", "azure"):
                if e[f"{side}_marketplace"] == "listed":
                    self.assertTrue(e.get(f"{side}_listing", "").startswith("https://"), e["product"])

    def test_web_intake_import_runs_through_pipeline(self):
        import shutil, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            shutil.copytree(ROOT / "samples/01-isv-inventory", proj)
            r = subprocess.run([sys.executable, str(ROOT / "tools/import_intake.py"), str(ROOT / "tests/fixtures/intake_example.json"),
                                "--project", str(proj)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = run(proj, Path(tmp) / "out", quiet=True)
            mine = [x for x in res["records"] if x.get("customer") == "Example Analytics Ltd. (fictional)"]
            self.assertEqual(len(mine), 6)
            okta = next(x for x in mine if x["product"] == "Okta Workforce Identity")
            self.assertEqual(okta["marketplace_route"], "AWS Marketplace")   # commitment came from the intake
            notion = next(x for x in mine if x["product"] == "Notion")
            self.assertEqual(notion["annual_spend"], 81000)                   # 15/user/month x 450 x 12

    def test_discovery_workbook_import(self):
        import shutil, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            wbp = Path(tmp) / "wb.xlsx"
            subprocess.run([sys.executable, str(ROOT / "tools/build_discovery_workbook.py"), "--example", "--out", str(wbp)],
                           check=True, capture_output=True)
            proj = Path(tmp) / "proj"
            shutil.copytree(ROOT / "samples/01-isv-inventory", proj)
            r = subprocess.run([sys.executable, str(ROOT / "tools/import_workbook.py"), str(wbp), "--project", str(proj)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = run(proj, Path(tmp) / "out", quiet=True)
            mine = {x["product"]: x for x in res["records"] if x.get("customer") == "Example Software Co. (fictional)"}
            self.assertEqual(len(mine), 10)
            self.assertEqual(mine["Zoom Workplace Business"]["_plays"][0], "consolidate")    # typed "Zoom", wants to retire
            self.assertEqual(mine["Zoom Workplace Business"]["consolidate_onto"], "Google Meet")
            self.assertEqual(mine["GitLab Ultimate"]["_plays"][0], "license-optimization")
            self.assertEqual(mine["Snyk"]["_plays"][0], "competitive-swap")
            self.assertIn("committed", mine["Snowflake"]["_tags"])
            self.assertEqual(mine["Notion"]["annual_spend"], 72000)                           # $10 x 600 x 12

        # the blank template has only the example row, which the importer skips
        with tempfile.TemporaryDirectory() as tmp:
            wbp = Path(tmp) / "blank.xlsx"
            subprocess.run([sys.executable, str(ROOT / "tools/build_discovery_workbook.py"), "--out", str(wbp)], check=True, capture_output=True)
            sys.path.insert(0, str(ROOT / "tools"))
            from import_workbook import read_workbook
            self.assertEqual(read_workbook(wbp)["lines"], [])

    def test_isv_rollups_and_calendar(self):
        out = self.results["01-isv-inventory"]["out_dir"]
        self.assertEqual(len(list((out / "customers").glob("*.md"))), 5)
        cal = (out / "calendar.md").read_text()
        self.assertIn("## November 2026", cal)
        self.assertLess(cal.index("Nov 05"), cal.index("Nov 30"))

    def test_saas_dedupe_and_routing(self):
        s = "02-saas-inbound"
        harbor = self.by_company(s, "Harborline Freight Inc.")
        self.assertEqual(harbor["_merged"], 2)
        self.assertIn("Raj Patel (Director Process Excellence)", harbor["other_contacts"])
        self.assertEqual(harbor["_plays"][0], "enterprise-abm")
        self.assertEqual(self.by_company(s, "Varda Capital")["_plays"][0], "competitive-switch")
        quill = self.by_company(s, "Quill & Co")
        self.assertEqual(quill["_plays"][0], "self-serve")

    def test_msp_packaging(self):
        s = "03-msp-rfq-packaging"
        ridge = self.by_company(s, "Ridgeview Precision Machining")
        self.assertEqual(ridge["package"], "secure-plus")
        self.assertIn("cmmc-pack", ridge["_addons"])
        self.assertIn("cmmc", ridge["compliance"])           # merged across two portal rows
        dental = self.by_company(s, "Lakeshore Family Dental")
        self.assertEqual(dental["referral_partner"], "Summit Insurance Brokers (cyber insurance)")
        self.assertIn("partner-co-sell", dental["_plays"])
        self.assertTrue(any(f.startswith("Budget gap") for f in dental["_flags"]))
        self.assertIsNone(self.by_company(s, "Greenway Property Management").get("package"))

    def test_renewals(self):
        s = "04-renewals-expansion"
        brook = self.by_company(s, "Brookfield Health Partners")
        self.assertEqual(brook["risk_band"], "High")
        self.assertEqual(brook["_plays"][0], "churn-rescue")
        iron = self.by_company(s, "Ironwood Labs")
        self.assertEqual(iron["package"], "enterprise")       # Growth → Enterprise upgrade
        self.assertIn("plan-upgrade", iron["_tags"])
        cedar = self.by_company(s, "Cedar & Pine Outfitters")
        self.assertEqual(len(cedar["_sources"]), 4)          # '&' vs 'and' still merged


if __name__ == "__main__":
    unittest.main()
