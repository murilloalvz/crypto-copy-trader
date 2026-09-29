"""Acquisition runner for Rejection Filter Prospective Holdout V1 (one cohort per invocation).

PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY. Makes live provider calls (Solana WSS/RPC, Jupiter
quotes) through the accepted V7 bridge; requires `--confirm-live-acquisition`. Computes no verdict.

Protocol: docs/rejection-filter-prospective-holdout-v1-preregistration-2026-09-29.md. The hash
constant below is None until the owner freezes the protocol and records its SHA-256; while None (or
on mismatch, or if the frozen file is missing) NOTHING runs.

Differences from V0 (acquisition quality only; hypothesis, rule and gates unchanged):
- fail-closed pre-flight BEFORE any data is created (env, RPC host, Jupiter key, bootstrap age);
- error taxonomy and cohort technical validity computed from statuses/timing only, never returns;
- pre-reserved replacements G5, G6 for DEGRADED cohorts; the runner chooses the next label itself.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import route_research_signal_plane_bridge_v0 as bridge
from participant_quality_native_memory_v1 import _schedule_audit, _strict_run_keys_fresh
from rejection_filter_holdout_v0_collect import console_guards, protocol_hash
from src.config import settings
from src.opportunity_route_research_store import load_route_research_outcomes
from src.route_research_forward_collection_900_v0 import collect_route_research_forward_through_900_v0

VERSION = "rejection_filter_holdout_v1_collect"
PROTOCOL_PATH = Path("docs/rejection-filter-prospective-holdout-v1-preregistration-2026-09-29.md")
PROTOCOL_SHA256: str | None = None  # set to the frozen file's SHA-256 (CRLF-normalized) at freeze
BASE_RUN_KEY = "rejection-filter-v1-20260929-01"
LABELS = ("G1", "G2", "G3", "G4", "G5", "G6")  # G5, G6 = pre-reserved replacements
VALID_COHORTS_REQUIRED = 4
MAX_DEGRADED = 2

LATENESS_CAP_SECONDS = 60
DEGRADED_THRESHOLD = 0.20
BOOTSTRAP_MAX_AGE_SECONDS = 24 * 3600
BOOTSTRAP_PASS = "PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0"
PUBLIC_RPC_HOSTS = ("api.mainnet.solana.com", "api.mainnet-beta.solana.com")

# Frozen acquisition parameters (same as V0 / Participant Quality). Not configurable.
ACQUISITION_DURATION_SECONDS = 120.0
MAX_EPISODES = 40
MIN_DECISIONS_PER_COHORT = 30
RESEARCH_NOTIONAL_USD = 25.0
RESEARCH_SLIPPAGE_BPS = 100
HAZARD_START_INTERVAL_MS = 650
ENTRY_START_INTERVAL_MS = 1000
EXIT_START_INTERVAL_MS = 250
FORWARD_PASS = "PASS_MEMORY_FORWARD_300_900_COMPLETE"

ARTIFACT_ROOT = Path("artifacts/rejection_filter_holdout_v1")
ACQ_DONE = "ACQUISITION_COMPLETE"
VALID = "VALID"
DEGRADED = "DEGRADED"
NOT_FRESH = "FAIL_REJECTION_FILTER_HOLDOUT_V1_RUN_KEY_NOT_FRESH"


# ------------------------------------------------------------------ pure helpers
def run_key_for(label: str) -> str:
    if label not in LABELS:
        raise ValueError(f"unknown cohort label {label}")
    return f"{BASE_RUN_KEY}-{label}"


def report_path(label: str, root: Path = ARTIFACT_ROOT) -> Path:
    return root / f"{run_key_for(label)}-acquisition-report.json"


def verify_protocol(path: Path = PROTOCOL_PATH, expected: str | None = None) -> None:
    expected = PROTOCOL_SHA256 if expected is None else expected
    if not expected:
        raise SystemExit("V1 protocol is not frozen yet (no SHA-256 recorded): refusing to acquire.")
    if not path.is_file():
        raise SystemExit(f"Frozen V1 protocol not found: {path}")
    actual = protocol_hash(path)
    if actual != expected:
        raise SystemExit(f"Frozen protocol hash mismatch. expected={expected} actual={actual}")


def classify_outcome(status: str, error_type: str | None, error_message: str | None,
                     target_at: int | None, observed_at: int | None) -> str:
    """AVAILABLE_ON_TIME | LATE | STRUCTURAL | TECHNICAL | PENDING. Timing/status only."""
    if status == "AVAILABLE":
        if observed_at is None or target_at is None:
            return "TECHNICAL"
        return "AVAILABLE_ON_TIME" if observed_at - target_at <= LATENESS_CAP_SECONDS else "LATE"
    if status == "PENDING":
        return "PENDING"
    msg = f"{error_type or ''} {error_message or ''}"
    if re.search(r"HTTP 400", msg) and re.search(r"Failed to get quotes", msg, re.I):
        return "STRUCTURAL"  # no route: legitimate missing outcome, never triggers replacement
    return "TECHNICAL"  # 429, 5xx, timeouts, transport, unknown: conservative


def assess_cohort(outcomes_900: list[dict[str, Any]], decisions: int) -> dict[str, Any]:
    counts = {k: 0 for k in ("AVAILABLE_ON_TIME", "LATE", "STRUCTURAL", "TECHNICAL", "PENDING")}
    for o in outcomes_900:
        counts[classify_outcome(o["status"], o.get("error_type"), o.get("error_message"),
                                o.get("target_at"), o.get("observed_at"))] += 1
    bad = counts["TECHNICAL"] + counts["LATE"] + counts["PENDING"]
    share = (bad / decisions) if decisions else 1.0
    return {"counts_900": counts, "technical_unusable_share": share,
            "cohort_validity": DEGRADED if (share > DEGRADED_THRESHOLD or decisions == 0) else VALID}


def study_state(root: Path = ARTIFACT_ROOT) -> dict[str, Any]:
    """Decide from existing reports what to do next. Raises SystemExit on a blocked state."""
    valid, degraded, used = [], [], []
    for label in LABELS:
        p = report_path(label, root)
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        used.append(label)
        if data.get("classification") == NOT_FRESH:
            raise SystemExit(f"{label}: run key was not fresh; owner action required (see report).")
        (valid if data.get("cohort_validity") == VALID else degraded).append(label)
    if len(valid) >= VALID_COHORTS_REQUIRED:
        return {"status": "COMPLETE", "valid": valid, "degraded": degraded, "next": None}
    if len(degraded) > MAX_DEGRADED:
        return {"status": "INCONCLUSIVE_ACQUISITION", "valid": valid, "degraded": degraded, "next": None}
    nxt = next((l for l in LABELS if l not in used), None)
    return {"status": "CONTINUE", "valid": valid, "degraded": degraded, "next": nxt}


def bootstrap_problem(path: Path, now: float | None = None) -> str | None:
    if not path.is_file():
        return f"bootstrap report not found: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("classification") != BOOTSTRAP_PASS or data.get("valid_bootstrap") is not True:
        return "bootstrap is not a valid PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0"
    ended = data.get("ended_at")
    if not isinstance(ended, (int, float)):
        return "bootstrap report has no ended_at"
    if (now if now is not None else time.time()) - float(ended) > BOOTSTRAP_MAX_AGE_SECONDS:
        return "bootstrap is older than 24 hours"
    return None


def preflight_problem(bootstrap_report: Path, now: float | None = None) -> str | None:
    if not settings.jupiter_api_key:
        return "JUPITER_API_KEY is not set (is python-dotenv installed / .env present?)"
    host = settings.rpc_url.split("?")[0].split("/")[2] if "//" in settings.rpc_url else settings.rpc_url
    if host in PUBLIC_RPC_HOSTS:
        return f"RPC host is the public default ({host}); configure the dedicated RPC"
    return bootstrap_problem(bootstrap_report, now)


# ------------------------------------------------------------------ runner
def _write(report: dict[str, Any], label: str, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    out = report_path(label, root)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    report["artifact"] = str(out)
    return report


def run_cohort(*, label: str, bootstrap_report: Path, artifact_root: Path = ARTIFACT_ROOT) -> dict[str, Any]:
    run_key = run_key_for(label)
    base = {"type": "rejection_filter_holdout_v1_acquisition_report", "version": VERSION,
            "cohort": label, "run_key": run_key, "protocol_sha256": PROTOCOL_SHA256,
            "no_verdict_computed": True, "scientific_thresholds_modified": False,
            "lateness_cap_seconds": LATENESS_CAP_SECONDS, "degraded_threshold": DEGRADED_THRESHOLD}
    fresh, residue = _strict_run_keys_fresh((run_key,))
    if not fresh:
        return _write({**base, "classification": NOT_FRESH, "cohort_validity": DEGRADED, "residue": residue},
                      label, artifact_root)

    artifact_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== REJECTION FILTER HOLDOUT V1 {label} ACQUISITION START {run_key} ===")
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
    problem = preflight_problem(args.bootstrap_report)
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
