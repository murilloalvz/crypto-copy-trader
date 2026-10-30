from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from typing import Any
from unittest.mock import patch

from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.market_first_capacity_harness_v0 import shadow_signal_plane as shadow_module
from benchmarks.market_first_capacity_harness_v0.run import (
    _load_identity_observations,
    _materialize_trace,
    _trace_paths,
)
from benchmarks.market_first_capacity_harness_v0.shadow_result_gate import (
    _SIGNAL_PIPELINE_FIELDS,
    _signal_errors,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    process_canonical_chunk_v0,
    seed_bootstrap_identities_v0,
)
from benchmarks.market_first_live_smoke_v0.run import _run_carbon_decoder
from src import database
from src.carbon_matched_unit_adapter import ADAPTED
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


VERSION = "market_first_shadow_pumpswap_causal_v0"
PASS_CLASSIFICATION = "PASS_MARKET_FIRST_SHADOW_PUMPSWAP_CAUSAL_V0"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_SHADOW_PUMPSWAP_CAUSAL_V0"


class VenueRecordingKernelV0(shadow_module.TriggerRecordingKernelV0):
    def __init__(self) -> None:
        super().__init__()
        self.trade_events_by_venue: Counter[str] = Counter()

    def ingest_trade(self, trade):
        venue = str(getattr(trade, "venue", "") or "unknown").strip().lower() or "unknown"
        self.trade_events_by_venue[venue] += 1
        return super().ingest_trade(trade)


