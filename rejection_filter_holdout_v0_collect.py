"""Acquisition runner for ONE cohort (F1..F4) of Rejection Filter Prospective Holdout V0.

PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY. Route-only, read-only research: no private key, no
funded BUY, no order. It DOES make live provider calls (Solana WSS/RPC, Jupiter quotes) through the
accepted V7 Signal Plane -> Research Plane -> route-research bridge, so it requires an explicit
`--confirm-live-acquisition`.

Frozen contract: docs/rejection-filter-prospective-holdout-v0-preregistration-2026-09-29.md
(freeze commit 7384c94). This runner ONLY acquires and matures data. It computes no verdict, reads
no outcomes for classification, and changes no gate. Analysis is a separate step.

Behavior (fail-closed):
- protocol file hash must match the frozen SHA-256 (line endings normalized) or nothing runs;
- run key must be exactly `<FROZEN_BASE>-F<n>` for n in 1..4 and completely fresh in every table;
- cohorts run in order: F<n> requires a PASS acquisition report for F<n-1>;
- frozen parameters are fixed constants, not CLI flags;
- technical failure => INCONCLUSIVE report, the key is burned and must not be reused.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import route_research_signal_plane_bridge_v0 as bridge
from participant_quality_native_memory_v1 import (
    _schedule_audit,
    _strict_run_keys_fresh,
)
from src.config import settings
from src.route_research_forward_collection_900_v0 import (
    collect_route_research_forward_through_900_v0,
)

VERSION = "rejection_filter_holdout_v0_collect"
PROTOCOL_PATH = Path(
    "docs/rejection-filter-prospective-holdout-v0-preregistration-2026-09-29.md"
)
PROTOCOL_SHA256 = "f7c9a10e2fcd43e1dc5f05f2a0db4186c0fd4b1ea43f71954c3209add938961c"
FROZEN_BASE_RUN_KEY = "rejection-filter-v0-20260929-01"
COHORT_COUNT = 4

# Frozen acquisition parameters (protocol section 5). Not configurable.
ACQUISITION_DURATION_SECONDS = 120.0
MAX_EPISODES = 40
MIN_DECISIONS_PER_COHORT = 30
RESEARCH_NOTIONAL_USD = 25.0
RESEARCH_SLIPPAGE_BPS = 100
HAZARD_START_INTERVAL_MS = 650
ENTRY_START_INTERVAL_MS = 1000
EXIT_START_INTERVAL_MS = 250
FORWARD_PASS = "PASS_MEMORY_FORWARD_300_900_COMPLETE"

ARTIFACT_ROOT = Path("artifacts/rejection_filter_holdout_v0")
ACQ_PASS = "PASS_REJECTION_FILTER_HOLDOUT_V0_ACQUISITION"
ACQ_INCONCLUSIVE = "INCONCLUSIVE_REJECTION_FILTER_HOLDOUT_V0_ACQUISITION"
ACQ_NOT_FRESH = "FAIL_REJECTION_FILTER_HOLDOUT_V0_RUN_KEY_NOT_FRESH"


def protocol_hash(path: Path) -> str:
    """SHA-256 of the file with CRLF normalized to LF (Windows checkouts may convert endings)."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def verify_protocol(path: Path = PROTOCOL_PATH, expected: str = PROTOCOL_SHA256) -> None:
    if not path.is_file():
        raise SystemExit(f"Frozen protocol not found: {path}")
    actual = protocol_hash(path)
    if actual != expected:
        raise SystemExit(
            "Frozen protocol hash mismatch: refusing to acquire. "
            f"expected={expected} actual={actual}"
        )


def run_key_for(cohort: int) -> str:
    if cohort not in range(1, COHORT_COUNT + 1):
        raise ValueError(f"cohort must be 1..{COHORT_COUNT}")
    return f"{FROZEN_BASE_RUN_KEY}-F{cohort}"


def report_path(cohort: int, root: Path = ARTIFACT_ROOT) -> Path:
    return root / f"{run_key_for(cohort)}-acquisition-report.json"


