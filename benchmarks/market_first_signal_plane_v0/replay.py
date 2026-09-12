from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from typing import Any
from unittest.mock import patch

from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.market_first_capacity_harness_v0.run import (
    _load_identity_observations,
    _materialize_trace,
    _trace_paths,
)
from benchmarks.market_first_capacity_harness_v0.shadow_pumpswap_causal import (
    apply_recorded_identity_refresh_v0,
    load_recorded_identity_refresh_v0,
)
from benchmarks.market_first_capacity_harness_v0.shadow_result_gate import (
    _SIGNAL_PIPELINE_FIELDS,
    _signal_errors,
)
from benchmarks.market_first_capacity_harness_v0.shadow_signal_plane import (
    TriggerRecordingKernelV0,
    compare_trigger_ledgers_v0,
    process_canonical_chunk_shadow_signal_v0,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    seed_bootstrap_identities_v0,
)
from benchmarks.market_first_live_smoke_v0.run import _run_carbon_decoder
from benchmarks.market_first_signal_plane_v0 import SIGNAL_PLANE_VERSION
from benchmarks.market_first_signal_plane_v0.pipeline import (
    DurableResearchStateV0,
    drain_deferred_operations_v0,
    process_canonical_chunk_signal_plane_v0,
)
from src import database
from src.market_activity_discovery_run_v0 import create_market_activity_discovery_run_v0


PASS_CLASSIFICATION = "PASS_MARKET_FIRST_SIGNAL_PLANE_V0_REPLAY"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_SIGNAL_PLANE_V0_REPLAY"


def _elapsed_ms(started_ns: int) -> float:
    return (time.monotonic_ns() - started_ns) / 1_000_000.0


def _field_mismatches(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        field: {"signal": left.get(field), "shadow": right.get(field)}
        for field in _SIGNAL_PIPELINE_FIELDS
        if left.get(field) != right.get(field)
    }


