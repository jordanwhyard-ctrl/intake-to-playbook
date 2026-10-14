"""Stage 2 — Rules: apply ordered, human-readable YAML rules to each record.

Every rule that fires is written to the record's `_trace`, so each deliverable
can say *why* an account got its score, segment, package and play.

Rule shape:
  - id: enterprise-size
    when: {all: [{field: employees, gte: 1000}, {field: country, in: [us, ca]}]}
    then:
      set:   {segment: Enterprise}      # write fields
      score: {fit: 25}                  # add to named scores
      tag:   [enterprise]               # add tags
      flag:  "Needs legal review"       # risk / to-do flags
      play:  enterprise-abm             # recommend a sales play
      package: professional             # recommend a packaged offer
      stop:  true                       # stop evaluating this stage
    reason: "{employees} employees in a core market"

Stages run in order. A stage with `first_match: true` stops at the first rule that fires
(useful for routing). `else` on a first_match stage applies when nothing fires.
"""
from __future__ import annotations

import re
import string
from datetime import date, timedelta
from math import prod as _prod
from typing import Any


# ---------------------------------------------------------------- field access
def get(rec: dict, path: str) -> Any:
    if path.startswith("score."):
        return rec["_scores"].get(path[6:], 0)
    if path == "score.total" or path == "total_score":
        return sum(rec["_scores"].values())
    if path == "tags":
        return rec["_tags"]
    if path == "plays":
        return rec["_plays"]
    cur: Any = rec
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _resolve(rec: dict, v: Any) -> Any:
    if isinstance(v, dict) and "ref" in v:
        return get(rec, v["ref"])
    return v


def _lower(v: Any) -> Any:
    return v.lower() if isinstance(v, str) else v


OPS = {
    "eq": lambda a, b: _lower(a) == _lower(b),
    "ne": lambda a, b: _lower(a) != _lower(b),
    "in": lambda a, b: _lower(a) in [_lower(x) for x in b],
    "not_in": lambda a, b: _lower(a) not in [_lower(x) for x in b],
    "gt": lambda a, b: _num(a) is not None and _num(a) > _num(b),
    "gte": lambda a, b: _num(a) is not None and _num(a) >= _num(b),
    "lt": lambda a, b: _num(a) is not None and _num(a) < _num(b),
    "lte": lambda a, b: _num(a) is not None and _num(a) <= _num(b),
    "between": lambda a, b: _num(a) is not None and _num(b[0]) <= _num(a) <= _num(b[1]),
    "exists": lambda a, b: (a not in (None, [], "")) == bool(b),
    "missing": lambda a, b: (a in (None, [], "")) == bool(b),
    "contains": lambda a, b: (_lower(b) in [_lower(x) for x in a]) if isinstance(a, list)
                              else (isinstance(a, str) and str(b).lower() in a.lower()),
    "contains_any": lambda a, b: any(OPS["contains"](a, x) for x in b),
    "contains_all": lambda a, b: all(OPS["contains"](a, x) for x in b),
    "matches": lambda a, b: isinstance(a, str) and re.search(b, a, re.I) is not None,
    "is_true": lambda a, b: (a is True) == bool(b),
}


def evaluate(cond: Any, rec: dict) -> bool:
    if cond is None or cond is True:
        return True
    if "all" in cond:
        return all(evaluate(c, rec) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, rec) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], rec)
    field = cond["field"]
    ops = [k for k in cond if k != "field"]
    if not ops:
        raise ValueError(f"condition on '{field}' has no operator")
    val = get(rec, field)
    for op in ops:
        if op not in OPS:
            raise ValueError(f"unknown operator '{op}' (known: {', '.join(OPS)})")
        if not OPS[op](val, _resolve(rec, cond[op])):
            return False
    return True


# ---------------------------------------------------------------- computed fields
def _days(d: str | None, as_of: date, sign: int) -> int | None:
    if not d:
        return None
    return sign * (date.fromisoformat(d) - as_of).days


