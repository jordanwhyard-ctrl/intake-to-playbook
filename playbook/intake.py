"""Stage 1 — Intake: load records from mixed sources, map fields, normalize types, dedupe.

Supported source formats:
  csv   — header row; columns renamed through the source's `map`
  json  — a list of objects (or {"records": [...]}); keys renamed through `map`
  text  — free-text submissions (emails, web-form notifications) separated by a
          line of `---`; lines that look like `Key: value` become fields, and the
          remaining text is kept in `notes`
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "proton.me"}


# ---------------------------------------------------------------- loaders
def _load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _load_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("records", [data])
    return list(data)


_KV = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/#-]{0,40}?)\s*[:=]\s*(.+?)\s*$")


def _load_text(path: Path) -> list[dict]:
    records = []
    for block in re.split(r"^\s*-{3,}\s*$", path.read_text(encoding="utf-8"), flags=re.M):
        if not block.strip():
            continue
        rec: dict[str, Any] = {}
        notes = []
        for line in block.splitlines():
            m = _KV.match(line)
            if m:
                key = re.sub(r"[^a-z0-9]+", "_", m.group(1).lower()).strip("_")
                rec[key] = m.group(2)
            elif line.strip():
                notes.append(line.strip())
        if notes:
            rec["notes"] = " ".join(notes)
        records.append(rec)
    return records


LOADERS = {"csv": _load_csv, "json": _load_json, "text": _load_text}


# ---------------------------------------------------------------- type coercion
def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in {"", "n/a", "na", "none", "null", "-", "?"})


def to_number(v: Any) -> float | None:
    """'$1.2M' -> 1200000, '45k' -> 45000, '1,250' -> 1250, '200-500' -> 350."""
    if _blank(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace(",", "").replace("$", "").replace("usd", "").strip()
    rng = re.match(r"^(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*([kmb]?)\+?$", s)
    if rng:
        mult = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[rng.group(3)]
        return (float(rng.group(1)) + float(rng.group(2))) / 2 * mult
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(k|m|mm|b|bn|thousand|million|billion)?\+?$", s)
    if not m:
        return None
    mult = {None: 1, "k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6,
            "b": 1e9, "bn": 1e9, "billion": 1e9}[m.group(2)]
    return float(m.group(1)) * mult


def to_bool(v: Any) -> bool | None:
    if _blank(v):
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"y", "yes", "true", "1", "x", "checked", "on"}


def to_date(v: Any) -> str | None:
    if _blank(v):
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %b %Y", "%b %d %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def to_list(v: Any) -> list[str]:
    if _blank(v):
        return []
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    return [p.strip().lower() for p in re.split(r"[;,|/]", str(v)) if p.strip()]


def to_email(v: Any) -> str | None:
    if _blank(v):
        return None
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(v))
    return m.group(0).lower() if m else None


def to_str(v: Any) -> str | None:
    return None if _blank(v) else re.sub(r"\s+", " ", str(v)).strip()


COERCE = {"str": to_str, "number": to_number, "money": to_number, "bool": to_bool,
          "date": to_date, "list": to_list, "email": to_email,
          "lower": lambda v: (to_str(v) or "").lower() or None}


# ---------------------------------------------------------------- normalization
_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|plc)\.?$", re.I)


def company_key(name: str | None) -> str | None:
    if not name:
        return None
    s = _SUFFIX.sub("", name.strip()).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]", "", s) or None


def normalize(raw: dict, schema: dict[str, str], aliases: dict[str, str]) -> tuple[dict, list[str]]:
    """Rename via aliases, coerce via schema. Returns (record, data-quality issues)."""
    renamed: dict[str, Any] = {}
    for k, v in raw.items():
        key = aliases.get(k, aliases.get(k.lower().strip(), k))
        if key in renamed and not _blank(renamed[key]):
            continue  # first non-blank value wins
        renamed[key] = v
    rec: dict[str, Any] = {}
    issues: list[str] = []
    for field, ftype in schema.items():
        raw_v = renamed.get(field)
        val = COERCE[ftype](raw_v)
        if val is None and not _blank(raw_v):
            issues.append(f"could not read {field}={raw_v!r} as {ftype}")
        rec[field] = val
    # keep unmapped extras for transparency
    rec["_extra"] = {k: v for k, v in renamed.items() if k not in schema and not _blank(v)}
    if rec.get("contact_name"):
        rec["first_name"] = rec["contact_name"].split()[0]
    if rec.get("email"):
        domain = rec["email"].split("@", 1)[1]
        rec.setdefault("domain", None)
        rec["domain"] = rec.get("domain") or domain
        rec["free_email"] = domain in FREE_MAIL
    return rec, issues


def _merge(a: dict, b: dict) -> dict:
    """Fill gaps in a from b; union lists; keep max of numbers that both have."""
    out = dict(a)
    for k, v in b.items():
        cur = out.get(k)
        if cur in (None, [], "") and v not in (None, [], ""):
            out[k] = v
        elif isinstance(cur, list) and isinstance(v, list):
            out[k] = sorted(set(cur) | set(v))
        elif isinstance(cur, (int, float)) and isinstance(v, (int, float)) and not isinstance(cur, bool):
            out[k] = max(cur, v)
    if b.get("contact_name") and a.get("contact_name") and b["contact_name"] != a["contact_name"]:
        who = b["contact_name"] + (f" ({b['title']})" if b.get("title") else "")
        others = list(a.get("other_contacts") or [])
        if who not in others:
            out["other_contacts"] = others + [who]
    out["_sources"] = sorted(set(a.get("_sources", [])) | set(b.get("_sources", [])))
    out["_merged"] = a.get("_merged", 1) + b.get("_merged", 1)
    out["_issues"] = a.get("_issues", []) + b.get("_issues", [])
    return out


def _norm_text(s: Any) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip() + " "


class Lookup:
    """Reference table (e.g. a software catalog) matched on a messy field via names + aliases.

    YAML: {entries: [{<key>: "Salesforce Sales Cloud", aliases: [sfdc, salesforce], ...fields}]}
    Exact alias match wins; otherwise the longest alias found inside the value as whole words.
    """

    def __init__(self, project_dir: Path, spec: dict):
        self.spec = spec
        data = yaml.safe_load((project_dir / spec["path"]).read_text(encoding="utf-8"))
        self.entries = data["entries"]
        self.key = spec.get("entry_key", "name")
        self.names: list[tuple[str, dict]] = []
        for e in self.entries:
            for n in [e[self.key], *e.get("aliases", [])]:
                self.names.append((_norm_text(n), e))
        self.names.sort(key=lambda t: -len(t[0]))

    def match(self, value: Any) -> dict | None:
        v = _norm_text(value)
        if not v.strip():
            return None
        for n, e in self.names:
            if n == v:
                return e
        for n, e in self.names:
            if n in v:
                return e
        return None

    def apply(self, rec: dict) -> None:
        field = self.spec["field"]
        if rec.get(field) in (None, ""):
            return
        e = self.match(rec[field])
        if not e:
            rec["_issues"].append(f"'{rec[field]}' not found in {self.spec['path']} — add it or an alias")
            return
        if self.spec.get("canonicalize", True):
            if rec[field] != e[self.key]:
                rec.setdefault("captured_as", rec[field])
            rec[field] = e[self.key]
        for k, v in e.items():
            if k in (self.key, "aliases"):
                continue
            if rec.get(k) in (None, [], "") or self.spec.get("overwrite"):
                rec[k] = v


def _part(v: Any) -> str:
    return company_key(v) if isinstance(v, str) else str(v).lower()


def run_intake(project_dir: Path, cfg: dict) -> tuple[list[dict], dict]:
    schema: dict[str, str] = cfg["schema"]
    key_fields: list[str] = cfg.get("dedupe_on", ["domain", "company"])
    records: list[dict] = []
    stats = {"sources": {}, "raw": 0, "issues": 0}

    value_maps = {f: {str(k).lower(): v for k, v in m.items()} for f, m in (cfg.get("value_maps") or {}).items()}

    def remap(rec: dict) -> None:
        for f, m in value_maps.items():
            v = rec.get(f)
            if isinstance(v, list):
                rec[f] = sorted({m.get(x, x) for x in v} - {""})
            elif isinstance(v, str):
                rec[f] = m.get(v.lower(), v)

    lookups = [Lookup(project_dir, spec) for spec in cfg.get("lookups", [])]

    for src in cfg["sources"]:
        path = project_dir / src["path"]
        rows = LOADERS[src["format"]](path)
        aliases = {k.lower().strip(): v for k, v in (src.get("map") or {}).items()}
        stats["sources"][src["path"]] = len(rows)
        for row in rows:
            rec, issues = normalize(row, schema, aliases)
            for k, v in (src.get("defaults") or {}).items():
                if rec.get(k) in (None, []):
                    rec[k] = COERCE[schema.get(k, "str")](v) if k in schema else v
            remap(rec)
            rec["_sources"] = [src.get("label", src["path"])]
            rec["_issues"] = issues
            for lk in lookups:
                lk.apply(rec)
            records.append(rec)
    stats["raw"] = len(records)

    merged: dict[str, dict] = {}
    order: list[str] = []
    for i, rec in enumerate(records):
        key = None
        for f in key_fields:
            if isinstance(f, list):  # composite key, e.g. [customer, product]
                parts = [rec.get(x) for x in f]
                if all(p not in (None, "") for p in parts):
                    key = "+".join(f) + ":" + "|".join(_part(p) for p in parts)
                    break
                continue
            val = rec.get(f)
            if f == "domain" and rec.get("free_email"):
                continue  # gmail.com is not a company
            if f == "company":
                val = company_key(val)
            if val:
                key = f"{f}:{str(val).lower()}"
                break
        key = key or f"row:{i}"
        # also link records sharing a company name to an existing domain key
        if "company" in key_fields:
            ck = company_key(rec.get("company"))
            alias = next((k for k, r in merged.items() if ck and company_key(r.get("company")) == ck), None)
            key = alias or key
        if key in merged:
            merged[key] = _merge(merged[key], rec)
        else:
            merged[key] = rec
            order.append(key)

    out = []
    for n, k in enumerate(order, 1):
        rec = merged[k]
        rec["id"] = f"{cfg.get('id_prefix', 'R')}-{n:03d}"
        for req in cfg.get("required", []):
            if rec.get(req) in (None, []):
                rec["_issues"].append(f"missing required field '{req}'")
        stats["issues"] += len(rec["_issues"])
        out.append(rec)
    stats["deduped"] = len(out)
    stats["as_of"] = cfg.get("as_of") or date.today().isoformat()
    return out, stats