def run_signal_plane_replay_v0(
    *,
    live_report_path: Path,
    raw_dir: Path,
    processed_root: Path,
    bootstrap_identities_path: Path,
    database_source_path: Path,
    max_chunks: int = 8,
    cargo: str = "cargo",
) -> dict[str, Any]:
    if max_chunks <= 0:
        raise ValueError("max_chunks must be positive")
    report = json.loads(Path(live_report_path).read_text(encoding="utf-8"))
    traces = _trace_paths(Path(raw_dir))
    if not traces:
        raise ValueError("raw_dir contains no traces")
    identities = _load_identity_observations(Path(bootstrap_identities_path))
    discovery_start_wall_ns = int(report["discovery_start_wall_ns"])
    discovery_close_wall_ns = int(report["discovery_close_wall_ns"])
    source_run = report.get("run") or {}
    source_started_at = int(source_run.get("started_at") or discovery_start_wall_ns // 1_000_000_000)

    signal_kernel = TriggerRecordingKernelV0()
    shadow_kernel = TriggerRecordingKernelV0()
    signal_state = LiveDiscoveryPipelineStateV0(kernel=signal_kernel)
    shadow_state = LiveDiscoveryPipelineStateV0(kernel=shadow_kernel)
    seed_bootstrap_identities_v0(signal_state, identities)
    seed_bootstrap_identities_v0(shadow_state, identities)
    durable_state = DurableResearchStateV0()
    chunk_results: list[dict[str, Any]] = []
    fatal_reason: str | None = None

    with tempfile.TemporaryDirectory(prefix="market-first-signal-plane-v0-") as directory:
        root = Path(directory)
        db_path = root / "signal-plane.db"
        shutil.copy2(database_source_path, db_path)
        isolated = replace(database.settings, database_path=db_path)
        run_key = f"{SIGNAL_PLANE_VERSION}:replay:{uuid.uuid4().hex[:12]}"
        cohort_key = f"{run_key}:cohort"

        with patch.object(database, "settings", isolated):
            create_market_activity_discovery_run_v0(
                acquisition_run_key=run_key,
                cohort_key=cohort_key,
                started_at=source_started_at,
            )

            for chunk_index, source in enumerate(traces[:max_chunks]):
                work = root / f"chunk-{chunk_index:06d}"
                raw_path = _materialize_trace(source, work / "raw.jsonl")
                carbon_input = work / "carbon-input.jsonl"
                manifest = work / "target-manifest.jsonl"
                carbon_output = work / "carbon-canonical.jsonl"

                print(f"[signal-v0] chunk={source.name} phase=reduce", flush=True)
                started = time.monotonic_ns()
                reducer = reduce_shadow(
                    trace_path=raw_path,
                    carbon_input_path=carbon_input,
                    manifest_path=manifest,
                )
                reduce_ms = _elapsed_ms(started)
                if not reducer.get("valid_for_carbon_decode"):
                    fatal_reason = f"reducer_rejected:{source.name}"
                    break

                print(f"[signal-v0] chunk={source.name} phase=carbon_decoder", flush=True)
                started = time.monotonic_ns()
                decoder = _run_carbon_decoder(
                    cargo=cargo,
                    carbon_input_path=carbon_input,
                    carbon_output_path=carbon_output,
                )
                decoder_ms = _elapsed_ms(started)
                if not decoder.get("footer_accounting_valid"):
                    fatal_reason = f"decoder_failed:{source.name}"
                    break

                print(f"[signal-v0] chunk={source.name} phase=signal", flush=True)
                started = time.monotonic_ns()
                signal_result = process_canonical_chunk_signal_plane_v0(
                    state=signal_state,
                    acquisition_run_key=run_key,
                    carbon_output_path=carbon_output,
                    target_manifest_path=manifest,
                    discovery_start_wall_ns=discovery_start_wall_ns,
                    discovery_close_wall_ns=discovery_close_wall_ns,
                )
                signal_canonical_ms = _elapsed_ms(started)

                print(f"[signal-v0] chunk={source.name} phase=shadow_reference", flush=True)
                started = time.monotonic_ns()
                shadow_unresolved = process_canonical_chunk_shadow_signal_v0(
                    state=shadow_state,
                    carbon_output_path=carbon_output,
                    target_manifest_path=manifest,
                    discovery_start_wall_ns=discovery_start_wall_ns,
                    discovery_close_wall_ns=discovery_close_wall_ns,
                )
                shadow_ms = _elapsed_ms(started)

                signal_summary = signal_state.summary()
                shadow_summary = shadow_state.summary()
                trigger_parity = compare_trigger_ledgers_v0(
                    signal_kernel.trigger_ledger,
                    shadow_kernel.trigger_ledger,
                )
                mismatches = _field_mismatches(signal_summary, shadow_summary)
                unresolved_match = set(signal_result.unresolved_pools) == set(shadow_unresolved)
                signal_errors = _signal_errors(signal_summary)
                shadow_errors = _signal_errors(shadow_summary)
                signal_total_ms = reduce_ms + decoder_ms + signal_canonical_ms

                print(f"[signal-v0] chunk={source.name} phase=durable_research", flush=True)
                started = time.monotonic_ns()
                errors_before = len(durable_state.errors)
                drain_deferred_operations_v0(
                    signal_result.deferred_operations,
                    state=durable_state,
                    max_observation_batch_size=256,
                )
                durable_ms = _elapsed_ms(started)
                new_durable_errors = durable_state.errors[errors_before:]

                chunk_ok = bool(
                    trigger_parity["exact_match"]
                    and unresolved_match
                    and not mismatches
                    and not signal_errors
                    and not shadow_errors
                    and not new_durable_errors
                )
                chunk_results.append(
                    {
                        "chunk_index": chunk_index,
                        "chunk": source.name,
                        "pass": chunk_ok,
                        "trigger_parity": trigger_parity,
                        "field_mismatches": mismatches,
                        "unresolved_pool_set_exact_match": unresolved_match,
                        "signal_errors": signal_errors,
                        "shadow_errors": shadow_errors,
                        "durable_errors": list(new_durable_errors),
                        "deferred_operation_count": len(signal_result.deferred_operations),
                        "emitted_trigger_count": signal_result.emitted_trigger_count,
                        "first_trigger_count": signal_result.first_trigger_count,
                        "timings_ms": {
                            "reduce": reduce_ms,
                            "carbon_decoder": decoder_ms,
                            "signal_canonical": signal_canonical_ms,
                            "shadow_reference_canonical": shadow_ms,
                            "signal_total": signal_total_ms,
                            "durable_research": durable_ms,
                        },
                        "signal_reference_le_5s": signal_total_ms <= 5000.0,
                        "signal_reference_le_2s": signal_total_ms <= 2000.0,
                    }
                )
                if not chunk_ok:
                    fatal_reason = f"chunk_contract_failed:{source.name}"
                    break

                refresh = load_recorded_identity_refresh_v0(
                    processed_root=Path(processed_root),
                    raw_trace_path=source,
                )
                apply_recorded_identity_refresh_v0(
                    baseline_state=signal_state,
                    shadow_state=shadow_state,
                    refresh=refresh,
                )

    all_chunks_pass = bool(chunk_results) and all(item["pass"] for item in chunk_results)
    all_signal_le_5s = bool(chunk_results) and all(
        item["signal_reference_le_5s"] for item in chunk_results
    )
    gates = {
        "all_chunks_signal_shadow_parity": all_chunks_pass,
        "durable_research_errors_empty": not durable_state.errors,
        "all_chunks_signal_reference_le_5s": all_signal_le_5s,
        "no_fatal_reason": fatal_reason is None,
    }
    passed = all(gates.values())
    return {
        "type": "market_first_signal_plane_v0_replay",
        "version": SIGNAL_PLANE_VERSION,
        "classification": PASS_CLASSIFICATION if passed else FAIL_CLASSIFICATION,
        "gates": gates,
        "fatal_reason": fatal_reason,
        "chunks_available": len(traces),
        "chunks_processed": len(chunk_results),
        "max_chunks": max_chunks,
        "bootstrap_identity_count": len(identities),
        "final_trigger_parity": compare_trigger_ledgers_v0(
            signal_kernel.trigger_ledger,
            shadow_kernel.trigger_ledger,
        ),
        "signal_pipeline": signal_state.summary(),
        "shadow_pipeline": shadow_state.summary(),
        "durable_research": durable_state.summary(),
        "chunk_results": chunk_results,
        "scientific_thresholds_modified": False,
        "live_behavior_modified": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acceptance replay for the split Market-First Signal Plane V0.")
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-identities", type=Path, required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_signal_plane_replay_v0(
        live_report_path=args.live_report,
        raw_dir=args.raw_dir,
        processed_root=args.processed_dir,
        bootstrap_identities_path=args.bootstrap_identities,
        database_source_path=args.database_source,
        max_chunks=args.max_chunks,
        cargo=args.cargo,
    )
    text = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
