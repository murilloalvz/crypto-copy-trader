from __future__ import annotations

from dataclasses import asdict, dataclass, field
import gzip
import json
from pathlib import Path
import shutil
from typing import Any, Sequence

from benchmarks.helius_standard_wss_shadow_v0.collect import SOURCE_PROVIDER
from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.market_first_live_discovery_v0.contracts import (
    event_is_inside_discovery_window_v0,
    identities_available_before_v0,
)
from benchmarks.market_first_live_smoke_v0.run import (
    _canonical_rows_in_receive_order,
    _observed_at_from_wall_ns,
    _run_carbon_decoder,
)
from benchmarks.pumpswap_identity_bootstrap_v0.bootstrap import (
    _load_identity_observations,
    _run_account_decoder,
    fetch_pool_account_inputs,
)
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    MISSING_CONTEXT,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.market_activity_discovery_handoff_v0 import build_market_activity_discovery_handoff_v0
from src.market_activity_discovery_research_processor_v0 import (
    process_market_activity_discovery_handoff_v0,
)
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import MarketLifecycleObservation
from src.market_signal_kernel import IndexedMarketSignalKernel
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


@dataclass
class LiveDiscoveryPipelineStateV0:
    kernel: IndexedMarketSignalKernel = field(default_factory=IndexedMarketSignalKernel)
    pool_identities: dict[str, list[PumpSwapPoolIdentityObservation]] = field(default_factory=dict)
    account_lookup_attempted_pools: set[str] = field(default_factory=set)
    chunks_processed: int = 0
    canonical_events_paired: int = 0
    decoded_events: int = 0
    decode_failures: int = 0
    out_of_window_events: int = 0
    lifecycle_events_ingested: int = 0
    market_trade_adapted_events: int = 0
    market_trade_statuses: dict[str, int] = field(default_factory=dict)
    matched_unit_statuses: dict[str, int] = field(default_factory=dict)
    triggers_emitted: int = 0
    first_trigger_episodes: int = 0
    grouped_trigger_count: int = 0
    research_handoffs_processed: int = 0
    bootstrap_identity_count: int = 0
    create_pool_identity_count: int = 0
    rpc_identity_count: int = 0
    unresolved_pool_event_count: int = 0
    unresolved_unique_pools_seen: set[str] = field(default_factory=set)
    dynamic_rpc_pools_requested: int = 0
    dynamic_rpc_batches: int = 0
    dynamic_rpc_account_missing: int = 0
    dynamic_rpc_invalid_account_shape: int = 0
    dynamic_account_decode_failures: int = 0
    semantic_errors: list[str] = field(default_factory=list)
    persistence_errors: list[str] = field(default_factory=list)
    research_errors: list[str] = field(default_factory=list)
    chunk_errors: list[str] = field(default_factory=list)

    def add_identity(self, identity: PumpSwapPoolIdentityObservation, *, kind: str) -> None:
        bucket = self.pool_identities.setdefault(identity.pool, [])
        key = (identity.observed_wall_ns, identity.evidence_key)
        if any((item.observed_wall_ns, item.evidence_key) == key for item in bucket):
            return
        bucket.append(identity)
        bucket.sort(key=lambda item: (item.observed_wall_ns, item.observed_slot, item.evidence_key))
        if kind == "bootstrap":
            self.bootstrap_identity_count += 1
        elif kind == "create_pool":
            self.create_pool_identity_count += 1
        elif kind == "rpc":
            self.rpc_identity_count += 1
        else:
            raise ValueError(f"unsupported identity kind: {kind}")

    def summary(self) -> dict[str, Any]:
        stats = self.kernel.stats()
        return {
            "chunks_processed": self.chunks_processed,
            "canonical_events_paired": self.canonical_events_paired,
            "decoded_events": self.decoded_events,
            "decode_failures_seen_in_processing": self.decode_failures,
            "out_of_window_events": self.out_of_window_events,
            "lifecycle_events_ingested": self.lifecycle_events_ingested,
            "matched_unit_statuses": dict(sorted(self.matched_unit_statuses.items())),
            "market_trade_statuses": dict(sorted(self.market_trade_statuses.items())),
            "market_trade_adapted_events": self.market_trade_adapted_events,
            "kernel_trade_events_ingested": stats.trade_events_ingested,
            "kernel_retained_trade_rows": stats.retained_trade_rows,
            "kernel_tracked_assets": stats.tracked_assets,
            "kernel_triggers_emitted": self.triggers_emitted,
            "first_trigger_episodes": self.first_trigger_episodes,
            "grouped_trigger_count": self.grouped_trigger_count,
            "research_handoffs_processed": self.research_handoffs_processed,
            "bootstrap_identity_count": self.bootstrap_identity_count,
            "create_pool_identity_count": self.create_pool_identity_count,
            "rpc_identity_count": self.rpc_identity_count,
            "current_identity_pool_count": len(self.pool_identities),
            "unresolved_pool_event_count": self.unresolved_pool_event_count,
            "unresolved_unique_pool_count": len(self.unresolved_unique_pools_seen),
            "dynamic_rpc_pools_requested": self.dynamic_rpc_pools_requested,
            "dynamic_rpc_batches": self.dynamic_rpc_batches,
            "dynamic_rpc_account_missing": self.dynamic_rpc_account_missing,
            "dynamic_rpc_invalid_account_shape": self.dynamic_rpc_invalid_account_shape,
            "dynamic_account_decode_failures": self.dynamic_account_decode_failures,
            "semantic_errors": list(self.semantic_errors),
            "persistence_errors": list(self.persistence_errors),
            "research_errors": list(self.research_errors),
            "chunk_errors": list(self.chunk_errors),
            "economic_edge_evaluated": False,
        }


