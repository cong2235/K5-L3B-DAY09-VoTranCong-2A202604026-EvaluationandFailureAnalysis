"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, brows = pr.get("rows") or [], base.get("rows") or []
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. non-finite metric values: `nan < min` is False, so a naive threshold check passes them.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v}: a non-finite value cannot be compared with a threshold")

    # 2. row count and duplicates.
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    want = int(man.get("items", 0)) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows but manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}"
                        " (rows dropped or duplicated)")
    dup = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dup:
        problems.append(f"duplicated (item, seed) rows: {dup[:3]}")

    # 3. the (item, seed) set must be the baseline's: same items, same seeds.
    pk, bk = set(keys), {(r.get("item_id"), r.get("seed")) for r in brows}
    if pk != bk:
        problems.append(f"(item, seed) set differs from the baseline: {len(bk - pk)} missing, {len(pk - bk)} extra"
                        " (cherry-picked seeds or items)")
    if man.get("items") != bman.get("items") or list(man.get("seeds") or []) != list(bman.get("seeds") or []):
        problems.append("manifest items/seeds differ from the baseline's")

    # 4. a grader that crashed leaves None (or a missing key): it silently leaves the mean.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics", []) if brows and m["id"] in brows[0]]
    for mid in graded:
        bad = [r for r in rows if r.get(mid) is None]
        if bad:
            problems.append(f"{len(bad)} row(s) with no value for graded metric {mid} (crashed grader?)")

    # 5. metrics must be what the rows say (a hand-edited summary hides failing rows).
    safety = {m["id"] for m in spec.get("metrics", []) if m.get("kind") == "safety"}
    for mid in graded:
        vals = [r[mid] for r in rows if r.get(mid) is not None]
        got = (pr.get("metrics") or {}).get(mid)
        if not vals or not isinstance(got, (int, float)) or not math.isfinite(got):
            continue
        calc = float(sum(vals)) if mid in safety else sum(vals) / len(vals)
        if abs(calc - got) > 1e-3:
            problems.append(f"metric {mid} is {got} but its rows give {calc:.4f} (summary edited by hand?)")
    by_item: dict[str, list[bool]] = {}
    for r in rows:
        if r.get("pass_rate") is not None:
            by_item.setdefault(r["item_id"], []).append(bool(r["pass_rate"]))
    for name, fn in (("pass_at", stats.pass_at_k), ("pass_hat", stats.pass_hat_k)):
        for mk, got in (pr.get("metrics") or {}).items():
            if not mk.startswith(name + "_") or not isinstance(got, (int, float)) or not math.isfinite(got):
                continue
            k = int(mk.rsplit("_", 1)[1])
            if by_item and min(len(v) for v in by_item.values()) >= k:
                calc = sum(fn(len(v), sum(v), k) for v in by_item.values()) / len(by_item)
                if abs(calc - got) > 1e-3:
                    problems.append(f"metric {mk} is {got} but its rows give {calc:.4f}")

    # 6. slice tags per item must be the baseline's (relabelling hides a regression from the slice gate).
    def tags(rs):
        out: dict[str, set] = {}
        for r in rs:
            out.setdefault(r.get("item_id"), set()).update(r.get("slices") or [])
        return out
    pt, bt = tags(rows), tags(brows)
    moved = sorted(i for i in pt.keys() & bt.keys() if pt[i] != bt[i])
    if moved:
        problems.append(f"slice tags changed for {len(moved)} item(s), e.g. {moved[0]}: {sorted(bt[moved[0]])} -> {sorted(pt[moved[0]])}")

    # 7. ratchet: on the same eval-set version a threshold may only get stricter.
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return problems


def _looser(new: dict, old: dict) -> list[str]:
    """What in a threshold-like dict is laxer than the old one (missing counts as laxer)."""
    out = []
    for k in ("max", "max_increase"):
        if k in old and (k not in new or new[k] > old[k]):
            out.append(f"{k} {old[k]} -> {new.get(k, 'removed')}")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"min {old['min']} -> {new.get('min', 'removed')}")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    out = []
    for key in ("eval_set", "labels", "adversarial_pack", "seeds"):
        if spec.get(key) != base_spec.get(key):
            out.append(f"spec {key} changed on the same eval-set version: {base_spec.get(key)} -> {spec.get(key)}")
    new = {m["id"]: m for m in spec.get("metrics", [])}
    for old in base_spec.get("metrics", []):
        cur = new.get(old["id"])
        if cur is None:
            out.append(f"metric {old['id']} was removed")
            continue
        why = _looser(cur.get("threshold") or {}, old.get("threshold") or {})
        if (old.get("threshold") or {}).get("no_significant_drop") and not (cur.get("threshold") or {}).get("no_significant_drop"):
            why.append("no_significant_drop dropped")
        if old.get("blocking") and not cur.get("blocking"):
            why.append("no longer blocking")
        if why:
            out.append(f"metric {old['id']} loosened: {'; '.join(why)}")
    cur_sl = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        cur = cur_sl.get((old["name"], old["metric"]))
        if cur is None:
            out.append(f"slice {old['name']}/{old['metric']} was removed")
            continue
        why = _looser(cur, old)
        if old.get("no_significant_drop") and not cur.get("no_significant_drop"):
            why.append("no_significant_drop dropped")
        if old.get("blocking") and not cur.get("blocking"):
            why.append("no longer blocking")
        if why:
            out.append(f"slice {old['name']}/{old['metric']} loosened: {'; '.join(why)}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    bs = spec.get("bootstrap", {})
    blocked, lines = [], []
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        got = per_item(pr, metric, slice_name=name)
        verdict, note = "ok", ""
        if not got:
            verdict, note = "missing", "no items in this slice"     # an empty slice proves nothing
            val = None
        else:
            val = sum(got.values()) / len(got)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                ref = per_item(base, metric, slice_name=name)
                keys = sorted(set(got) & set(ref))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([got[k] for k in keys], [ref[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict, note = "missing", "no item in common with the baseline"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        shown = "-" if val is None else f"{val:.4f}"
        lines.append(f"  {sid:<34} {shown:<8} {json.dumps({k: sl[k] for k in ('min',) if k in sl}):<14} {note:<34} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
