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
from statistics import mean

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems = []
    for section, identity in (("metrics", ("id",)), ("slices", ("name", "metric"))):
        current = {tuple(entry[k] for k in identity): entry for entry in spec.get(section, [])}
        for old in base_spec.get(section, []):
            key = tuple(old[k] for k in identity)
            new = current.get(key)
            problem = f"ratchet: {section} {'/'.join(key)}"
            if new is None:
                problems.append(f"{problem} removed")
                continue
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"{problem} made non-blocking")
            before = old.get("threshold", {}) if section == "metrics" else old
            after = new.get("threshold", {}) if section == "metrics" else new
            for bound in ("min", "max", "max_increase"):
                if bound in before and (bound not in after or
                        (after[bound] < before[bound] if bound == "min" else after[bound] > before[bound])):
                    problems.append(f"{problem} loosened {bound}")
            if before.get("no_significant_drop") and not after.get("no_significant_drop"):
                problems.append(f"{problem} removed paired CI check")
    return problems


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
    problems = _ratchet(spec, base_spec) if base_spec is not None else []
    graded = {m["id"] for m in spec["metrics"] if m["id"] in GRADERS}
    graded.update(s["metric"] for s in spec.get("slices", []))
    indexes = []
    for name, report in (("PR", pr), ("baseline", base)):
        manifest = report["manifest"]
        rows = report["rows"]
        seeds = manifest["seeds"]
        index = {(row["item_id"], row["seed"]): row for row in rows}
        indexes.append(index)
        items = {item for item, _ in index}
        if (len(index) != len(rows) or len(items) != manifest["items"] or
                not items or not seeds or len(set(seeds)) != len(seeds) or
                set(index) != {(item, seed) for item in items for seed in seeds}):
            problems.append(f"{name}: invalid, missing or duplicate item/seed rows")
        if set(seeds) != set(spec.get("seeds", seeds)):
            problems.append(f"{name}: seeds differ from metric spec")
        if report.get("evaluator_failures"):
            problems.append(f"{name}: evaluator failures recorded")
        for metric, value in report["metrics"].items():
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                problems.append(f"{name}: non-finite or invalid metric {metric}")
        for metric in sorted(graded):
            if any(type(row.get(metric)) is not bool for row in rows):
                problems.append(f"{name}: missing or invalid grader value for {metric}")
        if rows and ("metric_spec_version" in manifest or any("cost" in row for row in rows)) and not problems:
            costs = [row.get("cost") for row in rows]
            if any(not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0 for cost in costs):
                problems.append(f"{name}: invalid row cost")
            else:
                expected = aggregate(rows, sorted(graded), spec.get("pass_k", []))
                for metric, value in expected.items():
                    if report["metrics"].get(metric) != value:
                        problems.append(f"{name}: aggregate {metric} differs from trial rows")
    pr_index, base_index = indexes
    if pr_index.keys() != base_index.keys():
        problems.append("PR: item/seed coverage differs from baseline")
    elif any(set(pr_index[key].get("slices") or []) != set(base_index[key].get("slices") or [])
             for key in pr_index):
        problems.append("PR: slice tags differ from baseline")
    return problems


def _paired(pr: dict, base: dict, bootstrap: dict) -> tuple[float, float, float]:
    keys = sorted(pr)
    return stats.paired_bootstrap(
        [pr[key] for key in keys], [base[key] for key in keys],
        n_resamples=bootstrap.get("n_resamples", 1000), rng=bootstrap.get("rng", 2027),
        confidence=bootstrap.get("confidence", 0.95),
    )


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    for entry in spec.get("slices", []):
        name, metric = entry["name"], entry["metric"]
        key = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, name), per_item(base, metric, name)
        value = mean(a.values()) if a else None
        failed = value is None or a.keys() != b.keys() or value < entry.get("min", -math.inf)
        note = ""
        if entry.get("no_significant_drop") and a and a.keys() == b.keys():
            d, lo, hi = _paired(a, b, spec.get("bootstrap", {}))
            note = f" Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            failed |= hi < 0
        blocking = failed and entry.get("blocking")
        if blocking:
            blocked.append(key)
        verdict = "BLOCK" if blocking else "warn" if failed else "ok"
        lines.append(f"  {key} {value!s} ({len(a)} items){note} {verdict}")
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
            if a and a.keys() == b.keys():
                d, lo, hi = _paired(a, b, bs)
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
            else:
                verdict = "missing"
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