def require_previous_cohort(cohort: int, root: Path = ARTIFACT_ROOT) -> None:
    if cohort == 1:
        return
    prev = report_path(cohort - 1, root)
    if not prev.is_file():
        raise SystemExit(f"F{cohort} requires the F{cohort - 1} acquisition report: {prev}")
    data = json.loads(prev.read_text(encoding="utf-8"))
    if data.get("classification") != ACQ_PASS:
        raise SystemExit(
            f"F{cohort - 1} did not PASS acquisition ({data.get('classification')}); "
            "no further cohorts are authorized by this runner."
        )


def _write(report: dict[str, Any], cohort: int, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    out = report_path(cohort, root)
    out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report["artifact"] = str(out)
    return report


def run_cohort(
    *, cohort: int, bootstrap_report: Path, artifact_root: Path = ARTIFACT_ROOT
) -> dict[str, Any]:
    run_key = run_key_for(cohort)
    base = {
        "type": "rejection_filter_holdout_v0_acquisition_report",
        "version": VERSION,
        "cohort": f"F{cohort}",
        "run_key": run_key,
        "protocol_sha256": PROTOCOL_SHA256,
        "no_verdict_computed": True,
        "scientific_thresholds_modified": False,
    }

    fresh, residue = _strict_run_keys_fresh((run_key,))
    if not fresh:
        # Nothing was written by this run; do not touch existing rows.
        return _write({**base, "classification": ACQ_NOT_FRESH, "residue": residue}, cohort, artifact_root)

    artifact_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== REJECTION FILTER HOLDOUT V0 F{cohort} ACQUISITION START {run_key} ===")
    bridge_report = asyncio.run(
        bridge.run_bridge(
            run_key=run_key,
            bootstrap_report=bootstrap_report,
            duration_seconds=ACQUISITION_DURATION_SECONDS,
            shadow_output=artifact_root / f"{run_key}-signal-plane-shadow.json",
            report_output=artifact_root / f"{run_key}-route-research-bridge.json",
            max_episodes=MAX_EPISODES,
            research_notional_usd=RESEARCH_NOTIONAL_USD,
            research_slippage_bps=RESEARCH_SLIPPAGE_BPS,
            hazard_start_interval_ms=HAZARD_START_INTERVAL_MS,
            entry_start_interval_ms=ENTRY_START_INTERVAL_MS,
        )
    )
    decisions, scheduled, exact_three = _schedule_audit(run_key)
    base.update(
        bridge_classification=bridge_report.get("classification"),
        decision_count=decisions,
        scheduled_count=scheduled,
        exact_three_horizons=exact_three,
    )
    if (
        bridge_report.get("classification") != bridge.PASS_CLASSIFICATION
        or decisions < MIN_DECISIONS_PER_COHORT
        or not exact_three
        or scheduled != decisions * 3
    ):
        return _write({**base, "classification": ACQ_INCONCLUSIVE, "failed_stage": "bridge_or_schedule"}, cohort, artifact_root)

    print(f"=== F{cohort} 300/900 MATURITY ===")
    forward = collect_route_research_forward_through_900_v0(
        acquisition_run_key=run_key,
        api_key=settings.jupiter_api_key,
        exit_start_interval_ms=EXIT_START_INTERVAL_MS,
    )
    base.update(
        forward_900_classification=forward.classification,
        forward_900_statuses=forward.statuses_target,
        target_lateness_p95_seconds=forward.target_lateness_p95_seconds,
    )
    if forward.classification != FORWARD_PASS:
        return _write({**base, "classification": ACQ_INCONCLUSIVE, "failed_stage": "forward_900_maturity"}, cohort, artifact_root)

    return _write({**base, "classification": ACQ_PASS}, cohort, artifact_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohort", type=int, required=True, choices=range(1, COHORT_COUNT + 1))
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument(
        "--confirm-live-acquisition",
        action="store_true",
        help="required: this makes live provider calls (Solana WSS/RPC, Jupiter quotes)",
    )
    args = parser.parse_args(argv)
    if not args.confirm_live_acquisition:
        raise SystemExit("Refusing to start: pass --confirm-live-acquisition (live provider calls).")
    verify_protocol()
    require_previous_cohort(args.cohort)
    report = run_cohort(cohort=args.cohort, bootstrap_report=args.bootstrap_report)
    print(f"classification={report['classification']} run_key={report['run_key']}")
    print(f"report={report.get('artifact')}")
    return 0 if report["classification"] == ACQ_PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
