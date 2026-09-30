"""Frozen-gate analysis for Rejection Filter Prospective Holdout V2 (independent replication).

PAPER / RESEARCH / READ-ONLY. Implements only the gates in
docs/rejection-filter-prospective-holdout-v2-replication-preregistration-2026-09-30.md. No provider
calls. Route-only return != realized P&L.

Same rule, on-time label, catastrophic threshold, support gates and effect gates as V1 (reused from the
V0/V1 modules), plus the V2 independence design:
- five VALID cohorts required (H1..H5, replacements H6/H7 only for DEGRADED ones), read from the
  acquisition reports and never re-adjudicated; no partial/interim analysis;
- each token counts once: tokens present in any V0/V1 run key are excluded (SEEN_IN_PRIOR_STUDY) and
  later episodes of a token inside V2 are excluded (REPEAT), mechanically by decision time;
- direction rule: REJECTED > KEPT in at least 4 of the 5 valid cohorts;
- impact coverage (>= 80% per cohort) is measured BEFORE token exclusions;
- valid cohorts must span >= 2 UTC days, <= 3 per day, none on the V1 collection days.
No return value is used to decide validity, exclusion, day grouping or replacement.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import rejection_filter_holdout_v0_analyze as v0
import rejection_filter_holdout_v1_analyze as an1
import rejection_filter_holdout_v1_collect as v1c
import rejection_filter_holdout_v2_collect as collect

VERSION = "rejection_filter_holdout_v2_analysis"
REPLICATED = "REPLICATED_REJECTION_FILTER_V2_TAIL_RISK"
NOT_REPLICATED = "NOT_REPLICATED_REJECTION_FILTER_V2"
INC_SUPPORT = "INCONCLUSIVE_REJECTION_FILTER_V2_SUPPORT"
INC_ACQ = "INCONCLUSIVE_REJECTION_FILTER_V2_ACQUISITION"
INC_LINEAGE = "INCONCLUSIVE_REJECTION_FILTER_V2_LINEAGE"
VERDICT_MAP = {v0.KEEP: REPLICATED, v0.KILL: NOT_REPLICATED, v0.INC_SUPPORT: INC_SUPPORT}
DIRECTION_MIN = 4
V0_PRIOR_RUN_KEYS = ("rejection-filter-v0-20260929-01-F1",)
V1_REPORT_DEFAULT = Path("artifacts/rejection_filter_holdout_v1/rejection-filter-v1-analysis-report.json")


# ------------------------------------------------------------------ pure pieces
def prepare_rows_v2(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = an1.prepare_rows_v1(raw)
    for row, r in zip(rows, raw):
        row["token"] = r["token"]
        row["as_of"] = r["as_of"]
    return rows


def apply_token_exclusions(rows: list[dict[str, Any]], prior_tokens: set[str]) -> None:
    """Mark row['token_status'] in OK | SEEN_IN_PRIOR_STUDY | REPEAT (first episode per token wins)."""
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: (r["as_of"], r["episode_key"])):
        token = row["token"]
        if token in prior_tokens:
            row["token_status"] = "SEEN_IN_PRIOR_STUDY"
        elif token in seen:
            row["token_status"] = "REPEAT"
        else:
            row["token_status"] = "OK"
            seen.add(token)


def dedup_first_per_token(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convenience for diagnostics: same REPEAT rule, no prior-study exclusion."""
    apply_token_exclusions(rows, set())
    return [r for r in rows if r["token_status"] == "OK"]