def _jsonl_any(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else path.open
    with opener(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _first_existing(directory: Path, basename: str) -> Path | None:
    for candidate in (directory / basename, directory / f"{basename}.gz"):
        if candidate.exists():
            return candidate
    return None


def _processed_chunk_directory_v0(processed_root: Path, raw_trace_path: Path) -> Path:
    """Map a durable raw trace filename back to the live processor's chunk directory.

    The live processor creates its directory while the raw trace is still named
    `chunk-XXXXXX.jsonl`, so `Path.stem` yields `chunk-XXXXXX`. Later evidence
    compression renames the raw file to `chunk-XXXXXX.jsonl.gz`. A replay that
    blindly uses `.stem` on the compressed name would incorrectly look for
    `processed/chunk-XXXXXX.jsonl`.
    """

    name = raw_trace_path.name
    if name.endswith(".jsonl.gz"):
        chunk_key = name[: -len(".jsonl.gz")]
    elif name.endswith(".jsonl"):
        chunk_key = name[: -len(".jsonl")]
    else:
        chunk_key = raw_trace_path.stem
    if not chunk_key:
        raise ValueError(f"cannot derive processed chunk directory from {raw_trace_path}")
    return Path(processed_root) / chunk_key


def load_recorded_identity_refresh_v0(
    *,
    processed_root: Path,
    raw_trace_path: Path,
) -> dict[str, Any]:
    chunk_dir = _processed_chunk_directory_v0(Path(processed_root), raw_trace_path)
    input_path = _first_existing(chunk_dir, "pool-account-input.jsonl")
    output_path = _first_existing(chunk_dir, "pool-account-output.jsonl")
    if (input_path is None) != (output_path is None):
        raise RuntimeError(f"partial recorded identity evidence for {raw_trace_path.name}")
    if input_path is None:
        return {
            "evidence_present": False,
            "chunk_dir": str(chunk_dir),
            "attempted_pools": (),
            "identities": (),
        }

    attempted = tuple(
        sorted(
            {
                str(row.get("pool") or "").strip()
                for row in _jsonl_any(input_path)
                if row.get("type") == "pumpswap_pool_account_input"
                and str(row.get("pool") or "").strip()
            }
        )
    )
    identities: list[PumpSwapPoolIdentityObservation] = []
    for row in _jsonl_any(output_path):
        if row.get("type") != "pumpswap_pool_identity_decode" or row.get("status") != "ADAPTED":
            continue
        identities.append(
            PumpSwapPoolIdentityObservation(
                pool=str(row["pool"]),
                base_mint=str(row["base_mint"]),
                quote_mint=str(row["quote_mint"]),
                observed_wall_ns=int(row["observed_wall_ns"]),
                observed_slot=int(row["observed_slot"]),
                evidence_key=str(row["evidence_key"]),
                source=str(row["source"]),
            )
        )
    identities.sort(key=lambda item: (item.observed_wall_ns, item.pool, item.evidence_key))
    return {
        "evidence_present": True,
        "chunk_dir": str(chunk_dir),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "attempted_pools": attempted,
        "identities": tuple(identities),
    }


def apply_recorded_identity_refresh_v0(
    *,
    baseline_state: LiveDiscoveryPipelineStateV0,
    shadow_state: LiveDiscoveryPipelineStateV0,
    refresh: dict[str, Any],
) -> dict[str, Any]:
    attempted = tuple(refresh.get("attempted_pools") or ())
    identities = tuple(refresh.get("identities") or ())
    baseline_state.account_lookup_attempted_pools.update(attempted)
    shadow_state.account_lookup_attempted_pools.update(attempted)
    for identity in identities:
        baseline_state.add_identity(identity, kind="rpc")
        shadow_state.add_identity(identity, kind="rpc")
    return {
        "evidence_present": bool(refresh.get("evidence_present")),
        "attempted_pool_count": len(attempted),
        "identity_count": len(identities),
        "identity_evidence_keys": [item.evidence_key for item in identities],
        "earliest_identity_observed_wall_ns": (
            min((item.observed_wall_ns for item in identities), default=None)
        ),
        "latest_identity_observed_wall_ns": (
            max((item.observed_wall_ns for item in identities), default=None)
        ),
    }


def _field_mismatches(
    baseline: dict[str, Any],
    shadow: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        field: {"baseline": baseline.get(field), "shadow": shadow.get(field)}
        for field in _SIGNAL_PIPELINE_FIELDS
        if baseline.get(field) != shadow.get(field)
    }


def _elapsed_ms(started_ns: int) -> float:
    return (time.monotonic_ns() - started_ns) / 1_000_000.0


def run_shadow_pumpswap_causal_v0(
    *,
    live_report_path: Path,
    raw_dir: Path,
    bootstrap_identities_path: Path,
    database_source_path: Path,
    processed_root: Path | None = None,
    cargo: str = "cargo",
    max_chunks: int = 8,
) -> dict[str, Any]:
    if max_chunks <= 0:
        raise ValueError("max_chunks must be positive")
    report = json.loads(Path(live_report_path).read_text(encoding="utf-8"))
    run = report.get("run") or {}
    identity = report.get("identity") or {}
    source_acquisition_run_key = str(
        run.get("acquisition_run_key") or identity.get("acquisition_run_key") or ""
    ).strip()
    if not source_acquisition_run_key:
        raise ValueError("live report lacks acquisition_run_key")
    if processed_root is None:
        processed_root = Path((report.get("artifacts") or {}).get("processed_chunks") or "")
    processed_root = Path(processed_root)
    if not processed_root.exists():
        raise ValueError(f"processed chunk evidence root does not exist: {processed_root}")

    traces = _trace_paths(Path(raw_dir))
    if not traces:
        raise ValueError("raw_dir contains no chunk traces")
    identities = _load_identity_observations(Path(bootstrap_identities_path))
    discovery_start_wall_ns = int(report["discovery_start_wall_ns"])
    discovery_close_wall_ns = int(report["discovery_close_wall_ns"])

    baseline_kernel = VenueRecordingKernelV0()
    shadow_kernel = VenueRecordingKernelV0()
    baseline_state = LiveDiscoveryPipelineStateV0(kernel=baseline_kernel)
    shadow_state = LiveDiscoveryPipelineStateV0(kernel=shadow_kernel)
    seed_bootstrap_identities_v0(baseline_state, identities)
    seed_bootstrap_identities_v0(shadow_state, identities)

    recorded_rpc_evidence_keys: set[str] = set()
    chunk_results: list[dict[str, Any]] = []
    proof: dict[str, Any] | None = None
    fatal_reason: str | None = None

    with tempfile.TemporaryDirectory(prefix="market-first-shadow-pumpswap-v0-") as directory:
        root = Path(directory)
        baseline_db = root / "baseline.db"
        shutil.copy2(database_source_path, baseline_db)
        isolated_settings = replace(database.settings, database_path=baseline_db)
        benchmark_run_key = (
            f"{source_acquisition_run_key}:shadow-pumpswap:{uuid.uuid4().hex[:12]}"
        )

        for chunk_index, source in enumerate(traces[:max_chunks]):
            work = root / f"chunk-{chunk_index:06d}"
            raw_path = _materialize_trace(source, work / "raw.jsonl")
            carbon_input = work / "carbon-input.jsonl"
            manifest = work / "target-manifest.jsonl"
            carbon_output = work / "carbon-canonical.jsonl"

            print(f"[pumpswap-shadow] chunk={source.name} phase=reduce", flush=True)
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

            print(f"[pumpswap-shadow] chunk={source.name} phase=carbon_decoder", flush=True)
            started = time.monotonic_ns()
            decoder = _run_carbon_decoder(
                cargo=cargo,
                carbon_input_path=carbon_input,
                carbon_output_path=carbon_output,
            )
            decoder_ms = _elapsed_ms(started)
            if not decoder.get("footer_accounting_valid"):
                fatal_reason = f"decoder_accounting_failed:{source.name}"
                break

            print(f"[pumpswap-shadow] chunk={source.name} phase=baseline_canonical", flush=True)
            started = time.monotonic_ns()
            with patch.object(database, "settings", isolated_settings):
                baseline_unresolved = process_canonical_chunk_v0(
                    state=baseline_state,
                    acquisition_run_key=benchmark_run_key,
                    carbon_output_path=carbon_output,
                    target_manifest_path=manifest,
                    discovery_start_wall_ns=discovery_start_wall_ns,
                    discovery_close_wall_ns=discovery_close_wall_ns,
                )
            baseline_ms = _elapsed_ms(started)

            pumpswap_adapted_records: list[dict[str, Any]] = []
            original_adapter = shadow_module.adapt_carbon_pumpswap_trade_v0

            def recording_adapter(row, **kwargs):
                result = original_adapter(row, **kwargs)
                if result.status == ADAPTED:
                    causal = tuple(kwargs.get("pool_identity_observations") or ())
                    pumpswap_adapted_records.append(
                        {
                            "event_key": str(row.get("event_key") or ""),
                            "pool": str(row.get("pool") or ""),
                            "causal_identity_evidence_keys": [item.evidence_key for item in causal],
                            "causal_identity_sources": [item.source for item in causal],
                        }
                    )
                return result

            print(f"[pumpswap-shadow] chunk={source.name} phase=shadow_canonical", flush=True)
            started = time.monotonic_ns()
            with patch.object(
                shadow_module,
                "adapt_carbon_pumpswap_trade_v0",
                recording_adapter,
            ):
                shadow_unresolved = shadow_module.process_canonical_chunk_shadow_signal_v0(
                    state=shadow_state,
                    carbon_output_path=carbon_output,
                    target_manifest_path=manifest,
                    discovery_start_wall_ns=discovery_start_wall_ns,
                    discovery_close_wall_ns=discovery_close_wall_ns,
                )
            shadow_ms = _elapsed_ms(started)

            baseline_summary = baseline_state.summary()
            shadow_summary = shadow_state.summary()
            trigger_parity = shadow_module.compare_trigger_ledgers_v0(
                baseline_kernel.trigger_ledger,
                shadow_kernel.trigger_ledger,
            )
            field_mismatches = _field_mismatches(baseline_summary, shadow_summary)
            unresolved_match = set(baseline_unresolved) == set(shadow_unresolved)
            venue_match = dict(baseline_kernel.trade_events_by_venue) == dict(
                shadow_kernel.trade_events_by_venue
            )
            signal_errors = {
                "baseline": _signal_errors(baseline_summary),
                "shadow": _signal_errors(shadow_summary),
            }
            dynamic_pumpswap_records = [
                item
                for item in pumpswap_adapted_records
                if any(
                    key in recorded_rpc_evidence_keys
                    for key in item["causal_identity_evidence_keys"]
                )
            ]
            signal_path = shadow_module.derive_signal_path_comparison_v0(
                reduce_ms=reduce_ms,
                decoder_ms=decoder_ms,
                baseline_canonical_ms=baseline_ms,
                shadow_canonical_ms=shadow_ms,
            )

            chunk_ok = bool(
                trigger_parity["exact_match"]
                and unresolved_match
                and venue_match
                and not field_mismatches
                and not signal_errors["baseline"]
                and not signal_errors["shadow"]
            )
            chunk_result = {
                "chunk_index": chunk_index,
                "chunk": source.name,
                "chunk_signal_parity_pass": chunk_ok,
                "trigger_parity": trigger_parity,
                "unresolved_pool_set_exact_match": unresolved_match,
                "venue_counters_exact_match": venue_match,
                "field_mismatches": field_mismatches,
                "signal_errors": signal_errors,
                "trade_events_by_venue": {
                    "baseline": dict(sorted(baseline_kernel.trade_events_by_venue.items())),
                    "shadow": dict(sorted(shadow_kernel.trade_events_by_venue.items())),
                },
                "pumpswap_adapted_records_this_chunk": len(pumpswap_adapted_records),
                "pumpswap_adapted_via_prior_recorded_rpc_identity": len(dynamic_pumpswap_records),
                "dynamic_pumpswap_examples": dynamic_pumpswap_records[:5],
                "timings_ms": {
                    "reduce": reduce_ms,
                    "carbon_decoder": decoder_ms,
                    "baseline_canonical": baseline_ms,
                    "shadow_canonical": shadow_ms,
                },
                "signal_path": signal_path,
            }
            chunk_results.append(chunk_result)
            if not chunk_ok:
                fatal_reason = f"signal_parity_failed:{source.name}"
                break

            if dynamic_pumpswap_records:
                proof = {
                    "chunk_index": chunk_index,
                    "chunk": source.name,
                    "adapted_via_prior_recorded_rpc_identity_count": len(dynamic_pumpswap_records),
                    "examples": dynamic_pumpswap_records[:5],
                    "signal_path": signal_path,
                }
                break

            refresh = load_recorded_identity_refresh_v0(
                processed_root=processed_root,
                raw_trace_path=source,
            )
            if baseline_unresolved and not refresh["evidence_present"]:
                fatal_reason = f"missing_recorded_identity_refresh:{source.name}"
                break
            applied = apply_recorded_identity_refresh_v0(
                baseline_state=baseline_state,
                shadow_state=shadow_state,
                refresh=refresh,
            )
            recorded_rpc_evidence_keys.update(applied["identity_evidence_keys"])
            chunk_result["recorded_identity_refresh_after_chunk"] = applied

    all_chunk_parity = bool(chunk_results) and all(
        item["chunk_signal_parity_pass"] for item in chunk_results
    )
    gates = {
        "all_processed_chunks_signal_parity": all_chunk_parity,
        "recorded_rpc_identity_evidence_applied": bool(recorded_rpc_evidence_keys),
        "pumpswap_adapted_using_prior_recorded_rpc_identity": proof is not None,
        "no_fatal_reason": fatal_reason is None,
    }
    passed = all(gates.values())
    return {
        "type": "market_first_shadow_pumpswap_causal",
        "version": VERSION,
        "classification": PASS_CLASSIFICATION if passed else FAIL_CLASSIFICATION,
        "gates": gates,
        "fatal_reason": fatal_reason,
        "chunks_available": len(traces),
        "chunks_processed": len(chunk_results),
        "max_chunks": max_chunks,
        "bootstrap_identity_count": len(identities),
        "recorded_rpc_identity_evidence_key_count": len(recorded_rpc_evidence_keys),
        "proof": proof,
        "chunk_results": chunk_results,
        "final_trigger_parity": shadow_module.compare_trigger_ledgers_v0(
            baseline_kernel.trigger_ledger,
            shadow_kernel.trigger_ledger,
        ),
        "final_trade_events_by_venue": {
            "baseline": dict(sorted(baseline_kernel.trade_events_by_venue.items())),
            "shadow": dict(sorted(shadow_kernel.trade_events_by_venue.items())),
        },
        "non_gating_post_signal_research_errors": {
            "baseline": list(baseline_state.research_errors),
            "shadow": list(shadow_state.research_errors),
        },
        "scientific_thresholds_modified": False,
        "live_behavior_modified": False,
        "causal_replay_policy": (
            "Recorded dynamic RPC identities from original chunk N are applied only after both "
            "baseline and shadow finish chunk N, so they can affect chunk N+1 or later only. "
            "Each event still passes identities_available_before_v0 against original observed_wall_ns."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay sequential Market-First chunks with original recorded PumpSwap identity "
            "refreshes and require exact baseline/shadow Signal Plane parity until a PumpSwap "
            "trade is adapted using an identity learned after a prior chunk."
        )
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-identities", type=Path, required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_shadow_pumpswap_causal_v0(
        live_report_path=args.live_report,
        raw_dir=args.raw_dir,
        bootstrap_identities_path=args.bootstrap_identities,
        database_source_path=args.database_source,
        processed_root=args.processed_dir,
        cargo=args.cargo,
        max_chunks=args.max_chunks,
    )
    text = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
