"""Frozen-gate analysis for Rejection Filter V3 (USD 10 order size + buy-pressure selection within KEPT).

PAPER / RESEARCH / READ-ONLY. Implements only the gates in
docs/rejection-filter-prospective-holdout-v3-usd10-selection-preregistration-2026-10-02.md. No provider calls.
Route-only return != realized P&L. No verdict here is an edge claim.

Two claims, each with its own verdict at alpha = 0.025:
- P1: abs(price impact) > 2pp at the USD 10 BUY marks a higher 900s catastrophic-loss rate (<= -80%).
- P2: within KEPT, higher `flow60_wallet_direction_balance` goes with better 900s route-only returns.
Both are evaluated regardless of each other. Ten VALID cohorts are required, read from the acquisition reports
and never re-adjudicated; no partial/interim analysis. Tokens present in any V0/V1/V2 run key are excluded
(SEEN_IN_PRIOR_STUDY); later episodes of a token inside V3 are excluded (REPEAT). Impact coverage is measured
before token exclusions. The P2 median cutoff is computed from feature values only (outcome-blind).
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from statistics import median
from typing import Any

import rejection_filter_holdout_v0_analyze as v0
import rejection_filter_holdout_v1_analyze as an1
import rejection_filter_holdout_v1_collect as v1c
import rejection_filter_holdout_v2_analyze as an2
import rejection_filter_holdout_v2_collect as v2c
import rejection_filter_holdout_v3_collect as collect
from research import discover_kept_group_v0 as dk

VERSION = "rejection_filter_holdout_v3_analysis"
P1_CONFIRMED = "CONFIRMED_REJECTION_FILTER_AT_USD10"
P1_NOT_CONFIRMED = "NOT_CONFIRMED_REJECTION_FILTER_AT_USD10"
P1_INC_SUPPORT = "INCONCLUSIVE_REJECTION_FILTER_V3_P1_SUPPORT"
P1_INC_ACQ = "INCONCLUSIVE_REJECTION_FILTER_V3_P1_ACQUISITION"
P1_INC_LINEAGE = "INCONCLUSIVE_REJECTION_FILTER_V3_P1_LINEAGE"
P2_KEEP = "KEEP_BUY_PRESSURE_SELECTION_CANDIDATE_V3"
P2_KILL = "KILL_BUY_PRESSURE_SELECTION_CANDIDATE_V3"
P2_INC_SUPPORT = "INCONCLUSIVE_BUY_PRESSURE_SELECTION_V3_P2_SUPPORT"
P2_INC_ACQ = "INCONCLUSIVE_BUY_PRESSURE_SELECTION_V3_P2_ACQUISITION"
P2_INC_LINEAGE = "INCONCLUSIVE_BUY_PRESSURE_SELECTION_V3_P2_LINEAGE"

ALPHA = 0.025
FEATURE = "flow60_wallet_direction_balance"
DESCRIPTIVE_FEATURES = ("flow10_buy_share_pct", "flow30_buy_share_pct", "flow60_buy_share_pct",
                        "flow30_wallet_direction_balance")
PERMUTATIONS = 20000
SEED = 20261003
P1_MIN_PAIRED = 120
P1_MIN_GROUP = 15
P1_MIN_CATASTROPHIC = 10
P1_MIN_EVALUABLE_COHORTS = 8
P1_EVALUABLE_GROUP_MIN = 3
P1_DIRECTION_SHARE = 0.70
P2_MIN_PAIRED = 120
P2_MIN_FEATURE_COVERAGE_PCT = 80.0
PROJECTED_KEPT_SHARE_PCT = 57.0
IMPACT_BINS = ((0.0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 25.0), (25.0, math.inf))


# ------------------------------------------------------------------ pure pieces
def prepare_rows_v3(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = an2.prepare_rows_v2(raw)
    for row, r in zip(rows, raw):
        row["features"], row["impact"] = r.get("features") or {}, r.get("impact")
    return rows


def feature_value(row: dict[str, Any], name: str = FEATURE) -> float | None:
    v = row["features"].get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def profit_factor(values: list[float]) -> float | None:
    """gross profit / gross loss; inf when there are gains and no losses; None when empty."""
    if not values:
        return None
    gp = sum(v for v in values if v > 0)
    gl = -sum(v for v in values if v < 0)
    if gl > 0:
        return gp / gl
    return math.inf if gp > 0 else 0.0


def mean_without_best(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    rest = sorted(values)[:-1]
    return sum(rest) / len(rest)


def one_sided_perm_p(x: list[float], y: list[float], perms: int = PERMUTATIONS, seed: int = SEED) -> tuple[float, float]:
    """(rho, p) for H1: rho > 0, by permutation of the y ranks with a fixed seed."""
    rx, ry = dk.ranks(x), dk.ranks(y)
    rho = dk.pearson(rx, ry)
    rng = random.Random(seed)
    work, hits = list(ry), 0
    for _ in range(perms):
        rng.shuffle(work)
        if dk.pearson(rx, work) >= rho - 1e-12:
            hits += 1
    return rho, (hits + 1) / (perms + 1)


def _rho_if_defined(x: list[float], y: list[float]) -> float | None:
    if len(x) < 8 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return dk.spearman(x, y)


def clean(obj: Any) -> Any:
    """JSON-safe copy: +inf (profit factor without losses) becomes the string "INF"."""
    if isinstance(obj, float) and math.isinf(obj):
        return "INF" if obj > 0 else "-INF"
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj


def day_ok(dates: list[str | None]) -> bool:
    return collect.day_diversity_ok(dates)


# ------------------------------------------------------------------ P1
def evaluate_p1(post: list[dict[str, Any]], cohorts: tuple[str, ...], coverage: dict[str, float],
                days_ok: bool) -> dict[str, Any]:
    usable = [r for r in post if not r["excluded_authority"]]
    per: dict[str, Any] = {}
    for c in cohorts:
        g = v0._group_counts([r for r in usable if r["cohort"] == c])
        per[c] = {"groups": g, "evaluable": min(g["REJECTED"]["n"], g["KEPT"]["n"]) >= P1_EVALUABLE_GROUP_MIN,
                  "impact_coverage_pct_pre_exclusion": coverage.get(c, 0.0)}
    agg = v0._group_counts(usable)
    rej, kept = agg["REJECTED"], agg["KEPT"]
    paired = rej["n"] + kept["n"]
    cat_total = rej["catastrophic"] + kept["catastrophic"]
    evaluable = [c for c, p in per.items() if p["evaluable"]]
    classified = sum(1 for r in usable if r["group"] in ("KEPT", "REJECTED"))
    kept_classified = sum(1 for r in usable if r["group"] == "KEPT")
    kept_share = (100.0 * kept_classified / classified) if classified else None
    support = {
        "impact_coverage_ge_80_every_cohort": all(coverage.get(c, 0.0) >= v0.MIN_IMPACT_COVERAGE_PCT for c in cohorts),
        "paired_total_ge_120": paired >= P1_MIN_PAIRED,
        "rejected_and_kept_ge_15_total": rej["n"] >= P1_MIN_GROUP and kept["n"] >= P1_MIN_GROUP,
        "catastrophic_total_ge_10": cat_total >= P1_MIN_CATASTROPHIC,
        "evaluable_cohorts_ge_8": len(evaluable) >= P1_MIN_EVALUABLE_COHORTS,
        "utc_days_ge_3_and_max_3_per_day": bool(days_ok),
    }
    out: dict[str, Any] = {
        "per_cohort": per,
        "aggregate": {"groups": agg, "paired": paired, "classified_episodes": classified,
                      "kept_share_of_classified_pct": kept_share, "evaluable_cohorts": len(evaluable)},
        "support_checks": support,
    }
    if not all(support.values()):
        out["classification"] = P1_INC_SUPPORT
        return out
    diff = rej["cat_rate_pct"] - kept["cat_rate_pct"]
    p = v0.fisher_one_sided(rej["catastrophic"], rej["n"], kept["catastrophic"], kept["n"])
    right = sum(1 for c in evaluable
                if per[c]["groups"]["REJECTED"]["cat_rate_pct"] > per[c]["groups"]["KEPT"]["cat_rate_pct"])
    effect = {
        "diff_ge_15pp": diff >= v0.MIN_EFFECT_PP,
        "fisher_one_sided_p_lt_0_025": p < ALPHA,
        "rejected_gt_kept_in_at_least_70pct_of_evaluable_cohorts": right >= P1_DIRECTION_SHARE * len(evaluable),
        "kept_share_30_to_85": kept_share is not None
        and v0.KEPT_SHARE_MIN_PCT <= kept_share <= v0.KEPT_SHARE_MAX_PCT,
    }
    out["effect_values"] = {"cat_diff_pp": diff, "fisher_p": p, "cohorts_with_correct_direction": right,
                            "evaluable_cohorts": len(evaluable)}
    out["effect_checks"] = effect
    out["classification"] = P1_CONFIRMED if all(effect.values()) else P1_NOT_CONFIRMED
    return out


# ------------------------------------------------------------------ P2
def p2_cutoff(post: list[dict[str, Any]]) -> float | None:
    """Median of the feature over analysis-eligible KEPT episodes. Reads no outcome."""
    vals = [feature_value(r) for r in post if r["group"] == "KEPT" and not r["excluded_authority"]]
    vals = [v for v in vals if v is not None]
    return median(vals) if vals else None


def evaluate_p2(post: list[dict[str, Any]], cohort_start: dict[str, int], days_ok: bool) -> dict[str, Any]:
    kept = [r for r in post if r["group"] == "KEPT" and not r["excluded_authority"]]
    paired = [r for r in kept if r["ret900"] is not None]
    known = [r for r in paired if feature_value(r) is not None]
    cov = (100.0 * len(known) / len(paired)) if paired else 0.0
    support = {
        "kept_paired_ge_120": len(paired) >= P2_MIN_PAIRED,
        "feature_known_ge_80pct_of_kept_paired": cov >= P2_MIN_FEATURE_COVERAGE_PCT,
        "utc_days_ge_3_and_max_3_per_day": bool(days_ok),
    }
    cutoff = p2_cutoff(post)
    out: dict[str, Any] = {"support_checks": support, "kept_paired": len(paired), "feature_known": len(known),
                           "feature_coverage_pct": cov, "cutoff_median": cutoff}
    xs = [feature_value(r) for r in known]
    ys = [r["ret900"] for r in known]
    high = [r["ret900"] for r in known if feature_value(r) > cutoff] if cutoff is not None else []
    low = [r["ret900"] for r in known if feature_value(r) <= cutoff] if cutoff is not None else []
    out["groups_non_gating"] = {name: {"n": len(vals), "median": median(vals) if vals else None,
                                       "mean_without_best": mean_without_best(vals),
                                       "profit_factor": profit_factor(vals)}
                                for name, vals in (("HIGH", high), ("LOW", low))}
    if not all(support.values()):
        out["classification"] = P2_INC_SUPPORT
        return out
    rho, p = one_sided_perm_p(xs, ys)
    order = sorted(cohort_start, key=lambda c: (cohort_start[c], c))
    first = set(order[: len(order) // 2])
    halves = []
    for part in (first, set(order) - first):
        sel = [r for r in known if r["cohort"] in part]
        halves.append(_rho_if_defined([feature_value(r) for r in sel], [r["ret900"] for r in sel]))
    hp, lp = profit_factor(high), profit_factor(low)
    hm, lm = mean_without_best(high), mean_without_best(low)
    effect = {
        "spearman_rho_gt_0_perm_p_lt_0_025": rho > 0 and p < ALPHA,
        "high_median_gt_low_median": bool(high and low and median(high) > median(low)),
        "high_profit_factor_gt_low": hp is not None and lp is not None and hp > lp,
        "high_mean_without_best_gt_low": hm is not None and lm is not None and hm > lm,
        "rho_gt_0_in_both_halves": all(h is not None and h > 0 for h in halves),
    }
    out["effect_values"] = {"rho": rho, "perm_p_one_sided": p, "half_rho": halves,
                            "high_pf": hp, "low_pf": lp, "high_mean_without_best": hm, "low_mean_without_best": lm}
    out["effect_checks"] = effect
    out["classification"] = P2_KEEP if all(effect.values()) else P2_KILL
    return out


# ------------------------------------------------------------------ non-gating reports
def impact_bin_table(post: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for lo, hi in IMPACT_BINS:
        vals = []
        for r in post:
            x = v0._finite(r.get("impact"))
            if r["excluded_authority"] or r["ret900"] is None or x is None:
                continue
            if lo <= abs(x) < hi or (lo == 0.0 and abs(x) == 0.0):
                vals.append(r["ret900"])
        cat = sum(1 for v in vals if v0.is_catastrophic(v))
        out.append({"abs_impact_pp_from": lo, "abs_impact_pp_to": None if math.isinf(hi) else hi, "n": len(vals),
                    "catastrophic": cat, "cat_rate_pct": (100.0 * cat / len(vals)) if vals else None,
                    "median": median(vals) if vals else None})
    return out


def other_feature_rhos(post: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [r for r in post if r["group"] == "KEPT" and not r["excluded_authority"] and r["ret900"] is not None]
    out = {}
    for name in DESCRIPTIVE_FEATURES:
        pts = [(feature_value(r, name), r["ret900"]) for r in paired if feature_value(r, name) is not None]
        out[name] = {"n": len(pts), "rho": _rho_if_defined([p[0] for p in pts], [p[1] for p in pts])}
    return out


def p2_group_distributions(post: list[dict[str, Any]], cutoff: float | None) -> dict[str, Any]:
    out = {}
    paired = [r for r in post if r["group"] == "KEPT" and not r["excluded_authority"]
              and feature_value(r) is not None and cutoff is not None]
    for name, pick in (("HIGH", lambda r: feature_value(r) > cutoff), ("LOW", lambda r: feature_value(r) <= cutoff)):
        sel = [r for r in paired if pick(r)]
        out[name] = {f"{h}s": v0.dist_metrics([r["labels"][h] for r in sel if r["labels"].get(h) is not None])
                     for h in (300, 900)}
    return out


# ------------------------------------------------------------------ evaluation of a loaded dataset
def evaluate_v3(rows: list[dict[str, Any]], cohorts: tuple[str, ...], prior_tokens: set[str],
                cohort_dates: dict[str, str], cohort_start: dict[str, int]) -> dict[str, Any]:
    an2.apply_token_exclusions(rows, prior_tokens)
    post = [r for r in rows if r["token_status"] == "OK"]
    coverage = an2.pre_exclusion_coverage(rows, cohorts)
    days_ok = day_ok([cohort_dates.get(c) for c in cohorts])
    p1 = evaluate_p1(post, cohorts, coverage, days_ok)
    p2 = evaluate_p2(post, {c: cohort_start[c] for c in cohorts}, days_ok)
    kept_share = p1["aggregate"]["kept_share_of_classified_pct"]
    return {
        "p1": p1, "p2": p2,
        "token_exclusions_non_gating": an2.exclusion_counts(rows, cohorts),
        "missingness_non_gating": an1.missingness(post, cohorts),
        "worst_case_sensitivity_non_gating": an1.sensitivity(post),
        "per_utc_day_non_gating": an2.per_day_table(post, cohort_dates),
        "impact_bins_non_gating": impact_bin_table(post),
        "kept_share_vs_projection_non_gating": {"observed_pct": kept_share, "projected_pct": PROJECTED_KEPT_SHARE_PCT},
        "other_buy_pressure_features_rho_non_gating": other_feature_rhos(post),
        "p2_group_distributions_non_gating": p2_group_distributions(post, p2["cutoff_median"]),
        "descriptive_non_gating": v0.descriptive(post),
    }


# ------------------------------------------------------------------ loading + run
def prior_run_keys() -> tuple[str, ...]:
    return (*an2.V0_PRIOR_RUN_KEYS, *(v1c.run_key_for(l) for l in v1c.LABELS),
            *(v2c.run_key_for(l) for l in v2c.LABELS))


def load_prior_tokens() -> set[str]:
    from src.database import connection

    keys = prior_run_keys()
    with connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT token_mint FROM opportunity_route_research_decisions WHERE acquisition_run_key IN (%s)"
            % ",".join("?" * len(keys)), keys).fetchall()
    return {str(r[0]) for r in rows}


def load_raw_rows(run_keys: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from src.opportunity_route_research_store import load_route_research_outcomes
    from src.route_research_early_opportunity_v55 import build_early_opportunity_dataset_v55

    ds = build_early_opportunity_dataset_v55(acquisition_run_keys=tuple(run_keys.values()))
    by_key = {v: k for k, v in run_keys.items()}
    o900: dict[tuple[str, str], str] = {}
    for rk in run_keys.values():
        for o in load_route_research_outcomes(acquisition_run_key=rk):
            if o.horizon_seconds == 900:
                o900[(rk, o.episode_key)] = collect.v1.classify_outcome(
                    o.status, o.error_type, o.error_message, o.target_at, o.observed_at)
    raw = [{
        "cohort": by_key[r.acquisition_run_key], "episode_key": r.episode_key, "token": r.token_mint,
        "as_of": r.research_decision_as_of, "impact": r.features.get("entry_price_impact_pct_points"),
        "mint_auth": r.features.get("hazard_mint_authority_present"),
        "freeze_auth": r.features.get("hazard_freeze_authority_present"),
        "labels": r.labels, "statuses": r.outcome_statuses,
        "o900": o900.get((r.acquisition_run_key, r.episode_key), "TECHNICAL"),
        "features": dict(r.features),
    } for r in ds.rows]
    base = ds.base
    integrity = {"lineage_violations": base.lineage_violations, "missing_decisions": base.missing_decisions,
                 "missing_episodes": base.missing_episodes, "missing_hazard_attempts": base.missing_hazard_attempts,
                 "missing_entry_quotes": base.missing_entry_quotes,
                 "official_decision_mutations": base.official_decision_mutations,
                 "augmentation_failures": ds.augmentation_failures,
                 "feature_clock_violations": ds.feature_clock_violations}
    return raw, integrity


def check_reports(root: Path) -> tuple[list[str] | None, dict[str, str] | None, dict[str, int] | None, str | None]:
    """Return (valid labels, {label: utc date}, {label: started_at}, None) or (None, None, None, problem)."""
    if not collect.PROTOCOL_SHA256:
        return None, None, None, "V3 protocol is not frozen (no SHA-256 recorded in the runner)"
    try:
        state = collect.study_state(root)
    except SystemExit as exc:
        return None, None, None, str(exc)
    if state["status"] != "COMPLETE":
        return None, None, None, f"study state {state['status']} valid={state['valid']} degraded={state['degraded']}"
    reports = collect.read_reports(root)
    valid = state["valid"][: collect.VALID_COHORTS_REQUIRED]
    dates, starts = {}, {}
    for label in valid:
        data = reports[label]
        if data.get("protocol_sha256") != collect.PROTOCOL_SHA256:
            return None, None, None, f"{label}: acquisition report protocol hash differs from the frozen one"
        if data.get("order_notional_usd") != collect.RESEARCH_NOTIONAL_USD:
            return None, None, None, f"{label}: acquisition report order size is not USD {collect.RESEARCH_NOTIONAL_USD}"
        dates[label], starts[label] = data.get("started_utc_date"), data.get("started_at")
        if dates[label] is None or not isinstance(starts[label], int):
            return None, None, None, f"{label}: acquisition report lacks start time/date"
    return valid, dates, starts, None


def run_analysis(root: Path = collect.ARTIFACT_ROOT) -> dict[str, Any]:
    base = {"type": "rejection_filter_holdout_v3_analysis_report", "version": VERSION,
            "protocol_sha256": collect.PROTOCOL_SHA256, "scientific_thresholds_modified": False}
    collect.verify_protocol()
    valid, dates, starts, problem = check_reports(root)
    if problem:
        return {**base, "p1_classification": P1_INC_ACQ, "p2_classification": P2_INC_ACQ, "reason": problem}
    raw, integrity = load_raw_rows({label: collect.run_key_for(label) for label in valid})
    if any(integrity.values()):
        return {**base, "p1_classification": P1_INC_LINEAGE, "p2_classification": P2_INC_LINEAGE,
                "integrity": integrity}
    report = evaluate_v3(prepare_rows_v3(raw), tuple(valid), load_prior_tokens(), dates, starts)
    note = ("P1 CONFIRMED means the impact filter's tail-risk separation holds at USD 10; P2 KEEP means only that a "
            "separately preregistered independent replication on other days is warranted. Neither is edge, a "
            "TAKE/SKIP release, funded BUY, shadow execution or live money. NOT_CONFIRMED/KILL close the exact "
            "claim with no retune. INCONCLUSIVE permits no verdict. route-only return != realized P&L.")
    return {**base, "p1_classification": report["p1"]["classification"],
            "p2_classification": report["p2"]["classification"], **report, "valid_cohorts": valid,
            "cohort_utc_dates": dates, "integrity": integrity, "interpretation": note}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact-root", type=Path, default=collect.ARTIFACT_ROOT)
    args = ap.parse_args(argv)
    report = run_analysis(args.artifact_root)
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    out = args.artifact_root / "rejection-filter-v3-analysis-report.json"
    out.write_text(json.dumps(clean(report), indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    print(f"P1={report['p1_classification']}")
    print(f"P2={report['p2_classification']}")
    for k in ("reason", "integrity", "interpretation"):
        if report.get(k):
            print(f"{k}={report[k]}")
    for claim in ("p1", "p2"):
        for name in ("support_checks", "effect_checks", "effect_values"):
            for k, v in ((report.get(claim) or {}).get(name) or {}).items():
                print(f"{claim.upper()} {name.upper()} {k}={v}")
    print(f"report={out}")
    ok = (report["p1_classification"] in (P1_CONFIRMED, P1_NOT_CONFIRMED)
          and report["p2_classification"] in (P2_KEEP, P2_KILL))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
