from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_candidate_parity_v0.run import run_candidate_parity_v0
from benchmarks.launch_burst_coverage_audit_v0.run import run_coverage_audit
from benchmarks.launch_burst_matched_unit_coverage_v0.run import (
    run_matched_unit_coverage_audit,
)
from benchmarks.launch_burst_run_inventory_v0.run import (
    select_latest_closed_launch_run_key,
)
from benchmarks.market_first_live_discovery_v0.run import DEFAULT_ARTIFACTS_ROOT
from src.launch_burst_source_capabilities_v0 import (
    build_launch_burst_source_capabilities_v0,
)


READINESS_VERSION = "launch_burst_readiness_v0_outcome_blind_candidate_parity"


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def find_live_report_for_run(
    *,
    acquisition_run_key: str,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
) -> Path:
    key = str(acquisition_run_key).strip()
    if not key:
        raise ValueError("acquisition_run_key cannot be empty")
    root = Path(artifacts_root)
    if not root.exists():
        raise ValueError(f"live discovery artifacts root not found: {root}")

    matches: list[Path] = []
    for path in root.rglob("report.json"):
        try:
            payload = _json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        run = payload.get("run") or {}
        if str(run.get("acquisition_run_key") or "") != key:
            continue
        if run.get("status") != "CLOSED":
            continue
        if payload.get("valid_live_discovery") is not True:
            continue
        matches.append(path)

    matches.sort(key=lambda item: str(item.resolve()))
    if not matches:
        raise RuntimeError(
            "no valid CLOSED live discovery report found for acquisition_run_key=" + key
        )
    if len(matches) != 1:
        raise RuntimeError(
            "multiple valid live discovery reports found for the same acquisition run: "
            + ",".join(str(item) for item in matches[:10])
        )
    return matches[0]


def run_launch_burst_readiness_v0(
    *,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
    window_seconds: int = 30,
) -> dict[str, Any]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")

    run_key = select_latest_closed_launch_run_key()
    live_report = find_live_report_for_run(
        acquisition_run_key=run_key,
        artifacts_root=artifacts_root,
    )
    candidate_parity = run_candidate_parity_v0(
        acquisition_run_key=run_key,
        live_report_path=live_report,
    )
    db_coverage = run_coverage_audit(
        acquisition_run_key=run_key,
        window_seconds=window_seconds,
    )
    matched_coverage = run_matched_unit_coverage_audit(
        live_report_path=live_report,
        window_seconds=window_seconds,
    )
    capabilities = build_launch_burst_source_capabilities_v0().as_dict()

    candidate_parity_exact = candidate_parity.get("exact_match") is True
    complete_snapshots = int(db_coverage["sample"]["complete_snapshot_count"])
    nonempty_snapshots = int(db_coverage["sample"]["nonempty_snapshot_count"])
    matched_complete = int(matched_coverage["launch_sample"]["complete_anchor_count"])
    adapted = int(matched_coverage["trade_adaptation"]["adapted_count"])

    blockers: list[str] = []
    if not candidate_parity_exact:
        blockers.append("candidate_anchor_ledger_parity_failed")
    if int(candidate_parity["diagnostics"]["same_second_multi_candidate_count"]) > 0:
        blockers.append("same_second_lifecycle_candidates_require_exact_receive_order_audit")
    if complete_snapshots == 0:
        blockers.append("no_complete_launch_burst_snapshot_in_selected_closed_run")
    if nonempty_snapshots == 0:
        blockers.append("no_nonempty_launch_burst_snapshot_in_selected_closed_run")
    if matched_complete == 0:
        blockers.append("no_complete_raw_evidence_launch_anchor_in_selected_closed_run")
    if adapted == 0:
        blockers.append("no_causally_adapted_matched_unit_trade_in_selected_closed_run")
    blockers.extend(str(item) for item in capabilities.get("blockers", ()))

    feature_research_ready = bool(
        candidate_parity_exact and complete_snapshots > 0 and nonempty_snapshots > 0
    )
    matched_unit_research_ready = bool(
        candidate_parity_exact and matched_complete > 0 and adapted > 0
    )
    economic_outcome_ready = bool(
        candidate_parity_exact and capabilities.get("economic_outcome_ready")
    )

    if not candidate_parity_exact:
        classification = "CANDIDATE_LEDGER_PARITY_FAILED"
    elif not feature_research_ready:
        classification = "NEEDS_MORE_OR_BETTER_LAUNCH_SAMPLE"
    elif not matched_unit_research_ready:
        classification = "CORE_FEATURES_READY_MATCHED_UNIT_NOT_READY"
    elif not economic_outcome_ready:
        classification = "FEATURE_RESEARCH_READY_ECONOMIC_OUTCOME_BLOCKED"
    else:
        classification = "READY_FOR_FROZEN_OUTCOME_PROTOCOL"

    return {
        "type": "launch_burst_readiness",
        "version": READINESS_VERSION,
        "classification": classification,
        "acquisition_run_key": run_key,
        "source_live_report": str(live_report),
        "window_seconds": window_seconds,
        "readiness": {
            "candidate_ledger_parity_ready": candidate_parity_exact,
            "feature_research_ready": feature_research_ready,
            "matched_unit_research_ready": matched_unit_research_ready,
            "economic_outcome_ready": economic_outcome_ready,
            "automatic_trade_ready": False,
        },
        "blockers": list(dict.fromkeys(blockers)),
        "candidate_parity": candidate_parity,
        "db_coverage": db_coverage,
        "matched_unit_coverage": matched_coverage,
        "source_capabilities": capabilities,
        "scientific_lock": {
            "coverage_only": True,
            "candidate_parity_required": True,
            "economic_outcomes_loaded": False,
            "future_outcomes_reported": False,
            "return_values_reported": False,
            "candidate_thresholds_defined": False,
            "outcome_horizons_frozen": False,
            "automatic_buy_sell_decision": False,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Outcome-blind Launch Burst readiness gate for the latest closed acquisition"
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=DEFAULT_ARTIFACTS_ROOT,
    )
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/launch_burst_readiness_v0/report.json"),
    )
    args = parser.parse_args()
    result = run_launch_burst_readiness_v0(
        artifacts_root=args.artifacts_root,
        window_seconds=args.window_seconds,
    )
    _write_json(args.output, result)
    print(
        f"Launch Burst Readiness V0 classification={result['classification']} "
        f"run={result['acquisition_run_key']}"
    )
    print(f"readiness={result['readiness']}")
    print(f"blockers={result['blockers']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