def seed_bootstrap_identities_v0(
    state: LiveDiscoveryPipelineStateV0,
    identities: Sequence[PumpSwapPoolIdentityObservation],
) -> None:
    for item in identities:
        state.add_identity(item, kind="bootstrap")


def _text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_int(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _gzip_and_remove(path: Path) -> Path | None:
    if not path.exists():
        return None
    target = path.with_suffix(path.suffix + ".gz")
    temporary = target.with_suffix(target.suffix + ".tmp")
    with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    temporary.replace(target)
    path.unlink()
    return target


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _record_lifecycle(
    *,
    state: LiveDiscoveryPipelineStateV0,
    acquisition_run_key: str,
    event_key: str,
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
    try:
        record_market_lifecycle(
            acquisition_run_key=acquisition_run_key,
            event_key=event_key,
            source_provider=SOURCE_PROVIDER,
            observation=observation,
        )
        state.kernel.ingest_lifecycle(observation)
        state.lifecycle_events_ingested += 1
    except Exception as exc:
        state.persistence_errors.append(
            f"{event_key}:lifecycle:{type(exc).__name__}:{exc}"
        )


def process_canonical_chunk_v0(
    *,
    state: LiveDiscoveryPipelineStateV0,
    acquisition_run_key: str,
    carbon_output_path: Path,
    target_manifest_path: Path,
    discovery_start_wall_ns: int,
    discovery_close_wall_ns: int,
) -> set[str]:
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
            _record_lifecycle(
                state=state,
                acquisition_run_key=acquisition_run_key,
                event_key=event_key,
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
            identity = PumpSwapPoolIdentityObservation(
                pool=str(pool),
                base_mint=str(base_mint),
                quote_mint=str(quote_mint),
                observed_wall_ns=wall_ns,
                observed_slot=int(slot),
                evidence_key=event_key,
                source="carbon_pumpswap_create_pool_event_v0",
            )
            state.add_identity(identity, kind="create_pool")
            _record_lifecycle(
                state=state,
                acquisition_run_key=acquisition_run_key,
                event_key=event_key,
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

        observation = market_trade.observation
        try:
            record_market_trade(
                acquisition_run_key=acquisition_run_key,
                event_key=event_key,
                source_provider=SOURCE_PROVIDER,
                observation=observation,
            )
            trigger = state.kernel.ingest_trade(observation)
            state.market_trade_adapted_events += 1
        except Exception as exc:
            state.persistence_errors.append(
                f"{event_key}:market_trade_or_kernel:{type(exc).__name__}:{exc}"
            )
            continue

        if trigger is None:
            continue
        state.triggers_emitted += 1
        chain_as_of = trigger.features.chain_as_of
        if chain_as_of is None:
            state.semantic_errors.append(f"{event_key}:trigger_missing_chain_as_of")
            continue
        trigger_key = f"{event_key}:market-radar:{trigger.trigger_kind}"
        try:
            episode = assign_market_opportunity_trigger(
                acquisition_run_key=acquisition_run_key,
                trigger_key=trigger_key,
                token_mint=trigger.token_mint,
                trigger_kind=trigger.trigger_kind,
                direction=trigger.direction,
                chain_time=int(chain_as_of),
                observed_at=int(trigger.as_of),
                method_version=trigger.method_version,
                venue=observation.venue,
            )
        except Exception as exc:
            state.persistence_errors.append(
                f"{event_key}:episode_assignment:{type(exc).__name__}:{exc}"
            )
            continue

        if episode.first_trigger_key != trigger_key:
            state.grouped_trigger_count += 1
            continue
        state.first_trigger_episodes += 1
        try:
            handoff = build_market_activity_discovery_handoff_v0(
                episode=episode,
                trigger_key=trigger_key,
            )
            if handoff is None:
                raise RuntimeError("canonical first trigger did not produce a handoff")
            processing = process_market_activity_discovery_handoff_v0(handoff)
            if processing.provider_calls_performed != 0:
                raise RuntimeError("discovery Research Plane unexpectedly called a provider")
            state.research_handoffs_processed += 1
        except Exception as exc:
            state.research_errors.append(
                f"{event_key}:research_handoff:{type(exc).__name__}:{exc}"
            )

    return unresolved_for_lookup


def resolve_unknown_pools_after_chunk_v0(
    *,
    state: LiveDiscoveryPipelineStateV0,
    api_key: str,
    pools: Sequence[str],
    cargo: str,
    work_dir: Path,
) -> dict[str, Any]:
    unresolved = tuple(
        sorted(
            pool
            for pool in set(pools)
            if pool and pool not in state.account_lookup_attempted_pools
        )
    )
    if not unresolved:
        return {"requested": 0, "adapted": 0, "skipped": True}
    state.account_lookup_attempted_pools.update(unresolved)
    account_rows, rpc = fetch_pool_account_inputs(api_key=api_key, pools=unresolved)
    state.dynamic_rpc_pools_requested += int(rpc["requested"])
    state.dynamic_rpc_batches += int(rpc["rpc_batches"])
    state.dynamic_rpc_account_missing += int(rpc["account_missing"])
    state.dynamic_rpc_invalid_account_shape += int(rpc["invalid_account_shape"])

    input_path = work_dir / "pool-account-input.jsonl"
    output_path = work_dir / "pool-account-output.jsonl"
    _write_jsonl(input_path, account_rows)
    decoder = _run_account_decoder(
        cargo=cargo,
        input_path=input_path,
        output_path=output_path,
    )
    if not decoder.get("footer_accounting_valid"):
        raise RuntimeError("dynamic PumpSwap account decoder accounting failed")
    identities = _load_identity_observations(output_path)
    for item in identities:
        state.add_identity(item, kind="rpc")
    footer = decoder.get("footer") or {}
    state.dynamic_account_decode_failures += int(footer.get("decode_failed") or 0)
    return {
        "requested": len(unresolved),
        "rpc": rpc,
        "decoder": decoder,
        "adapted": len(identities),
    }


def process_trace_chunk_v0(
    *,
    state: LiveDiscoveryPipelineStateV0,
    api_key: str,
    cargo: str,
    acquisition_run_key: str,
    raw_trace_path: Path,
    processed_root: Path,
    discovery_start_wall_ns: int,
    discovery_close_wall_ns: int,
    compress_evidence: bool = True,
) -> dict[str, Any]:
    chunk_name = raw_trace_path.stem
    work_dir = processed_root / chunk_name
    work_dir.mkdir(parents=True, exist_ok=False)
    carbon_input = work_dir / "carbon-input.jsonl"
    manifest = work_dir / "target-manifest.jsonl"
    carbon_output = work_dir / "carbon-canonical.jsonl"
    report_path = work_dir / "chunk-report.json"

    report: dict[str, Any] = {
        "chunk": chunk_name,
        "raw_trace": str(raw_trace_path),
        "economic_edge_evaluated": False,
    }
    try:
        reducer = reduce_shadow(
            trace_path=raw_trace_path,
            carbon_input_path=carbon_input,
            manifest_path=manifest,
        )
        report["reducer"] = reducer
        accepted = int(reducer.get("accepted_success_target_events") or 0)
        if accepted == 0:
            report["status"] = "NO_TARGET_EVENTS"
        else:
            if not reducer.get("valid_for_carbon_decode"):
                raise RuntimeError("frozen reducer rejected live discovery chunk")
            decoder = _run_carbon_decoder(
                cargo=cargo,
                carbon_input_path=carbon_input,
                carbon_output_path=carbon_output,
            )
            report["decoder"] = decoder
            if not decoder.get("footer_accounting_valid"):
                raise RuntimeError("Carbon event decoder accounting failed")
            unresolved = process_canonical_chunk_v0(
                state=state,
                acquisition_run_key=acquisition_run_key,
                carbon_output_path=carbon_output,
                target_manifest_path=manifest,
                discovery_start_wall_ns=discovery_start_wall_ns,
                discovery_close_wall_ns=discovery_close_wall_ns,
            )
            report["identity_refresh"] = resolve_unknown_pools_after_chunk_v0(
                state=state,
                api_key=api_key,
                pools=tuple(unresolved),
                cargo=cargo,
                work_dir=work_dir,
            )
            report["status"] = "PROCESSED"
        state.chunks_processed += 1
        report["pipeline_after_chunk"] = state.summary()
        if compress_evidence:
            compressed: dict[str, str] = {}
            for label, path in (
                ("raw_trace", raw_trace_path),
                ("carbon_input", carbon_input),
                ("target_manifest", manifest),
                ("carbon_output", carbon_output),
                ("pool_account_input", work_dir / "pool-account-input.jsonl"),
                ("pool_account_output", work_dir / "pool-account-output.jsonl"),
            ):
                gz = _gzip_and_remove(path)
                if gz is not None:
                    compressed[label] = str(gz)
            report["compressed_evidence"] = compressed
    except Exception as exc:
        error = f"{chunk_name}:{type(exc).__name__}:{exc}"
        state.chunk_errors.append(error)
        report["status"] = "FAILED"
        report["error"] = error
    report_path.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report
