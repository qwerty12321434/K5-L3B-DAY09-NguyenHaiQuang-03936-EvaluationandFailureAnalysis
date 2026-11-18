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
from collections import Counter
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item, aggregate
from lab9.graders import GRADERS


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
    problems = []
    graded = [m["id"] for m in spec["metrics"] if m["id"] in GRADERS]
    required = {m["id"] for m in spec["metrics"]}

    def finite(value):
        return isinstance(value, (int, float)) and math.isfinite(value)

    def validate(report, name):
        start = len(problems)
        manifest = report.get("manifest") or {}
        rows, metrics = report.get("rows"), report.get("metrics")
        if not isinstance(rows, list) or not isinstance(metrics, dict):
            problems.append(f"{name}: missing rows/metrics")
            return {}, set()
        seeds, count = manifest.get("seeds"), manifest.get("items")
        if (not isinstance(seeds, list) or not seeds or any(type(s) is not int for s in seeds)
                or len(set(seeds)) != len(seeds) or type(count) is not int or count <= 0):
            problems.append(f"{name}: invalid manifest items/seeds")
            return {}, set()
        if not manifest.get("eval_set_sha"):
            problems.append(f"{name}: missing eval_set_sha")
        if "seeds" in spec and set(seeds) != set(spec["seeds"]):
            problems.append(f"{name}: seeds differ from spec")
        if report.get("evaluator_failures"):
            problems.append(f"{name}: evaluator_failures is non-empty")
        if len(rows) != count * len(seeds):
            problems.append(f"{name}: row count differs from items x seeds")
        for mid in required - metrics.keys():
            problems.append(f"{name}: missing metric {mid}")
        for mid, value in metrics.items():
            if not finite(value):
                problems.append(f"{name}: non-finite/missing metric {mid}")
        pairs, slices = [], {}
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("item_id"), str)
                    or type(row.get("seed")) is not int):
                problems.append(f"{name}: malformed row")
                continue
            pair = (row["item_id"], row["seed"])
            pairs.append(pair)
            tags = row.get("slices", [])
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags) or len(set(tags)) != len(tags):
                problems.append(f"{name}: invalid slice tags for {pair}")
                continue
            tags = frozenset(tags)
            if pair[0] in slices and slices[pair[0]] != tags:
                problems.append(f"{name}: inconsistent slice tags across seeds")
            slices[pair[0]] = tags
            for mid in graded:
                value = row.get(mid)
                if not finite(value) or value not in (0, 1):
                    problems.append(f"{name}: missing/invalid grader {mid} at {pair}")
            if "cost_per_success" in required and (not finite(row.get("cost")) or row["cost"] < 0):
                problems.append(f"{name}: invalid row cost")
        if any(n != 1 for n in Counter(pairs).values()):
            problems.append(f"{name}: duplicated (item, seed) rows")
        wanted = {(item, seed) for item in slices for seed in seeds}
        if len(slices) != count or set(pairs) != wanted:
            problems.append(f"{name}: incomplete item x seed coverage")
        if len(problems) == start:
            k_values = set(spec.get("pass_k", []))
            for mid in required:
                if mid.startswith(("pass_at_", "pass_hat_")):
                    k_values.add(int(mid.rsplit("_", 1)[1]))
            calculated = aggregate([{**r, "cost": r.get("cost", 0)} for r in rows], graded, sorted(k_values))
            for mid in required & calculated.keys():
                value = calculated[mid]
                if not finite(value) or not math.isclose(value, metrics[mid], abs_tol=1e-8, rel_tol=1e-8):
                    problems.append(f"{name}: aggregate {mid} disagrees with rows")
        return slices, set(pairs)

    pr_slices, pr_pairs = validate(pr, "PR")
    base_slices, base_pairs = validate(base, "baseline")
    if pr_pairs != base_pairs:
        problems.append("PR (item, seed) set differs from baseline")
    if pr_slices != base_slices:
        problems.append("PR item slice tags differ from baseline")
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        def ratchet(old_rules, new_rules, key, scope):
            current = {r[key]: r for r in new_rules}
            for old in old_rules:
                rid = old[key]
                new = current.get(rid)
                if new is None:
                    problems.append(f"ratchet: {scope} {rid} removed")
                    continue
                if old.get("blocking") and not new.get("blocking"):
                    problems.append(f"ratchet: {scope} {rid} no longer blocking")
                if scope == "slice" and old["metric"] != new.get("metric"):
                    problems.append(f"ratchet: slice {rid} metric changed")
                a, b = (old, new) if scope == "slice" else (old.get("threshold", {}), new.get("threshold", {}))
                for field in ("min", "max", "max_increase"):
                    if field in a and (field not in b or not finite(b[field])
                            or (b[field] < a[field] if field == "min" else b[field] > a[field])):
                        problems.append(f"ratchet: {scope} {rid} loosened {field}")
                if a.get("no_significant_drop") and not b.get("no_significant_drop"):
                    problems.append(f"ratchet: {scope} {rid} dropped no_significant_drop")
        ratchet(base_spec.get("metrics", []), spec.get("metrics", []), "id", "metric")
        ratchet(base_spec.get("slices", []), spec.get("slices", []), "name", "slice")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for rule in spec.get("slices", []):
        name, metric = rule["name"], rule["metric"]
        mid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, name), per_item(base, metric, name)
        reasons = []
        value = sum(a.values()) / len(a) if a else None
        if not a or set(a) != set(b):
            reasons.append("missing or unpaired slice items")
        else:
            if "min" in rule and value < rule["min"]:
                reasons.append(f"below floor {rule['min']}")
            if rule.get("no_significant_drop"):
                keys = sorted(a)
                if len(keys) == 1:
                    delta = a[keys[0]] - b[keys[0]]
                    lo = hi = delta
                else:
                    delta, lo, hi = stats.paired_bootstrap(
                        [a[k] for k in keys], [b[k] for k in keys],
                        n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                        confidence=bs.get("confidence", 0.95))
                if hi < 0:
                    reasons.append(f"significant drop CI [{lo:+.3f}, {hi:+.3f}]")
        if reasons and rule.get("blocking"):
            blocked.append(mid)
        lines.append(f"  {mid} {value}: {'; '.join(reasons) if reasons else 'ok'}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
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
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
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
