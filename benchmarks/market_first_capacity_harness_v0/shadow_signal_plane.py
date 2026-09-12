from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from typing import Any, Sequence
from unittest.mock import patch

from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.market_first_capacity_harness_v0.run import (
    _load_identity_observations,
    _materialize_trace,
    _trace_paths,
)
from benchmarks.market_first_live_discovery_v0.contracts import (
    event_is_inside_discovery_window_v0,
    identities_available_before_v0,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    _increment,
    _nonnegative_int,
    _text,
    process_canonical_chunk_v0,
    seed_bootstrap_identities_v0,
)
from benchmarks.market_first_live_smoke_v0.run import (
    _canonical_rows_in_receive_order,
    _observed_at_from_wall_ns,
    _run_carbon_decoder,
)
from src import database
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    MISSING_CONTEXT,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.market_signal_kernel import IndexedMarketSignalKernel
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


SHADOW_VERSION = "market_first_shadow_signal_plane_v0"
PASS_CLASSIFICATION = "PASS_MARKET_FIRST_SHADOW_SIGNAL_PLANE_V0"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_SHADOW_SIGNAL_PLANE_V0"


class TriggerRecordingKernelV0(IndexedMarketSignalKernel):
    """The production kernel plus an immutable diagnostic ledger of emitted triggers."""

    def __init__(self) -> None:
        super().__init__()
        self.trigger_ledger: list[dict[str, Any]] = []

    def ingest_trade(self, trade: MarketTradeObservation):
        trigger = super().ingest_trade(trade)
        if trigger is not None:
            self.trigger_ledger.append(asdict(trigger))
        return trigger


