"""Frozen-gate analysis for Rejection Filter Prospective Holdout V0.

PAPER / RESEARCH / READ-ONLY. Implements ONLY the gates written in
docs/rejection-filter-prospective-holdout-v0-preregistration-2026-09-29.md (frozen at 7384c94).
It reads persisted data; no provider calls. Route-only return != realized P&L.

Rules implemented (sections 3, 6-8, 10, 12 of the protocol):
- REJECTED: abs(entry_price_impact_pct_points) > 2.0; KEPT: known and <= 2.0; UNCLASSIFIED: missing
  or non-finite (never zero/imputed). Episodes with mint or freeze authority present are hard
  exclusions (counted, not tested); unknown authority is NOT excluded.
- Label: 900s route-only return, AVAILABLE only; catastrophic <= -80.0.
- No verdict until ALL four cohorts F1..F4 have a PASS acquisition report with the frozen protocol
  hash. There is deliberately no interim/partial analysis (no optional stopping).

Interpretation choice (protocol gate 4 says "KEPT is between 30% and 85% of classified episodes"):
"classified episodes" = episodes with a known impact and no hard exclusion, counted BEFORE requiring
a 900s outcome. The share among paired outcomes is reported too but does not gate.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from math import comb
from pathlib import Path
from statistics import median
from typing import Any

import rejection_filter_holdout_v0_collect as collect

VERSION = "rejection_filter_holdout_v0_analysis"
IMPACT_CAP_PP = 2.0
CATASTROPHIC_PCT = -80.0
MIN_IMPACT_COVERAGE_PCT = 80.0
MIN_PAIRED_TOTAL = 90
MIN_GROUP_TOTAL = 15
MIN_GROUP_PER_COHORT = 5
MIN_CATASTROPHIC_TOTAL = 10
MIN_EFFECT_PP = 15.0
ALPHA = 0.05
KEPT_SHARE_MIN_PCT = 30.0
KEPT_SHARE_MAX_PCT = 85.0
HORIZONS = (300, 900, 3600)
COHORTS = tuple(f"F{i}" for i in range(1, collect.COHORT_COUNT + 1))

KEEP = "KEEP_REJECTION_FILTER_TAIL_RISK_CANDIDATE"
KILL = "KILL_REJECTION_FILTER_TAIL_RISK_CANDIDATE"
INC_SUPPORT = "INCONCLUSIVE_REJECTION_FILTER_V0_SUPPORT"
INC_ACQ = "INCONCLUSIVE_REJECTION_FILTER_V0_ACQUISITION"
INC_LINEAGE = "INCONCLUSIVE_REJECTION_FILTER_V0_LINEAGE"


# ---------------------------------------------------------------- classification
def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def classify(impact: Any) -> str:
    x = _finite(impact)
    if x is None:
        return "UNCLASSIFIED"
    return "REJECTED" if abs(x) > IMPACT_CAP_PP else "KEPT"


def is_catastrophic(ret: float) -> bool:
    return ret <= CATASTROPHIC_PCT


# ---------------------------------------------------------------- statistics
def fisher_one_sided(a: int, n1: int, b: int, n2: int) -> float:
    """P(X >= a) for REJECTED catastrophic count a of n1 vs KEPT count b of n2 (hypergeometric)."""
    k, total = a + b, n1 + n2
    denom = comb(total, k)
    return sum(comb(n1, x) * comb(n2, k - x) for x in range(a, min(n1, k) + 1)) / denom


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    if n <= 0:
        return None

    def solve(target, decreasing):
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            v = target(mid)
            if (v > alpha / 2) == decreasing:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _binom_cdf(k - 1, n, p), False)  # f increasing in p
    upper = 1.0 if k == n else solve(lambda p: _binom_cdf(k, n, p), True)  # f decreasing in p
    return lower, upper


def dist_metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    pos = [v for v in values if v > 0]
    neg = [v for v in values if v < 0]
    gp, gl = sum(pos), -sum(neg)
    best = max(values)
    rest = list(values)
    rest.remove(best)
    return {
        "n": len(values),
        "median": median(values),
        "mean_without_best": (sum(rest) / len(rest)) if rest else None,
        "profit_factor": (gp / gl) if gl > 0 else (None if gp == 0 else "INF"),
        "largest_winner_share_of_gross_profit_pct": (100.0 * max(pos) / gp) if pos and gp > 0 else None,
    }


# ---------------------------------------------------------------- analysis
def _group_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = {"REJECTED": [], "KEPT": []}
    for r in rows:
        if r["group"] in by and r["ret900"] is not None:
            by[r["group"]].append(r["ret900"])
    out = {}
    for g, vals in by.items():
        cat = sum(1 for v in vals if is_catastrophic(v))
        out[g] = {
            "n": len(vals),
            "catastrophic": cat,
            "cat_rate_pct": (100.0 * cat / len(vals)) if vals else None,
            "cat_ci95": clopper_pearson(cat, len(vals)),
            "winners_ge_100": sum(1 for v in vals if v >= 100.0),
        }
    return out


def prepare_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """raw: {cohort, episode_key, impact, mint_auth, freeze_auth, labels, statuses}."""
    rows = []
    for r in raw_rows:
        excluded = bool(r.get("mint_auth") is True or r.get("freeze_auth") is True)
        labels = r.get("labels") or {}
        rows.append({
            "cohort": r["cohort"],
            "episode_key": r["episode_key"],
            "excluded_authority": excluded,
            "group": None if excluded else classify(r.get("impact")),
            "labels": {h: labels.get(h) for h in HORIZONS},
            "ret900": labels.get(900),
        })
    return rows


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if not r["excluded_authority"]]
    per: dict[str, Any] = {}
    for c in COHORTS:
        cr = [r for r in usable if r["cohort"] == c]
        counts = Counter(r["group"] for r in cr)
        known = counts["REJECTED"] + counts["KEPT"]
        per[c] = {
            "episodes": len(cr),
            "excluded_authority": sum(1 for r in rows if r["cohort"] == c and r["excluded_authority"]),
            "classified": known,
            "unclassified": counts["UNCLASSIFIED"],
            "impact_coverage_pct": (100.0 * known / len(cr)) if cr else 0.0,
            "groups": _group_counts(cr),
        }
    agg_groups = _group_counts(usable)
    rej, kept = agg_groups["REJECTED"], agg_groups["KEPT"]
    paired = rej["n"] + kept["n"]
    cat_total = rej["catastrophic"] + kept["catastrophic"]
    classified = sum(p["classified"] for p in per.values())
    kept_classified = sum(1 for r in usable if r["group"] == "KEPT")
    kept_share = (100.0 * kept_classified / classified) if classified else None

    support = {
        "impact_coverage_ge_80_every_cohort": all(p["impact_coverage_pct"] >= MIN_IMPACT_COVERAGE_PCT for p in per.values()),
        "paired_total_ge_90": paired >= MIN_PAIRED_TOTAL,
        "rejected_and_kept_ge_15_total": rej["n"] >= MIN_GROUP_TOTAL and kept["n"] >= MIN_GROUP_TOTAL,
        "rejected_and_kept_ge_5_every_cohort": all(
            p["groups"]["REJECTED"]["n"] >= MIN_GROUP_PER_COHORT and p["groups"]["KEPT"]["n"] >= MIN_GROUP_PER_COHORT
            for p in per.values()
        ),
        "catastrophic_total_ge_10": cat_total >= MIN_CATASTROPHIC_TOTAL,
    }
    result: dict[str, Any] = {
        "per_cohort": per,
        "aggregate": {"groups": agg_groups, "paired": paired, "classified_episodes": classified,
                      "kept_share_of_classified_pct": kept_share,
                      "kept_share_of_paired_pct": (100.0 * kept["n"] / paired) if paired else None},
        "support_checks": support,
    }
    if not all(support.values()):
        result["classification"] = INC_SUPPORT
        return result

    diff = rej["cat_rate_pct"] - kept["cat_rate_pct"]
    p_value = fisher_one_sided(rej["catastrophic"], rej["n"], kept["catastrophic"], kept["n"])
    effect = {
        "diff_ge_15pp": diff >= MIN_EFFECT_PP,
        "fisher_one_sided_p_lt_0_05": p_value < ALPHA,
        "rejected_gt_kept_in_every_cohort": all(
            p["groups"]["REJECTED"]["cat_rate_pct"] > p["groups"]["KEPT"]["cat_rate_pct"] for p in per.values()
        ),
        "kept_share_30_to_85": kept_share is not None and KEPT_SHARE_MIN_PCT <= kept_share <= KEPT_SHARE_MAX_PCT,
    }
    result["effect_values"] = {"cat_diff_pp": diff, "fisher_p": p_value}
    result["effect_checks"] = effect
    result["classification"] = KEEP if all(effect.values()) else KILL
    return result


def descriptive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Section 10, non-gating: fixed-horizon distributions of KEPT vs REJECTED."""
    out = {}
    for g in ("KEPT", "REJECTED"):
        out[g] = {
            f"{h}s": dist_metrics([r["labels"][h] for r in rows
                                   if r["group"] == g and r["labels"].get(h) is not None])
            for h in HORIZONS
        }
    return out


