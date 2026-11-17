from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any

from benchmarks.launch_burst_prospective_route_live_v3.live import (
    DEFAULT_CONTRACT,
    EXPECTED_ROUTE_CONTRACT_HASH,
    OnlinePumpFeatureState,
    _build_decoder,
    _distribution,
    _process_chunk,
    _read_json,
    _dispatch_timing,
)
from src.launch_burst_route_paper_v2 import selection_decision, validate_contract

REPLAY_VERSION = "launch_burst_prospective_route_capacity_replay_v3"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_ROUTE_CAPACITY_REPLAY_V3"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_ROUTE_CAPACITY_REPLAY_V3"
FAIL_CAPACITY = "FAIL_PROCESSING_CAPACITY_REPLAY_V3"
DEFAULT_OUTPUT_ROOT = Path("artifacts") / REPLAY_VERSION


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _trace_finalized_wall_ns(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and row.get("type") == "trace_footer":
            value = row.get("finalized_wall_ns")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
            raise ValueError(f"trace footer lacks finalized_wall_ns: {path}")
    raise ValueError(f"trace footer not found: {path}")


def _default_decoder_target() -> Path:
    configured = os.environ.get("LAUNCH_BURST_V3_DECODER_TARGET_DIR", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
        return Path(drive + "\\lbv3-decoder")
    return DEFAULT_OUTPUT_ROOT / "_decoder-build"


def _simulate_schedule(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: (int(item["finalized_wall_ns"]), str(item["chunk"])))
    previous_finish_ns: int | None = None
    output: list[dict[str, Any]] = []
    for item in ordered:
        arrival_ns = int(item["finalized_wall_ns"])
        service_ms = max(0.0, float(item["service_ms"]))
        start_ns = max(arrival_ns, previous_finish_ns or arrival_ns)
        finish_ns = start_ns + int(round(service_ms * 1_000_000.0))
        output.append(
            {
                **item,
                "simulated_start_wall_ns": start_ns,
                "simulated_finish_wall_ns": finish_ns,
                "simulated_queue_wait_ms": max(0.0, (start_ns - arrival_ns) / 1_000_000.0),
            }
        )
        previous_finish_ns = finish_ns
    return output


def _max_pending_depth(schedule: list[dict[str, Any]]) -> int:
    maximum = 0
    for index, item in enumerate(schedule):
        arrival = int(item["finalized_wall_ns"])
        pending = sum(
            1
            for previous in schedule[:index]
            if int(previous["simulated_finish_wall_ns"]) > arrival
        )
        maximum = max(maximum, pending)
    return maximum


def run_replay(
    *,
    source_run: Path,
    contract_path: Path,
    output_root: Path,
    cargo: str,
    decoder_target_dir: Path,
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    validate_contract(contract)
    if contract.get("contract_hash_sha256") != EXPECTED_ROUTE_CONTRACT_HASH:
        raise ValueError("route-paper contract hash changed; replay refuses to proceed")

    raw_dir = source_run / "raw-chunks"
    if not raw_dir.is_dir():
        raise ValueError(f"raw-chunks directory not found: {raw_dir}")
    raw_paths = sorted(raw_dir.glob("chunk-*.jsonl"))
    if not raw_paths:
        raise ValueError(f"no raw chunks found: {raw_dir}")

    run_id = f"{REPLAY_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    run_dir = output_root / run_id
    processed_root = run_dir / "processed-chunks"
    processed_root.mkdir(parents=True, exist_ok=False)

    decoder_build = _build_decoder(cargo=cargo, target_dir=decoder_target_dir)
    decoder_binary = Path(str(decoder_build["binary"]))

    chunk_records: list[dict[str, Any]] = []
    processing_errors: list[str] = []
    for raw_path in raw_paths:
        finalized_ns = _trace_finalized_wall_ns(raw_path)
        report = _process_chunk(
            raw_path=raw_path,
            processed_root=processed_root,
            decoder_binary=decoder_binary,
            finalized_wall_ns=finalized_ns,
            queue_depth_at_start=0,
        )
        telemetry = report.get("telemetry") or {}
        chunk_records.append(
            {
                "chunk": raw_path.stem,
                "finalized_wall_ns": finalized_ns,
                "service_ms": float(telemetry.get("total_service_ms") or 0.0),
                "reducer_service_ms": float(telemetry.get("reducer_service_ms") or 0.0),
                "decoder_service_ms": float(telemetry.get("decoder_service_ms") or 0.0),
                "status": report.get("status"),
            }
        )
        if report.get("status") == "FAILED":
            processing_errors.append(str(report.get("error") or f"{raw_path.stem}:FAILED"))

    schedule = _simulate_schedule(chunk_records)
    schedule_by_chunk = {str(item["chunk"]): item for item in schedule}

    online = OnlinePumpFeatureState()
    observations: list[dict[str, Any]] = []
    for raw_path in raw_paths:
        item = schedule_by_chunk[raw_path.stem]
        chunk_dir = processed_root / raw_path.stem
        if item.get("status") != "FAILED":
            online.ingest_processed_chunk(chunk_dir)
        finalized_ns = int(item["finalized_wall_ns"])
        simulated_finish_ns = int(item["simulated_finish_wall_ns"])
        for token_mint, snapshot in online.ready_snapshots(
            coverage_through_wall_ns=finalized_ns
        ):
            admitted, reason = selection_decision(snapshot, contract)
            timing = _dispatch_timing(
                snapshot=snapshot,
                contract=contract,
                snapshot_frozen_wall_ns=simulated_finish_ns,
            )
            observations.append(
                {
                    **timing,
                    "token_mint": token_mint,
                    "selected": bool(admitted),
                    "selection_reason": reason,
                    "provider_calls_enabled": False,
                    "economic_outcome_opened": False,
                }
            )

    selected = [item for item in observations if item["selected"]]
    selected_before_ready = sum(1 for item in selected if item["would_meet_entry_ready"])
    selected_before_deadline = sum(1 for item in selected if item["would_meet_entry_deadline"])
    selected_missed_deadline = len(selected) - selected_before_deadline

    service_values = [float(item["service_ms"]) for item in schedule]
    reducer_values = [float(item["reducer_service_ms"]) for item in schedule]
    decoder_values = [float(item["decoder_service_ms"]) for item in schedule]
    queue_wait_values = [float(item["simulated_queue_wait_ms"]) for item in schedule]
    dispatch_lags = [float(item["snapshot_dispatch_lag_ms"]) for item in observations]

    last_arrival = max(int(item["finalized_wall_ns"]) for item in schedule)
    last_finish = max(int(item["simulated_finish_wall_ns"]) for item in schedule)
    replay_metrics = {
        "chunk_count": len(schedule),
        "total_service_ms": _distribution(service_values),
        "reducer_service_ms": _distribution(reducer_values),
        "decoder_service_ms": _distribution(decoder_values),
        "simulated_queue_wait_ms": _distribution(queue_wait_values),
        "simulated_max_pending_depth": _max_pending_depth(schedule),
        "simulated_tail_backlog_ms": max(0.0, (last_finish - last_arrival) / 1_000_000.0),
        "snapshot_dispatch_lag_ms": _distribution(dispatch_lags),
        "snapshot_count": len(observations),
        "selected_count": len(selected),
        "selected_before_entry_ready": selected_before_ready,
        "selected_before_deadline": selected_before_deadline,
        "selected_missed_deadline": selected_missed_deadline,
    }
    gates = {
        "contract_hash_unchanged": contract.get("contract_hash_sha256") == EXPECTED_ROUTE_CONTRACT_HASH,
        "decoder_built_once": decoder_build.get("invocations") == 1,
        "decoder_binary_exists": decoder_build.get("binary_exists") is True,
        "processing_errors_zero": not processing_errors,
        "selected_observed": len(selected) > 0,
        "selected_missed_deadline_zero": selected_missed_deadline == 0,
        "provider_calls_disabled": True,
        "economic_outcomes_closed": True,
    }
    if selected_missed_deadline > 0 and all(
        value for key, value in gates.items() if key != "selected_missed_deadline_zero"
    ):
        classification = FAIL_CAPACITY
    else:
        classification = PASS_CLASSIFICATION if all(gates.values()) else FAIL_CLASSIFICATION

    report = {
        "type": "launch_burst_route_capacity_replay_report_v3",
        "version": REPLAY_VERSION,
        "classification": classification,
        "source_run": str(source_run.resolve()),
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "provider_calls_enabled": False,
        "economic_outcomes_opened": False,
        "decoder_build": decoder_build,
        "processing_errors": processing_errors,
        "metrics": replay_metrics,
        "gates": gates,
        "interpretation": (
            "Offline replay uses historical raw market chunks only to test processing capacity under their "
            "original chunk-arrival clocks. It opens no provider/economic outcomes and does not validate or "
            "retune the frozen trading hypothesis. Live systems-only remains the authoritative capacity gate."
        ),
    }
    _write_json(run_dir / "report.json", report)
    _write_json(run_dir / "schedule.json", {"chunks": schedule})
    _write_json(run_dir / "systems-observations.json", {"observations": observations})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline capacity replay of the Launch Burst V3 hot path using frozen raw chunks"
    )
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_replay(
            source_run=args.source_run,
            contract_path=args.contract,
            output_root=args.output_root,
            cargo=args.cargo,
            decoder_target_dir=args.decoder_target_dir or _default_decoder_target(),
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": FAIL_CLASSIFICATION,
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