def exclusion_counts(rows: list[dict[str, Any]], cohorts: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in (*cohorts, "ALL"):
        sel = [r for r in rows if c == "ALL" or r["cohort"] == c]
        cnt = Counter(r["token_status"] for r in sel)
        out[c] = {"episodes": len(sel), **{k: cnt.get(k, 0) for k in ("OK", "SEEN_IN_PRIOR_STUDY", "REPEAT")}}
    return out


def pre_exclusion_coverage(rows: list[dict[str, Any]], cohorts: tuple[str, ...]) -> dict[str, float]:
    cov = {}
    for c in cohorts:
        cr = [r for r in rows if r["cohort"] == c and not r["excluded_authority"]]
        known = sum(1 for r in cr if r["group"] in ("KEPT", "REJECTED"))
        cov[c] = (100.0 * known / len(cr)) if cr else 0.0
    return cov


def per_day_table(post_rows: list[dict[str, Any]], cohort_dates: dict[str, str]) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in post_rows:
        by_day[cohort_dates.get(r["cohort"], "UNKNOWN")].append(r)
    return {day: v0._group_counts(rs) for day, rs in sorted(by_day.items())}


def pooled_with_v1(v2_groups: dict[str, Any], v1_report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Descriptive only: V1 aggregate counts + V2 counts (V1 tokens are excluded from V2, so disjoint)."""
    if not v1_report:
        return None
    try:
        g1 = v1_report["aggregate"]["groups"]
        out = {}
        for g in ("KEPT", "REJECTED"):
            n = g1[g]["n"] + v2_groups[g]["n"]
            cat = g1[g]["catastrophic"] + v2_groups[g]["catastrophic"]
            out[g] = {"n": n, "catastrophic": cat, "cat_rate_pct": (100.0 * cat / n) if n else None}
        return out
    except (KeyError, TypeError):
        return None


def evaluate_v2(rows: list[dict[str, Any]], cohorts: tuple[str, ...], prior_tokens: set[str],
                cohort_dates: dict[str, str]) -> dict[str, Any]:
    apply_token_exclusions(rows, prior_tokens)
    post = [r for r in rows if r["token_status"] == "OK"]
    result = v0.evaluate(post, cohorts, coverage_pct_override=pre_exclusion_coverage(rows, cohorts),
                         direction_min=DIRECTION_MIN)
    days = [cohort_dates.get(c) for c in cohorts]
    diverse = (None not in days and len(set(days)) >= collect.MIN_DISTINCT_UTC_DAYS
               and max(days.count(d) for d in set(days)) <= collect.MAX_COHORTS_STARTED_PER_UTC_DAY)
    result["support_checks"]["utc_days_ge_2_and_max_3_per_day"] = bool(diverse)
    if not diverse:
        result["classification"] = v0.INC_SUPPORT
        result.pop("effect_checks", None)
        result.pop("effect_values", None)
    result["classification"] = VERDICT_MAP[result["classification"]]
    return {**result,
            "token_exclusions_non_gating": exclusion_counts(rows, cohorts),
            "descriptive_non_gating": v0.descriptive(post),
            "missingness_non_gating": an1.missingness(post, cohorts),
            "worst_case_sensitivity_non_gating": an1.sensitivity(post),
            "per_utc_day_non_gating": per_day_table(post, cohort_dates)}


# ------------------------------------------------------------------ loading + run
def load_prior_tokens() -> set[str]:
    from src.database import connection

    keys = (*V0_PRIOR_RUN_KEYS, *(v1c.run_key_for(l) for l in v1c.LABELS))
    with connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT token_mint FROM opportunity_route_research_decisions WHERE acquisition_run_key IN (%s)"
            % ",".join("?" * len(keys)), keys).fetchall()
    return {str(r[0]) for r in rows}


def load_raw_rows(run_keys: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from src.opportunity_route_research_store import load_route_research_outcomes
    from src.route_research_feature_review_v47 import build_feature_dataset_v47

    ds = build_feature_dataset_v47(acquisition_run_keys=tuple(run_keys.values()))
    by_key = {v: k for k, v in run_keys.items()}
    o900: dict[tuple[str, str], str] = {}
    for rk in run_keys.values():
        for o in load_route_research_outcomes(acquisition_run_key=rk):
            if o.horizon_seconds == 900:
                o900[(rk, o.episode_key)] = collect.classify_outcome(
                    o.status, o.error_type, o.error_message, o.target_at, o.observed_at)
    raw = [{
        "cohort": by_key[r.acquisition_run_key], "episode_key": r.episode_key, "token": r.token_mint,
        "as_of": r.research_decision_as_of,
        "impact": r.features.get("entry_price_impact_pct_points"),
        "mint_auth": r.features.get("hazard_mint_authority_present"),
        "freeze_auth": r.features.get("hazard_freeze_authority_present"),
        "labels": r.labels, "statuses": r.outcome_statuses,
        "o900": o900.get((r.acquisition_run_key, r.episode_key), "TECHNICAL"),
    } for r in ds.rows]
    integrity = {"lineage_violations": ds.lineage_violations, "missing_decisions": ds.missing_decisions,
                 "missing_episodes": ds.missing_episodes, "missing_hazard_attempts": ds.missing_hazard_attempts,
                 "missing_entry_quotes": ds.missing_entry_quotes,
                 "official_decision_mutations": ds.official_decision_mutations}
    return raw, integrity


def check_reports(root: Path) -> tuple[list[str] | None, dict[str, str] | None, str | None]:
    """Return (valid labels, {label: utc date}, None) or (None, None, problem). No partial analysis."""
    if not collect.PROTOCOL_SHA256:
        return None, None, "V2 protocol is not frozen (no SHA-256 recorded in the runner)"
    try:
        state = collect.study_state(root)
    except SystemExit as exc:
        return None, None, str(exc)
    if state["status"] != "COMPLETE":
        return None, None, f"study state {state['status']} valid={state['valid']} degraded={state['degraded']}"
    reports = collect.read_reports(root)
    valid = state["valid"][: collect.VALID_COHORTS_REQUIRED]
    dates = {}
    for label in valid:
        data = reports[label]
        if data.get("protocol_sha256") != collect.PROTOCOL_SHA256:
            return None, None, f"{label}: acquisition report protocol hash differs from the frozen one"
        dates[label] = data.get("started_utc_date")
        if dates[label] in collect.FORBIDDEN_UTC_DATES:
            return None, None, f"{label}: collected on a V1 collection day ({dates[label]})"
    return valid, dates, None


def run_analysis(root: Path = collect.ARTIFACT_ROOT, v1_report_path: Path = V1_REPORT_DEFAULT) -> dict[str, Any]:
    base = {"type": "rejection_filter_holdout_v2_analysis_report", "version": VERSION,
            "protocol_sha256": collect.PROTOCOL_SHA256, "scientific_thresholds_modified": False}
    collect.verify_protocol()
    valid, dates, problem = check_reports(root)
    if problem:
        return {**base, "classification": INC_ACQ, "reason": problem}
    run_keys = {label: collect.run_key_for(label) for label in valid}
    raw, integrity = load_raw_rows(run_keys)
    if any(integrity.values()):
        return {**base, "classification": INC_LINEAGE, "integrity": integrity}
    rows = prepare_rows_v2(raw)
    report = evaluate_v2(rows, tuple(valid), load_prior_tokens(), dates)
    v1_report = json.loads(v1_report_path.read_text(encoding="utf-8")) if v1_report_path.is_file() else None
    post_groups = v0._group_counts([r for r in rows if r["token_status"] == "OK" and not r["excluded_authority"]])
    sens = report["worst_case_sensitivity_non_gating"]
    note = ("REPLICATED authorizes only: the filter as a documented research precondition in paper pipelines and a "
            "separately preregistered selection study conditional on KEPT. Not edge, not a TAKE/SKIP release, no "
            "funded BUY, no live money. NOT_REPLICATED means the V1 KEEP is not confirmed. INCONCLUSIVE permits no "
            "verdict. route-only return != realized P&L.")
    if report["classification"] == REPLICATED and sens.get("direction_reverses_under_worst_case"):
        note += " CAVEAT: the direction reverses when no-route 900s outcomes are counted as catastrophic."
    return {**base, **report, "valid_cohorts": valid, "cohort_utc_dates": dates, "integrity": integrity,
            "pooled_v1_plus_v2_descriptive_only": pooled_with_v1(post_groups, v1_report), "interpretation": note}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact-root", type=Path, default=collect.ARTIFACT_ROOT)
    ap.add_argument("--v1-report", type=Path, default=V1_REPORT_DEFAULT)
    args = ap.parse_args(argv)
    report = run_analysis(args.artifact_root, args.v1_report)
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    out = args.artifact_root / "rejection-filter-v2-analysis-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    print(f"classification={report['classification']}")
    for k in ("reason", "integrity", "interpretation"):
        if report.get(k):
            print(f"{k}={report[k]}")
    for name in ("support_checks", "effect_checks", "effect_values"):
        for k, v in (report.get(name) or {}).items():
            print(f"{name.upper()} {k}={v}")
    print(f"report={out}")
    return 0 if report["classification"] in (REPLICATED, NOT_REPLICATED) else 2


if __name__ == "__main__":
    raise SystemExit(main())
