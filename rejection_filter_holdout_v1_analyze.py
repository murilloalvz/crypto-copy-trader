"""Frozen-gate analysis for Rejection Filter Prospective Holdout V1.

PAPER / RESEARCH / READ-ONLY. Implements only the gates in
docs/rejection-filter-prospective-holdout-v1-preregistration-2026-09-29.md. No provider calls.
Route-only return != realized P&L.

Same rule, label and effect/support gates as V0 (reused from rejection_filter_holdout_v0_analyze),
plus the V1 acquisition-quality machinery:
- only cohorts the runner marked VALID enter the analysis; cohort validity is READ from the
  acquisition reports and never re-adjudicated here (no return value is used to decide it);
- a 900s label counts only if it was collected on time (lateness <= cap); LATE, TECHNICAL,
  STRUCTURAL and PENDING outcomes are unavailable for pairing and never converted to a value;
- mandatory NON-GATING missingness tables per group and a worst-case sensitivity that counts
  STRUCTURAL (no-route) 900s outcomes as catastrophic;
- no interim/partial analysis: it refuses until study_state == COMPLETE (four VALID cohorts).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import rejection_filter_holdout_v0_analyze as v0
import rejection_filter_holdout_v1_collect as collect

VERSION = "rejection_filter_holdout_v1_analysis"
KEEP = "KEEP_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE"
KILL = "KILL_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE"
INC_SUPPORT = "INCONCLUSIVE_REJECTION_FILTER_V1_SUPPORT"
INC_ACQ = "INCONCLUSIVE_REJECTION_FILTER_V1_ACQUISITION"
INC_LINEAGE = "INCONCLUSIVE_REJECTION_FILTER_V1_LINEAGE"
VERDICT_MAP = {v0.KEEP: KEEP, v0.KILL: KILL, v0.INC_SUPPORT: INC_SUPPORT}
CLASSES = ("AVAILABLE_ON_TIME", "LATE", "TECHNICAL", "STRUCTURAL", "PENDING")


# ------------------------------------------------------------------ pure pieces
def prepare_rows_v1(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """V0 preparation, then enforce the on-time label rule using each row's o900 class."""
    rows = v0.prepare_rows(raw)
    for row, r in zip(rows, raw):
        row["o900"] = r["o900"]
        if r["o900"] != "AVAILABLE_ON_TIME":
            row["labels"] = {**row["labels"], 900: None}
            row["ret900"] = None
    return rows


