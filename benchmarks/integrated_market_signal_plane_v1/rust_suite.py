from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from benchmarks.commodity_signal_plane_v0.benchmark import (
    TraceRecord,
    generate_synthetic_trace,
    load_trace,
)
from benchmarks.integrated_market_signal_plane_v1.indexed_kernel import IndexedWindowRadarState
from benchmarks.integrated_market_signal_plane_v1.suite import (
    HEADROOM_EPS,
    REPRESENTATIVE_EPS,
    RESEARCH_BUFFER,
    _fixed_arrivals,
    _percentile,
    _simulate_bounded_research_handoff,
    _simulate_single_worker,
    _trigger_snapshot,
)

VERSION = "rust_indexed_signal_plane_v0"
PASS_CLASSIFICATION = "PASS_RUST_INDEXED_SIGNAL_PLANE_V0"
SEMANTIC_FAIL_CLASSIFICATION = "FAIL_RUST_INDEXED_SIGNAL_PLANE_SEMANTICS"
CAPACITY_FAIL_CLASSIFICATION = "RUST_INDEXED_SIGNAL_PLANE_CAPACITY_INSUFFICIENT"


def _json_equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, float) and not math.isfinite(left):
            return left == right
        if isinstance(right, float) and not math.isfinite(right):
            return left == right
        return math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-9)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _json_equivalent(a, b) for a, b in zip(left, right)
        )
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equivalent(left[key], right[key]) for key in left
        )
    return left == right


def _service_report(service_s: list[float]) -> dict[str, float]:
    mean = sum(service_s) / len(service_s) if service_s else 0.0
    return {
        "mean_ms": mean * 1000.0,
        "p95_ms": _percentile(service_s, 95.0) * 1000.0,
        "p99_ms": _percentile(service_s, 99.0) * 1000.0,
        "capacity_eps_from_mean": 1.0 / mean if mean > 0 else math.inf,
    }


def _python_indexed_oracle(
    records: tuple[TraceRecord, ...],
) -> tuple[dict[int, dict | None], list[float], IndexedWindowRadarState]:
    state = IndexedWindowRadarState()
    decisions: dict[int, dict | None] = {}
    service_s: list[float] = []
    for record in records:
        started = time.perf_counter_ns()
        trigger = state.ingest(record)
        service_s.append((time.perf_counter_ns() - started) / 1_000_000_000.0)
        if record.kind == "trade":
            decisions[record.sequence] = _trigger_snapshot(trigger)
    return decisions, service_s, state


def _run_rust(
    *,
    cargo: str,
    manifest: Path,
    trace: Path,
    output: Path,
) -> dict[str, Any]:
    command = [
        cargo,
        "run",
        "--quiet",
        "--release",
        "--manifest-path",
        str(manifest),
        "--bin",
        "rust-indexed-signal-plane-v0",
        "--",
        "--trace",
        str(trace),
        "--out",
        str(output),
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Rust indexed signal runner failed "
            f"(exit={completed.returncode}).\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-4000:]}"
        )
    return json.loads(output.read_text(encoding="utf-8"))


