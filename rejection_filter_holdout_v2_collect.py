"""Acquisition runner for Rejection Filter Prospective Holdout V2 (independent replication).

PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY. Live provider calls (Solana WSS/RPC, Jupiter quotes)
through the accepted V7 bridge; requires `--confirm-live-acquisition`. Computes no verdict.

Protocol: docs/rejection-filter-prospective-holdout-v2-replication-preregistration-2026-09-30.md.
`PROTOCOL_SHA256` is None until the owner freezes the protocol and records its SHA-256; while None
(or on mismatch / missing file) NOTHING runs.

V1 provenance is untouched: this module is new. Pure helpers that do not depend on study constants
(error taxonomy, cohort assessment, bootstrap/env checks, console guard) are reused from V1 and V0.
New in V2: five required VALID cohorts H1..H5 with reserved replacements H6, H7; UTC start-date
recording; day rules (never on the V1 collection days, at most three cohorts started per UTC day).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import route_research_signal_plane_bridge_v0 as bridge
import rejection_filter_holdout_v1_collect as v1
from participant_quality_native_memory_v1 import _schedule_audit, _strict_run_keys_fresh
from rejection_filter_holdout_v0_collect import console_guards, protocol_hash
from src.config import settings
from src.opportunity_route_research_store import load_route_research_outcomes
from src.route_research_forward_collection_900_v0 import collect_route_research_forward_through_900_v0

VERSION = "rejection_filter_holdout_v2_collect"
PROTOCOL_PATH = Path("docs/rejection-filter-prospective-holdout-v2-replication-preregistration-2026-09-30.md")
PROTOCOL_SHA256: str | None = "c775a1a38d056ab356f4128f8c6fddf5b61940ebf7f8bca7369f5482dba905a3"  # SHA-256 (CRLF-normalized) of the file frozen at 6e1c81457f1098cb69d99d08ec6c9f3e686152d5
BASE_RUN_KEY = "rejection-filter-v2-20260930-01"
LABELS = ("H1", "H2", "H3", "H4", "H5", "H6", "H7")  # H6, H7 = pre-reserved replacements
VALID_COHORTS_REQUIRED = 5
MAX_DEGRADED = 2
FORBIDDEN_UTC_DATES = frozenset({"2026-09-29", "2026-09-30"})  # V1 collection days
MAX_COHORTS_STARTED_PER_UTC_DAY = 3
MIN_DISTINCT_UTC_DAYS = 2

# Reused unchanged from V1 (same frozen values by design).
LATENESS_CAP_SECONDS = v1.LATENESS_CAP_SECONDS
DEGRADED_THRESHOLD = v1.DEGRADED_THRESHOLD
classify_outcome = v1.classify_outcome
assess_cohort = v1.assess_cohort
bootstrap_problem = v1.bootstrap_problem
preflight_problem = v1.preflight_problem
VALID, DEGRADED = v1.VALID, v1.DEGRADED

ACQUISITION_DURATION_SECONDS = v1.ACQUISITION_DURATION_SECONDS
MAX_EPISODES = v1.MAX_EPISODES
MIN_DECISIONS_PER_COHORT = v1.MIN_DECISIONS_PER_COHORT
RESEARCH_NOTIONAL_USD = v1.RESEARCH_NOTIONAL_USD
RESEARCH_SLIPPAGE_BPS = v1.RESEARCH_SLIPPAGE_BPS
HAZARD_START_INTERVAL_MS = v1.HAZARD_START_INTERVAL_MS
ENTRY_START_INTERVAL_MS = v1.ENTRY_START_INTERVAL_MS
EXIT_START_INTERVAL_MS = v1.EXIT_START_INTERVAL_MS
FORWARD_PASS = v1.FORWARD_PASS

ARTIFACT_ROOT = Path("artifacts/rejection_filter_holdout_v2")
ACQ_DONE = "ACQUISITION_COMPLETE"
NOT_FRESH = "FAIL_REJECTION_FILTER_HOLDOUT_V2_RUN_KEY_NOT_FRESH"


def utc_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def run_key_for(label: str) -> str:
    if label not in LABELS:
        raise ValueError(f"unknown cohort label {label}")
    return f"{BASE_RUN_KEY}-{label}"


def report_path(label: str, root: Path = ARTIFACT_ROOT) -> Path:
    return root / f"{run_key_for(label)}-acquisition-report.json"


def verify_protocol(path: Path = PROTOCOL_PATH, expected: str | None = None) -> None:
    expected = PROTOCOL_SHA256 if expected is None else expected
    if not expected:
        raise SystemExit("V2 protocol is not frozen yet (no SHA-256 recorded): refusing to acquire.")
    if not path.is_file():
        raise SystemExit(f"Frozen V2 protocol not found: {path}")
    actual = protocol_hash(path)
    if actual != expected:
        raise SystemExit(f"Frozen protocol hash mismatch. expected={expected} actual={actual}")


def read_reports(root: Path = ARTIFACT_ROOT) -> dict[str, dict[str, Any]]:
    out = {}
    for label in LABELS:
        p = report_path(label, root)
        if p.is_file():
            out[label] = json.loads(p.read_text(encoding="utf-8"))
    return out


def study_state(root: Path = ARTIFACT_ROOT) -> dict[str, Any]:
    reports = read_reports(root)
    valid, degraded = [], []
    for label, data in reports.items():
        if data.get("classification") == NOT_FRESH:
            raise SystemExit(f"{label}: run key was not fresh; owner action required (see report).")
        (valid if data.get("cohort_validity") == VALID else degraded).append(label)
    if len(valid) >= VALID_COHORTS_REQUIRED:
        return {"status": "COMPLETE", "valid": valid, "degraded": degraded, "next": None}
    if len(degraded) > MAX_DEGRADED:
        return {"status": "INCONCLUSIVE_ACQUISITION", "valid": valid, "degraded": degraded, "next": None}
    nxt = next((l for l in LABELS if l not in reports), None)
    return {"status": "CONTINUE", "valid": valid, "degraded": degraded, "next": nxt}


def day_problem(now: float, root: Path = ARTIFACT_ROOT) -> str | None:
    """Independence day rules, enforced BEFORE any data is created."""
    today = utc_date(now)
    if today in FORBIDDEN_UTC_DATES:
        return f"today ({today} UTC) is a V1 collection day; V2 cohorts must be collected on other days"
    started_today = sum(1 for d in read_reports(root).values() if d.get("started_utc_date") == today)
    if started_today >= MAX_COHORTS_STARTED_PER_UTC_DAY:
        return f"{started_today} cohorts already started today ({today} UTC); wait for the next UTC day"
    return None


def distinct_days_problem(reports: dict[str, dict[str, Any]], labels: list[str]) -> str | None:
    """Analysis-side check over the VALID cohorts."""
    days = [reports[l].get("started_utc_date") for l in labels]
    if any(d is None for d in days):
        return "a valid cohort has no recorded UTC start date"
    if any(d in FORBIDDEN_UTC_DATES for d in days):
        return "a valid cohort was collected on a V1 collection day"
    if len(set(days)) < MIN_DISTINCT_UTC_DAYS:
        return f"valid cohorts span {len(set(days))} UTC day(s); at least {MIN_DISTINCT_UTC_DAYS} required"
    if max(days.count(d) for d in set(days)) > MAX_COHORTS_STARTED_PER_UTC_DAY:
        return f"more than {MAX_COHORTS_STARTED_PER_UTC_DAY} valid cohorts on a single UTC day"
    return None


def _write(report: dict[str, Any], label: str, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    out = report_path(label, root)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    report["artifact"] = str(out)
    return report


def run_cohort(*, label: str, bootstrap_report: Path, artifact_root: Path = ARTIFACT_ROOT) -> dict[str, Any]:
    run_key = run_key_for(label)
    started = time.time()
    base = {"type": "rejection_filter_holdout_v2_acquisition_report", "version": VERSION,
            "cohort": label, "run_key": run_key, "protocol_sha256": PROTOCOL_SHA256,
            "started_at": int(started), "started_utc_date": utc_date(started),
            "no_verdict_computed": True, "scientific_thresholds_modified": False,
            "lateness_cap_seconds": LATENESS_CAP_SECONDS, "degraded_threshold": DEGRADED_THRESHOLD}
    fresh, residue = _strict_run_keys_fresh((run_key,))
    if not fresh:
        return _write({**base, "classification": NOT_FRESH, "cohort_validity": DEGRADED, "residue": residue},
                      label, artifact_root)

    artifact_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== REJECTION FILTER HOLDOUT V2 {label} ACQUISITION START {run_key} ===")
    bridge_report = asyncio.run(bridge.run_bridge(
        run_key=run_key, bootstrap_report=bootstrap_report, duration_seconds=ACQUISITION_DURATION_SECONDS,
        shadow_output=artifact_root / f"{run_key}-signal-plane-shadow.json",
        report_output=artifact_root / f"{run_key}-route-research-bridge.json",
        max_episodes=MAX_EPISODES, research_notional_usd=RESEARCH_NOTIONAL_USD,
        research_slippage_bps=RESEARCH_SLIPPAGE_BPS, hazard_start_interval_ms=HAZARD_START_INTERVAL_MS,
        entry_start_interval_ms=ENTRY_START_INTERVAL_MS))
    decisions, scheduled, exact_three = _schedule_audit(run_key)
    base.update(bridge_classification=bridge_report.get("classification"), decision_count=decisions,
                scheduled_count=scheduled, exact_three_horizons=exact_three)
    if (bridge_report.get("classification") != bridge.PASS_CLASSIFICATION or decisions < MIN_DECISIONS_PER_COHORT
            or not exact_three or scheduled != decisions * 3):
        return _write({**base, "classification": ACQ_DONE, "cohort_validity": DEGRADED,
                       "degraded_reason": "bridge_or_schedule_failure"}, label, artifact_root)

    print(f"=== {label} 300/900 MATURITY ===")
    forward = collect_route_research_forward_through_900_v0(
        acquisition_run_key=run_key, api_key=settings.jupiter_api_key, exit_start_interval_ms=EXIT_START_INTERVAL_MS)
    base.update(forward_900_classification=forward.classification, forward_900_statuses=forward.statuses_target,
                target_lateness_p95_seconds=forward.target_lateness_p95_seconds)
    if forward.classification != FORWARD_PASS:
        return _write({**base, "classification": ACQ_DONE, "cohort_validity": DEGRADED,
                       "degraded_reason": "forward_900_maturity_failure"}, label, artifact_root)

    rows = [{"status": o.status, "error_type": o.error_type, "error_message": o.error_message,
             "target_at": o.target_at, "observed_at": o.observed_at}
            for o in load_route_research_outcomes(acquisition_run_key=run_key) if o.horizon_seconds == 900]
    assessment = assess_cohort(rows, decisions)  # statuses and timing only; no return values read
    if assessment["cohort_validity"] == DEGRADED:
        assessment["degraded_reason"] = "technical_unusable_share_above_threshold"
    return _write({**base, "classification": ACQ_DONE, **assessment}, label, artifact_root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bootstrap-report", type=Path, required=True)
    ap.add_argument("--confirm-live-acquisition", action="store_true",
                    help="required: this makes live provider calls (Solana WSS/RPC, Jupiter quotes)")
    args = ap.parse_args(argv)
    if not args.confirm_live_acquisition:
        raise SystemExit("Refusing to start: pass --confirm-live-acquisition (live provider calls).")
    verify_protocol()
    state = study_state()
    if state["status"] != "CONTINUE":
        raise SystemExit(f"No further cohort to run: {state['status']} valid={state['valid']} degraded={state['degraded']}")
    problem = day_problem(time.time()) or preflight_problem(args.bootstrap_report)
    if problem:
        raise SystemExit(f"Pre-flight failed (nothing was created): {problem}")
    label = state["next"]
    with console_guards():
        report = run_cohort(label=label, bootstrap_report=args.bootstrap_report)
    print(f"cohort={label} classification={report['classification']} validity={report.get('cohort_validity')}")
    print(f"technical_unusable_share={report.get('technical_unusable_share')} report={report.get('artifact')}")
    return 0 if report.get("cohort_validity") == VALID else 2


if __name__ == "__main__":
    raise SystemExit(main())