def missingness(rows: list[dict[str, Any]], cohorts: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in (*cohorts, "ALL"):
        out[c] = {}
        for g in ("KEPT", "REJECTED", "UNCLASSIFIED"):
            sel = [r for r in rows if not r["excluded_authority"] and r["group"] == g
                   and (c == "ALL" or r["cohort"] == c)]
            cnt = Counter(r["o900"] for r in sel)
            out[c][g] = {"episodes": len(sel), **{k: cnt.get(k, 0) for k in CLASSES}}
    return out


def sensitivity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Worst case: STRUCTURAL (no-route) 900s outcomes counted as catastrophic. Non-gating."""
    res: dict[str, Any] = {}
    for g in ("KEPT", "REJECTED"):
        sel = [r for r in rows if not r["excluded_authority"] and r["group"] == g]
        paired = [r["ret900"] for r in sel if r["ret900"] is not None]
        cat = sum(1 for v in paired if v0.is_catastrophic(v))
        structural = sum(1 for r in sel if r["o900"] == "STRUCTURAL")
        n = len(paired) + structural
        res[g] = {"paired": len(paired), "catastrophic": cat, "structural_no_route": structural,
                  "worst_case_cat_rate_pct": (100.0 * (cat + structural) / n) if n else None,
                  "primary_cat_rate_pct": (100.0 * cat / len(paired)) if paired else None}
    k, r_ = res["KEPT"], res["REJECTED"]
    if None in (k["worst_case_cat_rate_pct"], r_["worst_case_cat_rate_pct"],
                k["primary_cat_rate_pct"], r_["primary_cat_rate_pct"]):
        res["direction_reverses_under_worst_case"] = None
    else:
        res["direction_reverses_under_worst_case"] = bool(
            r_["primary_cat_rate_pct"] > k["primary_cat_rate_pct"]
            and r_["worst_case_cat_rate_pct"] <= k["worst_case_cat_rate_pct"])
    return res


def check_reports(root: Path) -> tuple[list[str] | None, str | None]:
    """Return (valid cohort labels, None) or (None, problem). No partial analysis."""
    if not collect.PROTOCOL_SHA256:
        return None, "V1 protocol is not frozen (no SHA-256 recorded in the runner)"
    try:
        state = collect.study_state(root)
    except SystemExit as exc:
        return None, str(exc)
    if state["status"] != "COMPLETE":
        return None, f"study state {state['status']} valid={state['valid']} degraded={state['degraded']}"
    valid = state["valid"][: collect.VALID_COHORTS_REQUIRED]
    for label in valid:
        data = json.loads(collect.report_path(label, root).read_text(encoding="utf-8"))
        if data.get("protocol_sha256") != collect.PROTOCOL_SHA256:
            return None, f"{label}: acquisition report protocol hash differs from the frozen one"
    return valid, None


# ------------------------------------------------------------------ loading + run
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
        "cohort": by_key[r.acquisition_run_key], "episode_key": r.episode_key,
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


def analyze(raw: list[dict[str, Any]], cohorts: tuple[str, ...]) -> dict[str, Any]:
    rows = prepare_rows_v1(raw)
    result = v0.evaluate(rows, cohorts)
    result["classification"] = VERDICT_MAP[result["classification"]]
    return {**result, "descriptive_non_gating": v0.descriptive(rows),
            "missingness_non_gating": missingness(rows, cohorts), "worst_case_sensitivity_non_gating": sensitivity(rows)}


def run_analysis(root: Path = collect.ARTIFACT_ROOT) -> dict[str, Any]:
    base = {"type": "rejection_filter_holdout_v1_analysis_report", "version": VERSION,
            "protocol_sha256": collect.PROTOCOL_SHA256, "scientific_thresholds_modified": False}
    collect.verify_protocol()
    valid, problem = check_reports(root)
    if problem:
        return {**base, "classification": INC_ACQ, "reason": problem}
    run_keys = {label: collect.run_key_for(label) for label in valid}
    raw, integrity = load_raw_rows(run_keys)
    if any(integrity.values()):
        return {**base, "classification": INC_LINEAGE, "integrity": integrity}
    report = analyze(raw, tuple(valid))
    sens = report["worst_case_sensitivity_non_gating"]
    note = ("KEEP authorizes only a separately preregistered independent replication; not edge, not a TAKE/SKIP "
            "release, no live money. KILL closes this frozen rule. INCONCLUSIVE permits no verdict. "
            "route-only return != realized P&L.")
    if report["classification"] == KEEP and sens.get("direction_reverses_under_worst_case"):
        note += " CAVEAT: the direction reverses when no-route 900s outcomes are counted as catastrophic."
    return {**base, **report, "valid_cohorts": valid, "integrity": integrity, "interpretation": note}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact-root", type=Path, default=collect.ARTIFACT_ROOT)
    args = ap.parse_args(argv)
    report = run_analysis(args.artifact_root)
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    out = args.artifact_root / "rejection-filter-v1-analysis-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    print(f"classification={report['classification']}")
    for k in ("reason", "integrity", "interpretation"):
        if report.get(k):
            print(f"{k}={report[k]}")
    for name in ("support_checks", "effect_checks", "effect_values"):
        for k, v in (report.get(name) or {}).items():
            print(f"{name.upper()} {k}={v}")
    print(f"report={out}")
    return 0 if report["classification"] in (KEEP, KILL) else 2


if __name__ == "__main__":
    raise SystemExit(main())