def run_rust_indexed_signal_plane_v0(
    *,
    events: int,
    seed: int,
    cargo: str = "cargo",
) -> dict[str, Any]:
    if events <= 0:
        raise ValueError("events must be positive")

    manifest = (
        Path(__file__).resolve().parent
        / "rust_runner"
        / "Cargo.toml"
    )

    with tempfile.TemporaryDirectory(prefix="rust-indexed-signal-v0-") as directory:
        root = Path(directory)
        trace_path = root / "trace.jsonl"
        rust_output = root / "rust-report.json"

        generate_synthetic_trace(out=trace_path, events=events, seed=seed)
        _, records = load_trace(trace_path)

        python_decisions, python_service_s, python_state = _python_indexed_oracle(records)
        rust = _run_rust(
            cargo=cargo,
            manifest=manifest,
            trace=trace_path,
            output=rust_output,
        )

    rust_decisions = {
        int(item["sequence"]): item.get("trigger")
        for item in rust.get("decisions", [])
    }

    all_sequences = sorted(set(python_decisions) | set(rust_decisions))
    mismatches = []
    for sequence in all_sequences:
        expected = python_decisions.get(sequence)
        actual = rust_decisions.get(sequence)
        if not _json_equivalent(expected, actual):
            mismatches.append(
                {
                    "sequence": sequence,
                    "python": expected,
                    "rust": actual,
                }
            )

    exact_matches = len(all_sequences) - len(mismatches)
    parity_pct = (
        100.0
        if not all_sequences
        else 100.0 * exact_matches / len(all_sequences)
    )

    rust_service_s = [
        int(value) / 1_000_000_000.0 for value in rust.get("service_ns", [])
    ]
    if len(rust_service_s) != len(records):
        raise RuntimeError(
            f"Rust service sample count mismatch: {len(rust_service_s)} != {len(records)}"
        )

    scenarios: dict[str, Any] = {}
    for name, eps in (
        ("representative_5k", REPRESENTATIVE_EPS),
        ("headroom_7_5k", HEADROOM_EPS),
    ):
        arrivals = _fixed_arrivals(len(records), eps)
        queue = _simulate_single_worker(arrivals, rust_service_s)
        research = _simulate_bounded_research_handoff(
            queue["completion_times_s"],
            buffer=RESEARCH_BUFFER,
        )
        scenarios[name] = {
            "eps": eps,
            "rust_queue": {
                key: value
                for key, value in queue.items()
                if key != "completion_times_s"
            },
            "research_handoff": research,
        }

    python_service = _service_report(python_service_s)
    rust_service = _service_report(rust_service_s)
    speedup = (
        python_service["mean_ms"] / rust_service["mean_ms"]
        if rust_service["mean_ms"] > 0
        else math.inf
    )

    checks = {
        "detector_parity_100": parity_pct == 100.0 and not mismatches,
        "late_chain_time_insert_parity": (
            int(rust.get("late_chain_time_inserts", -1))
            == python_state.late_chain_time_inserts
        ),
        "rust_5k_no_backlog": (
            scenarios["representative_5k"]["rust_queue"]["backlog_at_source_end"]
            == 0
        ),
        "rust_7_5k_no_backlog": (
            scenarios["headroom_7_5k"]["rust_queue"]["backlog_at_source_end"]
            == 0
        ),
        "research_5k_zero_drop": (
            scenarios["representative_5k"]["research_handoff"]["dropped"] == 0
        ),
        "research_7_5k_zero_drop": (
            scenarios["headroom_7_5k"]["research_handoff"]["dropped"] == 0
        ),
    }

    if not checks["detector_parity_100"] or not checks["late_chain_time_insert_parity"]:
        classification = SEMANTIC_FAIL_CLASSIFICATION
        interpretation = (
            "Rust is rejected regardless of speed because frozen Radar semantics diverged."
        )
    elif all(checks.values()):
        classification = PASS_CLASSIFICATION
        interpretation = (
            "Rust preserves the frozen indexed Radar semantics and clears both 5k and 7.5k "
            "single-kernel capacity gates. It is eligible for live shadow evaluation only."
        )
    else:
        classification = CAPACITY_FAIL_CLASSIFICATION
        interpretation = (
            "Rust semantics match, but the frozen synthetic capacity gates still fail. "
            "Do not migrate the live Signal Plane yet."
        )

    return {
        "type": "rust_indexed_signal_plane_report",
        "version": VERSION,
        "record_count": len(records),
        "trade_decision_points": len(all_sequences),
        "detector_parity": {
            "exact_matches": exact_matches,
            "mismatches": len(mismatches),
            "parity_pct": parity_pct,
            "first_mismatches": mismatches[:10],
        },
        "late_chain_time_inserts": {
            "python": python_state.late_chain_time_inserts,
            "rust": rust.get("late_chain_time_inserts"),
        },
        "service": {
            "python_indexed": python_service,
            "rust_indexed": rust_service,
            "rust_speedup_vs_python_mean": speedup,
            "rust_wall_ms_including_json_loop": int(rust.get("wall_ns", 0))
            / 1_000_000.0,
        },
        "scenarios": scenarios,
        "checks": checks,
        "classification": classification,
        "interpretation": interpretation,
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "authorization": "research_only_no_v68_no_live_execution",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Rust indexed Signal Plane against the Python indexed Radar oracle. "
            "Semantic parity gates capacity: speed never rescues a mismatch."
        )
    )
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/integrated_market_signal_plane_v1/"
            "rust-indexed-report.json"
        ),
    )
    args = parser.parse_args()

    report = run_rust_indexed_signal_plane_v0(
        events=args.events,
        seed=args.seed,
        cargo=args.cargo,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
