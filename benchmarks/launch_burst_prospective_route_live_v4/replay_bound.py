from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_prospective_route_live_v3.live import EXPECTED_ROUTE_CONTRACT_HASH

BOUND_VERSION = "launch_burst_v4_watermark_capacity_bound_v0"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_V4_WATERMARK_CAPACITY_BOUND"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_V4_WATERMARK_CAPACITY_BOUND"
INCONCLUSIVE_CLASSIFICATION = "INCONCLUSIVE_LAUNCH_BURST_V4_WATERMARK_CAPACITY_BOUND"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _footer_stop_reason_counts(raw_dir: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(raw_dir.glob("chunk-*.jsonl")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("type") == "trace_footer":
                counts[str(row.get("stop_reason") or "UNKNOWN")] += 1
                break
    return counts


def run_bound(
    *,
    source_run: Path,
    capacity_replay_run: Path,
    rotation_seconds: float,
) -> dict[str, Any]:
    if rotation_seconds <= 0:
        raise ValueError("rotation_seconds must be positive")

    replay = _read_json(capacity_replay_run / "report.json")
    observations_payload = _read_json(capacity_replay_run / "systems-observations.json")
    observations = observations_payload.get("observations")
    if not isinstance(observations, list):
        raise ValueError("capacity replay systems-observations.json lacks observations list")

    contract_hash = str(replay.get("contract_hash_sha256") or "")
    metrics = replay.get("metrics") or {}
    service = metrics.get("total_service_ms") or {}
    max_service_ms = float(service.get("max") or 0.0)
    rotation_ms = float(rotation_seconds) * 1000.0
    conservative_dispatch_lag_ms = rotation_ms + max_service_ms

    stop_reason_counts = _footer_stop_reason_counts(source_run / "raw-chunks")
    size_rotations = int(stop_reason_counts.get("chunk_rotation", 0))

    selected = [
        item
        for item in observations
        if isinstance(item, dict) and item.get("selected") is True
    ]
    before_ready = 0
    before_deadline = 0
    details: list[dict[str, Any]] = []
    for item in selected:
        cutoff_ns = int(item["decision_cutoff_wall_ns"])
        entry_ready_at = int(item["entry_ready_at"])
        entry_deadline_at = int(item["entry_deadline_at"])
        worst_freeze_ns = cutoff_ns + int(round(conservative_dispatch_lag_ms * 1_000_000.0))
        meet_ready = worst_freeze_ns <= entry_ready_at * 1_000_000_000
        meet_deadline = worst_freeze_ns <= entry_deadline_at * 1_000_000_000
        before_ready += int(meet_ready)
        before_deadline += int(meet_deadline)
        details.append(
            {
                "token_mint": item.get("token_mint"),
                "decision_cutoff_wall_ns": cutoff_ns,
                "entry_ready_at": entry_ready_at,
                "entry_deadline_at": entry_deadline_at,
                "conservative_freeze_wall_ns": worst_freeze_ns,
                "conservative_dispatch_lag_ms": conservative_dispatch_lag_ms,
                "would_meet_entry_ready": meet_ready,
                "would_meet_entry_deadline": meet_deadline,
            }
        )

    missed_ready = len(selected) - before_ready
    missed_deadline = len(selected) - before_deadline
    gates = {
        "contract_hash_unchanged": contract_hash == EXPECTED_ROUTE_CONTRACT_HASH,
        "source_replay_provider_calls_disabled": replay.get("provider_calls_enabled") is False,
        "source_replay_economic_outcomes_closed": replay.get("economic_outcomes_opened") is False,
        "selected_observed": len(selected) > 0,
        "historical_size_rotations_zero": size_rotations == 0,
        "max_service_lt_rotation_interval": max_service_ms < rotation_ms,
        "conservative_selected_missed_deadline_zero": missed_deadline == 0,
    }

    if not gates["historical_size_rotations_zero"] or not gates["max_service_lt_rotation_interval"]:
        classification = INCONCLUSIVE_CLASSIFICATION
    else:
        classification = PASS_CLASSIFICATION if all(gates.values()) else FAIL_CLASSIFICATION

    return {
        "type": BOUND_VERSION,
        "classification": classification,
        "contract_hash_sha256": contract_hash,
        "provider_calls_enabled": False,
        "economic_outcomes_opened": False,
        "source_run": str(source_run.resolve()),
        "capacity_replay_run": str(capacity_replay_run.resolve()),
        "assumptions": {
            "rotation_seconds": rotation_seconds,
            "bound_formula": "rotation_interval_ms + observed_max_chunk_service_ms",
            "requires_historical_size_rotations_zero": True,
            "requires_observed_max_service_below_rotation_interval": True,
            "live_systems_only_remains_authoritative": True,
        },
        "source_footer_stop_reason_counts": dict(sorted(stop_reason_counts.items())),
        "observed_max_chunk_service_ms": max_service_ms,
        "conservative_dispatch_lag_ms": conservative_dispatch_lag_ms,
        "selected_count": len(selected),
        "selected_before_entry_ready": before_ready,
        "selected_missed_entry_ready": missed_ready,
        "selected_before_deadline": before_deadline,
        "selected_missed_deadline": missed_deadline,
        "gates": gates,
        "selected_details": details,
        "interpretation": (
            "This is a conservative offline engineering bound, not an economic result and not a substitute "
            "for the V4 systems-only live gate. When the historical run had no size-triggered extra rotations "
            "and every observed chunk service time was shorter than the 1s timer interval, a V4 periodic "
            "watermark cannot accumulate timer-induced queue backlog under the measured workload. The bound "
            "charges every selected snapshot a full timer interval plus the single worst observed chunk service."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Conservative offline capacity bound for Launch Burst V4 watermarks")
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--capacity-replay-run", type=Path, required=True)
    parser.add_argument("--rotation-seconds", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_bound(
            source_run=args.source_run,
            capacity_replay_run=args.capacity_replay_run,
            rotation_seconds=args.rotation_seconds,
        )
    except Exception as exc:
        print(json.dumps({"classification": FAIL_CLASSIFICATION, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