def compute(rec: dict, spec: dict, as_of: date) -> None:
    for name, how in (spec or {}).items():
        (kind, arg), = how.items()
        if kind == "days_until":
            rec[name] = _days(rec.get(arg), as_of, 1)
        elif kind == "days_since":
            rec[name] = _days(rec.get(arg), as_of, -1)
        elif kind == "ratio":
            a, b = (_num(rec.get(x)) for x in arg)
            rec[name] = round(a / b, 3) if a is not None and b else None
        elif kind == "sum":
            vals = [_num(rec.get(x)) for x in arg]
            rec[name] = sum(v for v in vals if v is not None)
        elif kind == "count":
            rec[name] = len(rec.get(arg) or [])
        elif kind == "product":
            vals = [_num(rec.get(x)) if isinstance(x, str) else float(x) for x in arg]
            rec[name] = None if any(v is None for v in vals) else round(_prod(vals), 2)
        elif kind == "difference":
            a, b = (_num(rec.get(x)) for x in arg)
            rec[name] = a - b if a is not None and b is not None else None
        elif kind == "date_minus_days":
            d, n = rec.get(arg[0]), _num(rec.get(arg[1])) if isinstance(arg[1], str) else arg[1]
            rec[name] = (date.fromisoformat(d) - timedelta(days=int(n))).isoformat() if d and n is not None else None
        elif kind == "without":
            rec[name] = [x for x in (rec.get(arg[0]) or []) if x != rec.get(arg[1])]
        elif kind == "template":
            rec[name] = _fmt(arg, rec)
        elif kind == "min":
            vals = [v for v in (_num(rec.get(x)) for x in arg) if v is not None]
            rec[name] = min(vals) if vals else None
        elif kind == "max":
            vals = [v for v in (_num(rec.get(x)) for x in arg) if v is not None]
            rec[name] = max(vals) if vals else None
        elif kind == "coalesce":  # first non-empty field; non-string items are literal defaults
            rec[name] = next((x if not isinstance(x, str) else rec.get(x) for x in arg
                              if (x if not isinstance(x, str) else rec.get(x)) not in (None, [], "")), None)
        elif kind == "scale":
            v = _num(rec.get(arg["field"]))
            if v is None:
                rec[name] = arg.get("default")
            else:
                v *= arg.get("factor", 1)
                v = max(v, arg.get("min", v))
                v = min(v, arg.get("max", v))
                step = arg.get("round_to", 1)
                rec[name] = float(int(-(-v // step)) * step)  # round up to step
        else:
            raise ValueError(f"unknown computed field kind '{kind}'")


# ---------------------------------------------------------------- applying
class _SafeDict(dict):
    def __missing__(self, key):
        return f"[{key.replace('_', ' ')}]"  # visible gap the rep fills in


def _fmt(template: str, rec: dict) -> str:
    flat = _SafeDict({k: (", ".join(map(str, v)) if isinstance(v, list) else v)
                      for k, v in rec.items() if not k.startswith("_") and v not in (None, [], "")})
    flat.update({f"score_{k}": v for k, v in rec["_scores"].items()})
    for _, field, spec, _ in string.Formatter().parse(template):
        if field and isinstance(flat.get(field), float) and not spec:
            v = flat[field]
            flat[field] = f"{v:,.0f}" if v >= 100 or v == int(v) else f"{v:g}"
    try:
        return template.format_map(flat)
    except (ValueError, TypeError):
        return template


def _display_num(v: Any) -> Any:
    return int(v) if isinstance(v, float) and v == int(v) else v


def _apply(rule: dict, rec: dict, stage: str) -> bool:
    then = rule.get("then", {})
    effects = []
    for k, v in (then.get("set") or {}).items():
        rec[k] = v
        effects.append(f"{k}={v}")
    for k, src in (then.get("copy") or {}).items():
        rec[k] = rec.get(src)
        effects.append(f"{k}={_display_num(rec[k])}")
    for k, v in (then.get("score") or {}).items():
        rec["_scores"][k] = rec["_scores"].get(k, 0) + v
        effects.append(f"{k} {v:+d}")
    for t in ([then["tag"]] if isinstance(then.get("tag"), str) else then.get("tag") or []):
        if t not in rec["_tags"]:
            rec["_tags"].append(t)
    if then.get("flag"):
        rec["_flags"].append(_fmt(then["flag"], rec))
    if then.get("play") and then["play"] not in rec["_plays"]:
        rec["_plays"].append(then["play"])
        effects.append(f"play={then['play']}")
    if then.get("package"):
        rec["package"] = then["package"]
        effects.append(f"package={then['package']}")
    for addon in then.get("addons") or []:
        if addon not in rec["_addons"]:
            rec["_addons"].append(addon)
            effects.append(f"+{addon}")
    rec["_trace"].append({"stage": stage, "rule": rule["id"],
                          "reason": _fmt(rule.get("reason", rule["id"]), rec),
                          "effects": effects})
    return bool(then.get("stop"))


def group_compute(records: list[dict], spec: dict) -> None:
    """Fields that look across records, e.g. how many tools a customer has in the same category.

      tools_in_category: {count: {by: [customer, category]}}
      customer_spend:    {sum: {by: [customer], field: annual_cost}}
      customer_products: {values: {by: [customer], field: product}}
    """
    for name, how in (spec or {}).items():
        (kind, arg), = how.items()
        by = arg["by"] if isinstance(arg["by"], list) else [arg["by"]]
        groups: dict[tuple, list[dict]] = {}
        for r in records:
            groups.setdefault(tuple(str(r.get(b) or "").lower() for b in by), []).append(r)
        for members in groups.values():
            if kind == "count":
                val = len(members)
            elif kind == "sum":
                val = sum(_num(m.get(arg["field"])) or 0 for m in members)
            elif kind == "values":
                val = sorted({m.get(arg["field"]) for m in members if m.get(arg["field"])})
            else:
                raise ValueError(f"unknown group computed kind '{kind}'")
            for m in members:
                m[name] = val


def run_rules(records: list[dict], rules_cfg: dict, as_of: date) -> list[dict]:
    score_names = rules_cfg.get("scores", [])
    bands = rules_cfg.get("score_bands", {})
    for rec in records:
        rec.update(_scores={s: 0 for s in score_names}, _tags=[], _flags=[], _plays=[],
                   _addons=[], _trace=[])
        compute(rec, rules_cfg.get("computed"), as_of)
    group_compute(records, rules_cfg.get("group_computed"))
    for rec in records:
        compute(rec, rules_cfg.get("computed_after"), as_of)
        for stage in rules_cfg["stages"]:
            if not evaluate(stage.get("when"), rec):
                continue  # whole stage doesn't apply to this record
            fired = False
            for rule in stage["rules"]:
                if evaluate(rule.get("when"), rec):
                    fired = True
                    if _apply(rule, rec, stage["name"]) or stage.get("first_match"):
                        break
            if not fired and stage.get("else"):
                _apply({"id": f"{stage['name']}-default", **stage["else"]}, rec, stage["name"])
            if stage.get("after_compute"):
                compute(rec, stage["after_compute"], as_of)
        rec["score_total"] = sum(rec["_scores"].values())
        for name, cuts in bands.items():
            val = rec["score_total"] if name == "total" else rec["_scores"].get(name, 0)
            label = None
            for cut in cuts:  # [{min: 70, label: A}, ...] highest first
                if val >= cut["min"]:
                    label = cut["label"]
                    break
            rec[f"{name}_band"] = label
        for issue in rec["_issues"]:
            rec["_flags"].append(f"Data: {issue}")
    return records


def validate_rules(rules_cfg: dict, plays: dict, packages: dict) -> list[str]:
    """Catch typos before they silently do nothing."""
    problems = []
    seen = set()
    for stage in rules_cfg["stages"]:
        items = list(stage["rules"]) + ([{"id": f"{stage['name']}-else", **stage["else"]}] if stage.get("else") else [])
        for rule in items:
            if rule["id"] in seen:
                problems.append(f"duplicate rule id '{rule['id']}'")
            seen.add(rule["id"])
            then = rule.get("then", {})
            if then.get("play") and then["play"] not in plays:
                problems.append(f"rule '{rule['id']}' points to unknown play '{then['play']}'")
            if then.get("package") and then["package"] not in packages.get("packages", {}):
                problems.append(f"rule '{rule['id']}' points to unknown package '{then['package']}'")
            for a in then.get("addons") or []:
                if a not in packages.get("addons", {}):
                    problems.append(f"rule '{rule['id']}' points to unknown add-on '{a}'")
            for k in then.get("score") or {}:
                if k not in rules_cfg.get("scores", []):
                    problems.append(f"rule '{rule['id']}' scores undeclared score '{k}'")
            try:
                _check_ops(rule.get("when"))
            except ValueError as e:
                problems.append(f"rule '{rule['id']}': {e}")
    return problems


def _check_ops(cond: Any) -> None:
    if not cond or cond is True:
        return
    for key in ("all", "any"):
        if key in cond:
            for c in cond[key]:
                _check_ops(c)
            return
    if "not" in cond:
        _check_ops(cond["not"])
        return
    for op in cond:
        if op != "field" and op not in OPS:
            raise ValueError(f"unknown operator '{op}'")