def compare_trigger_ledgers_v0(
    baseline: Sequence[dict[str, Any]],
    shadow: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    left = list(baseline)
    right = list(shadow)
    first_mismatch_index: int | None = None
    for index in range(max(len(left), len(right))):
        if index >= len(left) or index >= len(right) or left[index] != right[index]:
            first_mismatch_index = index
            break
    return {
        "exact_match": left == right,
        "baseline_count": len(left),
        "shadow_count": len(right),
        "first_mismatch_index": first_mismatch_index,
    }


def derive_signal_path_comparison_v0(
    *,
    reduce_ms: float,
    decoder_ms: float,
    baseline_canonical_ms: float,
    shadow_canonical_ms: float,
) -> dict[str, Any]:
    shared_frontend_ms = max(0.0, float(reduce_ms)) + max(0.0, float(decoder_ms))
    baseline_ms = shared_frontend_ms + max(0.0, float(baseline_canonical_ms))
    shadow_ms = shared_frontend_ms + max(0.0, float(shadow_canonical_ms))
    saved_ms = max(0.0, baseline_ms - shadow_ms)
    return {
        "shared_reduce_plus_decoder_ms": shared_frontend_ms,
        "baseline_signal_chunk_service_ms": baseline_ms,
        "shadow_signal_chunk_service_ms": shadow_ms,
        "shadow_saved_ms": saved_ms,
        "shadow_saved_percent": (100.0 * saved_ms / baseline_ms if baseline_ms > 0 else 0.0),
        "single_chunk_reference_le_5s": shadow_ms <= 5000.0,
        "single_chunk_reference_le_2s": shadow_ms <= 2000.0,
    }


def _elapsed_ms(started_ns: int) -> float:
    return (time.monotonic_ns() - started_ns) / 1_000_000.0


def _shadow_record_lifecycle_v0(
    *,
    state: LiveDiscoveryPipelineStateV0,
    token_mint: str,
    chain_time: int,
    observed_at: int,
    venue: str,
) -> None:
    observation = MarketLifecycleObservation(
        token_mint=token_mint,
        market_started_at=chain_time,
        observed_at=observed_at,
        venue=venue,
    )
    state.kernel.ingest_lifecycle(observation)
    state.lifecycle_events_ingested += 1


def process_canonical_chunk_shadow_signal_v0(
    *,
    state: LiveDiscoveryPipelineStateV0,
    carbon_output_path: Path,
    target_manifest_path: Path,
    discovery_start_wall_ns: int,
    discovery_close_wall_ns: int,
) -> set[str]:
    """Run only the causal in-memory signal path over one decoded chunk.

    This deliberately omits observation persistence, episode persistence, T0 durable
    boundary writes and Research Plane work. It is a shadow benchmark only; it does
    not change live behavior. PumpSwap identities are restricted by the exact same
    observed-wall causal availability rule as the production canonical path.
    """

    ordered, pairing_errors = _canonical_rows_in_receive_order(
        carbon_output_path=carbon_output_path,
        target_manifest_path=target_manifest_path,
    )
    state.semantic_errors.extend(pairing_errors)
    state.canonical_events_paired += len(ordered)
    unresolved_for_lookup: set[str] = set()

    for row, manifest in ordered:
        event_key = str(row["event_key"])
        wall_ns = int(manifest["first_received_wall_ns"])
        if not event_is_inside_discovery_window_v0(
            wall_ns,
            discovery_start_wall_ns=discovery_start_wall_ns,
            discovery_close_wall_ns=discovery_close_wall_ns,
        ):
            state.out_of_window_events += 1
            continue
        if row.get("status") != "decoded":
            state.decode_failures += 1
            continue
        state.decoded_events += 1
        observed_at = _observed_at_from_wall_ns(wall_ns)
        event_type = _text(row, "event_type")

        if event_type == "pump_create":
            mint = _text(row, "mint")
            chain_time = _nonnegative_int(row, "timestamp")
            if mint is None or chain_time is None:
                state.semantic_errors.append(f"invalid_pump_create:{event_key}")
                continue
            _shadow_record_lifecycle_v0(
                state=state,
                token_mint=mint,
                chain_time=chain_time,
                observed_at=observed_at,
                venue="pump",
            )
            continue

        if event_type == "pumpswap_create_pool":
            pool = _text(row, "pool")
            base_mint = _text(row, "base_mint")
            quote_mint = _text(row, "quote_mint")
            chain_time = _nonnegative_int(row, "timestamp")
            slot = _nonnegative_int(row, "slot")
            if None in (pool, base_mint, quote_mint, chain_time, slot):
                state.semantic_errors.append(f"invalid_pumpswap_create_pool:{event_key}")
                continue
            state.add_identity(
                PumpSwapPoolIdentityObservation(
                    pool=str(pool),
                    base_mint=str(base_mint),
                    quote_mint=str(quote_mint),
                    observed_wall_ns=wall_ns,
                    observed_slot=int(slot),
                    evidence_key=event_key,
                    source="carbon_pumpswap_create_pool_event_v0",
                ),
                kind="create_pool",
            )
            _shadow_record_lifecycle_v0(
                state=state,
                token_mint=str(base_mint),
                chain_time=int(chain_time),
                observed_at=observed_at,
                venue="pumpswap",
            )
            continue

        if event_type == "pump_trade":
            matched = adapt_carbon_pump_trade_v0(row, observed_at=observed_at)
        elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
            pool = _text(row, "pool")
            causal_identities = (
                identities_available_before_v0(
                    state.pool_identities.get(pool or "", ()),
                    pool=pool or "",
                    event_wall_ns=wall_ns,
                )
                if pool is not None
                else ()
            )
            matched = adapt_carbon_pumpswap_trade_v0(
                row,
                observed_at=observed_at,
                observed_wall_ns=wall_ns,
                pool_observations=(),
                pool_identity_observations=causal_identities,
            )
            if matched.status == MISSING_CONTEXT and pool is not None:
                state.unresolved_pool_event_count += 1
                state.unresolved_unique_pools_seen.add(pool)
                if pool not in state.account_lookup_attempted_pools:
                    unresolved_for_lookup.add(pool)
        else:
            continue

        _increment(state.matched_unit_statuses, matched.status)
        market_trade = adapt_carbon_matched_unit_to_market_trade_v0(row, matched)
        _increment(state.market_trade_statuses, market_trade.status)
        if market_trade.status != ADAPTED or market_trade.observation is None:
            continue

        trigger = state.kernel.ingest_trade(market_trade.observation)
        state.market_trade_adapted_events += 1
        if trigger is not None:
            state.triggers_emitted += 1

    return unresolved_for_lookup


def run_shadow_signal_plane_v0(
    *,
    live_report_path: Path,
    raw_dir: Path,
    bootstrap_identities_path: Path,
    database_source_path: Path,
    cargo: str = "cargo",
    chunk_index: int = 0,
) -> dict[str, Any]:
    report = json.loads(Path(live_report_path).read_text(encoding="utf-8"))
    run = report.get("run") or {}
    identity = report.get("identity") or {}
    source_acquisition_run_key = str(
        run.get("acquisition_run_key") or identity.get("acquisition_run_key") or ""
    ).strip()
    if not source_acquisition_run_key:
        raise ValueError("live report lacks acquisition_run_key")

    traces = _trace_paths(Path(raw_dir))
    if not traces:
        raise ValueError("raw_dir contains no chunk traces")
    if chunk_index < 0 or chunk_index >= len(traces):
        raise ValueError(f"chunk_index out of range: {chunk_index}; available={len(traces)}")

    identities = _load_identity_observations(Path(bootstrap_identities_path))
    source = traces[chunk_index]
    discovery_start_wall_ns = int(report["discovery_start_wall_ns"])
    discovery_close_wall_ns = int(report["discovery_close_wall_ns"])

    with tempfile.TemporaryDirectory(prefix="market-first-shadow-signal-v0-") as directory:
        root = Path(directory)
        raw_path = _materialize_trace(source, root / "raw" / "chunk-shadow.jsonl")
        carbon_input = root / "carbon-input.jsonl"
        manifest = root / "target-manifest.jsonl"
        carbon_output = root / "carbon-canonical.jsonl"

        print(f"[shadow] chunk={source.name} phase=reduce", flush=True)
        started = time.monotonic_ns()
        reducer = reduce_shadow(
            trace_path=raw_path,
            carbon_input_path=carbon_input,
            manifest_path=manifest,
        )
        reduce_ms = _elapsed_ms(started)
        if not reducer.get("valid_for_carbon_decode"):
            raise RuntimeError("frozen reducer rejected shadow chunk")

        print(f"[shadow] chunk={source.name} phase=carbon_decoder", flush=True)
        started = time.monotonic_ns()
        decoder = _run_carbon_decoder(
            cargo=cargo,
            carbon_input_path=carbon_input,
            carbon_output_path=carbon_output,
        )
        decoder_ms = _elapsed_ms(started)
        if not decoder.get("footer_accounting_valid"):
            raise RuntimeError("Carbon event decoder accounting failed")

        baseline_db = root / "baseline.db"
        shutil.copy2(database_source_path, baseline_db)
        baseline_kernel = TriggerRecordingKernelV0()
        baseline_state = LiveDiscoveryPipelineStateV0(kernel=baseline_kernel)
        seed_bootstrap_identities_v0(baseline_state, identities)
        benchmark_run_key = (
            f"{source_acquisition_run_key}:shadow-parity:{uuid.uuid4().hex[:12]}"
        )

        print(f"[shadow] chunk={source.name} phase=baseline_canonical", flush=True)
        started = time.monotonic_ns()
        with patch.object(database.settings, "database_path", baseline_db):
            baseline_unresolved = process_canonical_chunk_v0(
                state=baseline_state,
                acquisition_run_key=benchmark_run_key,
                carbon_output_path=carbon_output,
                target_manifest_path=manifest,
                discovery_start_wall_ns=discovery_start_wall_ns,
                discovery_close_wall_ns=discovery_close_wall_ns,
            )
        baseline_canonical_ms = _elapsed_ms(started)

        shadow_kernel = TriggerRecordingKernelV0()
        shadow_state = LiveDiscoveryPipelineStateV0(kernel=shadow_kernel)
        seed_bootstrap_identities_v0(shadow_state, identities)

        print(f"[shadow] chunk={source.name} phase=shadow_canonical", flush=True)
        started = time.monotonic_ns()
        shadow_unresolved = process_canonical_chunk_shadow_signal_v0(
            state=shadow_state,
            carbon_output_path=carbon_output,
            target_manifest_path=manifest,
            discovery_start_wall_ns=discovery_start_wall_ns,
            discovery_close_wall_ns=discovery_close_wall_ns,
        )
        shadow_canonical_ms = _elapsed_ms(started)

    parity = compare_trigger_ledgers_v0(
        baseline_kernel.trigger_ledger,
        shadow_kernel.trigger_ledger,
    )
    unresolved_parity = set(baseline_unresolved) == set(shadow_unresolved)
    signal_path = derive_signal_path_comparison_v0(
        reduce_ms=reduce_ms,
        decoder_ms=decoder_ms,
        baseline_canonical_ms=baseline_canonical_ms,
        shadow_canonical_ms=shadow_canonical_ms,
    )
    baseline_clean = not (
        baseline_state.semantic_errors
        or baseline_state.persistence_errors
        or baseline_state.research_errors
        or baseline_state.chunk_errors
    )
    shadow_clean = not (
        shadow_state.semantic_errors
        or shadow_state.persistence_errors
        or shadow_state.research_errors
        or shadow_state.chunk_errors
    )
    passed = bool(parity["exact_match"] and unresolved_parity and baseline_clean and shadow_clean)

    return {
        "type": "market_first_shadow_signal_plane",
        "version": SHADOW_VERSION,
        "classification": PASS_CLASSIFICATION if passed else FAIL_CLASSIFICATION,
        "scientific_thresholds_modified": False,
        "live_behavior_modified": False,
        "chunk": source.name,
        "chunk_index": chunk_index,
        "source_chunk_count": len(traces),
        "bootstrap_identity_count": len(identities),
        "timings_ms": {
            "reduce": reduce_ms,
            "carbon_decoder": decoder_ms,
            "baseline_canonical": baseline_canonical_ms,
            "shadow_canonical": shadow_canonical_ms,
        },
        "signal_path": signal_path,
        "trigger_parity": parity,
        "unresolved_pool_set_exact_match": unresolved_parity,
        "baseline": {
            "pipeline": baseline_state.summary(),
            "trigger_ledger": baseline_kernel.trigger_ledger,
        },
        "shadow": {
            "pipeline": shadow_state.summary(),
            "trigger_ledger": shadow_kernel.trigger_ledger,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the current durable Market-First canonical path with a persistence-free "
            "shadow Signal Plane over the exact same decoded chunk and require trigger parity."
        )
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-identities", type=Path, required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_shadow_signal_plane_v0(
        live_report_path=args.live_report,
        raw_dir=args.raw_dir,
        bootstrap_identities_path=args.bootstrap_identities,
        database_source_path=args.database_source,
        cargo=args.cargo,
        chunk_index=args.chunk_index,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
