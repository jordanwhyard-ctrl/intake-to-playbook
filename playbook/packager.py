"""Stage 3 — Packaging: turn scored records into deliverables people can use.

For each run it writes:
  accounts/<id>-<name>.md   one-page brief per account (snapshot, why, package + estimate,
                            play, dated next steps, personalized talk track, flags)
  plays/<play>.md           play pack: objective, sequence, talk track, objection
                            handling, and the ranked list of accounts assigned to it
  crm_import.csv            flat file ready to import into a CRM
  data_quality.md           every issue found at intake, by record
  results.json              full machine-readable output including rule traces
  index.html                self-contained dashboard linking everything above
  <project>-deliverables.zip  the whole bundle
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .rules import _fmt


def label(r: dict, cfg: dict) -> str:
    tf = cfg["project"].get("title_field", "company")
    return str(r.get(tf) or r.get("contact_name") or r.get("email") or r["id"])


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "record").lower()).strip("-")[:40]


def money(v: float | None, cur: str = "USD") -> str:
    if v is None:
        return "—"
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur, "")
    return f"{'−' if v < 0 else ''}{sym}{abs(v):,.0f}"


def business_day(start: date, offset: int) -> date:
    d = start
    step = 1 if offset >= 0 else -1
    remaining = abs(offset)
    while remaining:
        d += timedelta(days=step)
        if d.weekday() < 5:
            remaining -= 1
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------- pricing
def estimate(rec: dict, pkg_cfg: dict) -> dict | None:
    key = rec.get("package")
    pkgs = pkg_cfg.get("packages", {})
    if not key or key not in pkgs:
        return None
    p = pkgs[key]
    term = pkg_cfg.get("term_months", 12)
    lines = []

    def units_for(spec: dict) -> float:
        u = rec.get(spec["field"]) or 0
        return max(float(u), spec.get("min", 0))

    base = float(p.get("base", 0))
    if base:
        lines.append({"item": f"{p['name']} — platform", "qty": 1, "unit": base, "monthly": base})
    if p.get("per_unit"):
        spec = p["per_unit"]
        q = units_for(spec)
        lines.append({"item": f"{p['name']} — {spec.get('label', spec['field'])}", "qty": q,
                      "unit": spec["price"], "monthly": q * spec["price"]})
    for a in rec.get("_addons", []):
        ad = pkg_cfg.get("addons", {}).get(a)
        if not ad:
            continue
        if ad.get("per_unit"):
            q = units_for(ad["per_unit"])
            lines.append({"item": ad["name"], "qty": q, "unit": ad["per_unit"]["price"],
                          "monthly": q * ad["per_unit"]["price"]})
        else:
            lines.append({"item": ad["name"], "qty": 1, "unit": ad["price"], "monthly": ad["price"]})
    one_time = [{"item": o["name"], "amount": o["amount"]} for o in p.get("one_time", [])]
    monthly = sum(l["monthly"] for l in lines)
    discount = 0.0
    for d in pkg_cfg.get("discounts", []):
        if monthly * term >= d.get("min_annual", 0) and (not d.get("tag") or d["tag"] in rec["_tags"]):
            discount = max(discount, d["pct"])
    annual = monthly * term * (1 - discount)
    return {"package": key, "name": p["name"], "description": p.get("description", ""),
            "includes": p.get("includes", []), "lines": lines, "monthly": monthly,
            "discount_pct": discount, "term_months": term, "contract_value": annual,
            "one_time": one_time, "one_time_total": sum(o["amount"] for o in one_time)}


# ---------------------------------------------------------------- writers
def _md_table(rows: list[list[Any]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
    return "\n".join(out)


def _display(v: Any, fmt: str | None = None, cur: str = "USD") -> str:
    if v is None or v == []:
        return "—"
    if fmt == "pct" and isinstance(v, (int, float)):
        return f"{v:.0%}"
    if fmt == "money" and isinstance(v, (int, float)):
        return money(v, cur)
    if fmt == "upper":
        return ", ".join(map(str, v)).upper() if isinstance(v, list) else str(v).upper()
    if fmt == "title":
        return ", ".join(x.title() for x in v) if isinstance(v, list) else str(v).title()
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:,.0f}" if v == int(v) or v >= 100 else f"{v:,.2f}"
    return str(v)


def account_brief(rec: dict, cfg: dict, plays: dict, est: dict | None, as_of: date) -> str:
    cur = cfg.get("packages", {}).get("currency", "USD")
    title_field = cfg["project"].get("title_field", "company")
    name = label(rec, cfg)
    out = [f"# {name}", ""]
    out.append(f"*{cfg['project']['name']} · {rec['id']} · prepared {as_of.isoformat()} · "
               f"sources: {', '.join(rec['_sources'])}*\n")

    primary = plays.get(rec["_plays"][0]) if rec["_plays"] else None
    headline = [f"**Priority:** {rec.get('total_band') or '—'} (score {rec['score_total']})"]
    if rec.get("segment"):
        headline.append(f"**Segment:** {rec['segment']}")
    if primary:
        headline.append(f"**Play:** {primary['name']}")
    if est:
        headline.append(f"**Package:** {est['name']} · {money(est['contract_value'], cur)} / {est['term_months']} mo")
        if est.get("baseline") is not None:
            headline.append(f"**vs current:** {money(est['baseline'], cur)} ({est['delta']:+,.0f})")
    out.append(" · ".join(headline) + "\n")

    out.append("## Snapshot\n")
    fmts = cfg["project"].get("field_formats", {})
    rows = [[lbl, _display(rec.get(field), fmts.get(field), cur)]
            for field, lbl in cfg["project"].get("brief_fields", {}).items()]
    out.append(_md_table(rows, ["", ""]) + "\n")

    out.append("## Scores\n")
    out.append(_md_table([[k.title(), v] for k, v in rec["_scores"].items()] + [["**Total**", f"**{rec['score_total']}**"]],
                         ["Score", "Points"]) + "\n")
    if rec["_tags"]:
        out.append("Tags: " + " ".join(f"`{t}`" for t in rec["_tags"]) + "\n")

    out.append("## Why this recommendation\n")
    for t in rec["_trace"]:
        eff = f" → {', '.join(t['effects'])}" if t["effects"] else ""
        out.append(f"- **{t['stage']}** · {t['reason']}{eff}")
    out.append("")

    if est:
        out.append(f"## Recommended package: {est['name']}\n")
        if est["description"]:
            out.append(est["description"] + "\n")
        if est["includes"]:
            out.append("Includes: " + "; ".join(est["includes"]) + "\n")
        rows = [[l["item"], _display(l["qty"]), money(l["unit"], cur), money(l["monthly"], cur)] for l in est["lines"]]
        rows.append(["**Monthly**", "", "", f"**{money(est['monthly'], cur)}**"])
        out.append(_md_table(rows, ["Line", "Qty", "Unit / mo", "Monthly"]) + "\n")
        terms = f"**{est['term_months']}-month value: {money(est['contract_value'], cur)}**"
        if est["discount_pct"]:
            terms += f" (includes {est['discount_pct']:.0%} volume discount)"
        out.append(terms)
        if est["one_time"]:
            out.append(" · One-time: " + ", ".join(f"{o['item']} {money(o['amount'], cur)}" for o in est["one_time"]))
        out.append("\n> Estimate generated from list pricing; confirm with deal desk before sending.\n")

    if primary:
        out.append(f"## Sales play: {primary['name']}\n")
        out.append(f"{primary['objective']}\n")
        if primary.get("owner") or primary.get("sla"):
            out.append(f"Owner: {primary.get('owner', '—')} · SLA: {primary.get('sla', '—')}\n")
        out.append("### Next steps\n")
        rows = [[business_day(as_of, s["day"]).strftime("%a %b %d"), s["channel"], _fmt(s["action"], rec)]
                for s in primary.get("sequence", [])]
        out.append(_md_table(rows, ["When", "Channel", "Action"]) + "\n")
        if primary.get("talk_track"):
            out.append("### Talk track\n")
            out.extend(f"> {_fmt(line, rec)}\n>" for line in primary["talk_track"])
            out[-1] = out[-1].rstrip(">").rstrip()
            out.append("")
        if primary.get("discovery_questions"):
            out.append("### Discovery questions\n")
            out.extend(f"{i}. {_fmt(q, rec)}" for i, q in enumerate(primary["discovery_questions"], 1))
            out.append("")
        if len(rec["_plays"]) > 1:
            others = ", ".join(plays[p]["name"] for p in rec["_plays"][1:] if p in plays)
            out.append(f"Also qualifies for: {others}\n")

    if rec["_flags"]:
        out.append("## Flags and to-dos\n")
        out.extend(f"- [ ] {f}" for f in rec["_flags"])
        out.append("")
    if rec.get("notes"):
        out.append("## Original notes\n")
        out.append(f"> {rec['notes']}\n")
    return "\n".join(out)


def play_pack(key: str, play: dict, members: list[dict], cfg: dict, briefs: dict, ests: dict) -> str:
    cur = cfg.get("packages", {}).get("currency", "USD")
    title_field = cfg["project"].get("title_field", "company")
    out = [f"# Play: {play['name']}", "", f"*{cfg['project']['name']} · {len(members)} account(s)*", ""]
    out.append(f"**Objective:** {play['objective']}\n")
    names = {"owner": "Owner", "sla": "SLA", "success_metric": "Success metric"}
    meta = [f"**{v}:** {play[k]}" for k, v in names.items() if play.get(k)]
    if meta:
        out.append(" · ".join(meta) + "\n")
    out.append("## Target accounts (highest priority first)\n")
    rows = []
    pipeline = 0.0
    for r in members:
        est = ests.get(r["id"])
        if est:
            pipeline += est["contract_value"]
        rows.append([f"[{label(r, cfg)}](../accounts/{briefs[r['id']]})", r["score_total"],
                     r.get("total_band") or "—", r.get("segment") or "—",
                     est["name"] if est else "—", money(est["contract_value"], cur) if est else "—",
                     len(r["_flags"])])
    out.append(_md_table(rows, ["Account", "Score", "Band", "Segment", "Package", "Value", "Flags"]))
    if pipeline:
        out.append(f"\n**Pipeline in this play: {money(pipeline, cur)}**\n")
    else:
        out.append("")
    out.append("## Sequence\n")
    out.append(_md_table([[f"Day {s['day']}", s["channel"], s["action"]] for s in play.get("sequence", [])],
                         ["When", "Channel", "Action"]) + "\n")
    if play.get("talk_track"):
        out.append("## Talk track (template)\n")
        out.extend(f"- {l}" for l in play["talk_track"])
        out.append("")
    if play.get("discovery_questions"):
        out.append("## Discovery questions\n")
        out.extend(f"{i}. {q}" for i, q in enumerate(play["discovery_questions"], 1))
        out.append("")
    if play.get("objections"):
        out.append("## Objection handling\n")
        for o in play["objections"]:
            out.append(f"**\"{o['objection']}\"**  \n{o['response']}\n")
    if play.get("assets"):
        out.append("## Assets to send\n")
        out.extend(f"- {a}" for a in play["assets"])
        out.append("")
    return "\n".join(out)


def _dashboard(cfg: dict, records: list[dict], plays: dict, ests: dict, briefs: dict, stats: dict) -> str:
    cur = cfg.get("packages", {}).get("currency", "USD")
    tf = cfg["project"].get("title_field", "company")
    e = html.escape
    play_counts = Counter(r["_plays"][0] if r["_plays"] else "unassigned" for r in records)
    band_counts = Counter(r.get("total_band") or "—" for r in records)
    pipeline = sum(x["contract_value"] for x in ests.values())
    col = cfg["project"].get("dashboard_column", {"field": "segment", "label": "Segment"})
    show_col = any(r.get(col["field"]) for r in records)
    rows = []
    for r in sorted(records, key=lambda r: -r["score_total"]):
        est = ests.get(r["id"])
        play = plays.get(r["_plays"][0], {}).get("name", "—") if r["_plays"] else "—"
        rows.append(
            f"<tr><td><a href='accounts/{briefs[r['id']]}'>{e(label(r, cfg))}</a></td>"
            f"<td data-v='{r['score_total']}'>{r['score_total']}</td><td>{e(r.get('total_band') or '—')}</td>"
            + (f"<td>{e(str(r.get(col['field']) or '—'))}</td>" if show_col else "") +
            f"<td>{e(play)}</td>"
            f"<td>{e(est['name'] if est else '—')}</td>"
            f"<td data-v='{est['contract_value'] if est else 0}'>{money(est['contract_value'], cur) if est else '—'}</td>"
            f"<td data-v='{len(r['_flags'])}'>{len(r['_flags']) or ''}</td></tr>")
    play_links = "".join(
        f"<li><a href='plays/{k}.md'>{e(plays[k]['name'])}</a> <span>{play_counts.get(k, 0)}</span></li>"
        for k in plays if play_counts.get(k))
    bands = "".join(f"<li>{e(k)} <span>{v}</span></li>" for k, v in sorted(band_counts.items()))
    tiles = [("Records in", stats["raw"]), ("Accounts after dedupe", stats["deduped"]),
             ("Data issues flagged", stats["issues"])]
    if pipeline:
        tiles.append(("Total packaged value", money(pipeline, cur)))
    deltas = [x["delta"] for x in ests.values() if "delta" in x]
    if deltas:
        tiles[-1] = ("Quoted renewal value", money(pipeline, cur))
        tiles.append(("Expansion quoted", money(sum(d for d in deltas if d > 0), cur)))
        tiles.append(("Contraction quoted", money(sum(d for d in deltas if d < 0), cur)))
    tile_html = "".join(f"<div class='tile'><b>{e(str(v))}</b><span>{e(k)}</span></div>" for k, v in tiles)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(cfg['project']['name'])}</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e4e1da;--acc:#2f5d50;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151614;--fg:#ecebe6;--mut:#a3a29c;--line:#2e2f2b;--acc:#7fb8a6;--card:#1d1e1b}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:32px 16px}} h1{{margin:0 0 4px;font-size:26px}}
p.sub{{color:var(--mut);margin:0 0 24px}} a{{color:var(--acc)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:24px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.tile b{{display:block;font-size:24px}} .tile span{{color:var(--mut);font-size:13px}}
.cols{{display:grid;grid-template-columns:1fr 3fr;gap:24px}} @media(max-width:760px){{.cols{{grid-template-columns:1fr}}}}
ul{{list-style:none;padding:0;margin:0}} li{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)}}
li span{{color:var(--mut)}} h2{{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{cursor:pointer;color:var(--mut);font-weight:600}} td[data-v]{{font-variant-numeric:tabular-nums}}
</style></head><body><main>
<h1>{e(cfg['project']['name'])}</h1>
<p class="sub">{e(cfg['project'].get('description', ''))} · as of {e(stats['as_of'])}</p>
<div class="tiles">{tile_html}</div>
<div class="cols"><section><h2>Plays</h2><ul>{play_links}</ul>
<h2>Priority bands</h2><ul>{bands}</ul>
<h2>Files</h2><ul><li><a href="crm_import.csv">crm_import.csv</a></li>
<li><a href="data_quality.md">data_quality.md</a></li><li><a href="results.json">results.json</a></li></ul></section>
<section><h2>Accounts</h2><div class="wrap"><table id="t"><thead><tr><th>Account</th><th>Score</th><th>Band</th>
{f"<th>{e(col['label'])}</th>" if show_col else ""}<th>Play</th><th>Package</th><th>Value</th><th>Flags</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section></div>
</main><script>
document.querySelectorAll('#t th').forEach((th,i)=>th.onclick=()=>{{const tb=document.querySelector('#t tbody');
const rs=[...tb.rows];const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
rs.sort((a,b)=>{{const x=a.cells[i],y=b.cells[i];const va=x.dataset.v??x.innerText,vb=y.dataset.v??y.innerText;
const n=parseFloat(va)-parseFloat(vb);return (isNaN(n)?va.localeCompare(vb):n)*(asc?1:-1)}});rs.forEach(r=>tb.appendChild(r))}});
</script></body></html>"""