# ---------------------------------------------------------------- data loading
def load_raw_rows(run_keys: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from src.route_research_feature_review_v47 import build_feature_dataset_v47

    ds = build_feature_dataset_v47(acquisition_run_keys=tuple(run_keys.values()))
    by_key = {v: k for k, v in run_keys.items()}
    raw = [{
        "cohort": by_key[r.acquisition_run_key],
        "episode_key": r.episode_key,
        "impact": r.features.get("entry_price_impact_pct_points"),
        "mint_auth": r.features.get("hazard_mint_authority_present"),
        "freeze_auth": r.features.get("hazard_freeze_authority_present"),
        "labels": r.labels,
        "statuses": r.outcome_statuses,
    } for r in ds.rows]
    integrity = {
        "lineage_violations": ds.lineage_violations, "missing_decisions": ds.missing_decisions,
        "missing_episodes": ds.missing_episodes, "missing_hazard_attempts": ds.missing_hazard_attempts,
        "missing_entry_quotes": ds.missing_entry_quotes,
        "official_decision_mutations": ds.official_decision_mutations,
    }
    return raw, integrity


def check_acquisition_reports(root: Path) -> str | None:
    """Return a problem description, or None if F1..F4 all PASS with the frozen hash."""
    for i, c in enumerate(COHORTS, start=1):
        path = collect.report_path(i, root)
        if not path.is_file():
            return f"{c}: acquisition report missing ({path})"
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("classification") != collect.ACQ_PASS:
            return f"{c}: acquisition classification {data.get('classification')}"
        if data.get("protocol_sha256") != collect.PROTOCOL_SHA256:
            return f"{c}: acquisition report protocol hash differs from the frozen one"
    return None


def run_analysis(artifact_root: Path = collect.ARTIFACT_ROOT) -> dict[str, Any]:
    collect.verify_protocol()
    base = {"type": "rejection_filter_holdout_v0_analysis_report", "version": VERSION,
            "protocol_sha256": collect.PROTOCOL_SHA256, "scientific_thresholds_modified": False}
    problem = check_acquisition_reports(artifact_root)
    if problem:
        return {**base, "classification": INC_ACQ, "reason": problem}
    run_keys = {c: collect.run_key_for(i) for i, c in enumerate(COHORTS, start=1)}
    raw, integrity = load_raw_rows(run_keys)
    if any(integrity.values()):
        return {**base, "classification": INC_LINEAGE, "integrity": integrity}
    rows = prepare_rows(raw)
    result = evaluate(rows)
    return {**base, **result, "descriptive_non_gating": descriptive(rows), "integrity": integrity,
            "run_keys": run_keys,
            "interpretation": (
                "KEEP authorizes only a separately preregistered independent replication; it is not edge, "
                "not a TAKE/SKIP release and not live-money authorization. KILL closes this frozen rule. "
                "INCONCLUSIVE permits no verdict. route-only return != realized P&L.")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact-root", type=Path, default=collect.ARTIFACT_ROOT)
    args = ap.parse_args(argv)
    report = run_analysis(args.artifact_root)
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    out = args.artifact_root / "rejection-filter-v0-analysis-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    print(f"classification={report['classification']}")
    for k in ("reason", "integrity"):
        if report.get(k):
            print(f"{k}={report[k]}")
    for name in ("support_checks", "effect_checks", "effect_values"):
        for k, v in (report.get(name) or {}).items():
            print(f"{name.upper()} {k}={v}")
    print(f"report={out}")
    return 0 if report["classification"] in (KEEP, KILL) else 2


if __name__ == "__main__":
    raise SystemExit(main())