def package_outputs(out_dir: Path, cfg: dict, records: list[dict], plays: dict, stats: dict, as_of: date) -> Path:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "accounts").mkdir(parents=True)
    (out_dir / "plays").mkdir()
    pkg_cfg = cfg.get("packages", {})
    cur = pkg_cfg.get("currency", "USD")
    tf = cfg["project"].get("title_field", "company")

    ests, briefs = {}, {}
    for r in records:
        est = estimate(r, pkg_cfg)
        if est:
            ests[r["id"]] = est
            base_f = cfg["project"].get("baseline_value_field")
            if base_f and r.get(base_f) is not None:
                est["baseline"] = r[base_f]
                est["delta"] = est["contract_value"] - r[base_f]
            bc = cfg["project"].get("budget_check")
            budget = r.get(bc["field"]) if bc else None
            if budget:
                gap = est["monthly"] - budget
                if gap > budget * bc.get("tolerance", 0):
                    r["_flags"].insert(0, f"Budget gap: estimate {money(est['monthly'], cur)}/mo vs stated "
                                          f"budget {money(budget, cur)}/mo — lead with phased scope or ROI")
                    r["_tags"].append("over-budget")
        fname = f"{r['id']}-{slug(label(r, cfg))}.md"
        briefs[r["id"]] = fname
        (out_dir / "accounts" / fname).write_text(account_brief(r, cfg, plays, est, as_of), encoding="utf-8")

    ranked = sorted(records, key=lambda r: -r["score_total"])
    for key, play in plays.items():
        members = [r for r in ranked if r["_plays"] and r["_plays"][0] == key]
        if members:
            (out_dir / "plays" / f"{key}.md").write_text(play_pack(key, play, members, cfg, briefs, ests), encoding="utf-8")

    crm_fields = cfg["project"].get("crm_fields", [tf])
    with (out_dir / "crm_import.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["record_id", *crm_fields, "score_total", "priority_band", "primary_play", "other_plays",
                    "package", "contract_value", "change_vs_current", "currency", "tags", "flags", "next_action", "next_action_date"])
        for r in ranked:
            est = ests.get(r["id"])
            play = plays.get(r["_plays"][0]) if r["_plays"] else None
            step = (play or {}).get("sequence", [{}])[0]
            w.writerow([r["id"], *[_display(r.get(c)) if r.get(c) not in (None, []) else "" for c in crm_fields],
                        r["score_total"], r.get("total_band") or "", play["name"] if play else "",
                        "; ".join(plays[p]["name"] for p in r["_plays"][1:] if p in plays),
                        est["name"] if est else "", round(est["contract_value"], 2) if est else "",
                        round(est["delta"], 2) if est and "delta" in est else "", cur if est else "",
                        "; ".join(r["_tags"]), "; ".join(r["_flags"]),
                        _fmt(step.get("action", ""), r) if step else "",
                        business_day(as_of, step["day"]).isoformat() if step.get("day") is not None else ""])

    dq = [f"# Data quality — {cfg['project']['name']}", "",
          f"{stats['raw']} raw records from {len(stats['sources'])} sources merged into {stats['deduped']} accounts.", "",
          _md_table([[k, v] for k, v in stats["sources"].items()], ["Source", "Records"]), "", "## Issues by account", ""]
    issues = [(r, r["_issues"]) for r in records if r["_issues"]]
    if not issues:
        dq.append("No issues found.")
    for r, iss in issues:
        dq.append(f"**{label(r, cfg)}** ({r['id']})")
        dq.extend(f"- {i}" for i in iss)
        dq.append("")
    merged = [r for r in records if r.get("_merged", 1) > 1]
    if merged:
        dq.append("## Duplicates merged\n")
        dq.extend(f"- {label(r, cfg)}: {r['_merged']} records ← {', '.join(r['_sources'])}" for r in merged)
    (out_dir / "data_quality.md").write_text("\n".join(dq) + "\n", encoding="utf-8")

    def clean(r: dict) -> dict:
        d = {k: v for k, v in r.items() if not k.startswith("_")}
        d.update(scores=r["_scores"], tags=r["_tags"], flags=r["_flags"], plays=r["_plays"],
                 addons=r["_addons"], trace=r["_trace"], sources=r["_sources"], estimate=ests.get(r["id"]))
        return d
    (out_dir / "results.json").write_text(json.dumps({"project": cfg["project"]["name"], "stats": stats,
                                                      "records": [clean(r) for r in ranked]}, indent=2, default=str),
                                          encoding="utf-8")
    (out_dir / "index.html").write_text(_dashboard(cfg, records, plays, ests, briefs, stats), encoding="utf-8")

    zip_path = out_dir.parent / f"{out_dir.name}-deliverables.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out_dir.rglob("*")):
            if p.is_file():
                z.write(p, Path(out_dir.name) / p.relative_to(out_dir))
    return zip_path
