from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from benchmarks.helius_standard_wss_shadow_v0.collect import SOURCE_PROVIDER
from benchmarks.market_first_live_discovery_v0.contracts import (
    event_is_inside_discovery_window_v0,
    identities_available_before_v0,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    _increment,
    _nonnegative_int,
    _text,
)
from benchmarks.market_first_live_smoke_v0.run import (
    _canonical_rows_in_receive_order,
    _observed_at_from_wall_ns,
)
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    MISSING_CONTEXT,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.market_activity_discovery_handoff_v0 import (
    MarketActivityDiscoveryHandoffV0,
    build_market_activity_discovery_handoff_v0,
)
from src.market_activity_discovery_research_processor_v0 import (
    process_market_activity_discovery_handoff_v0,
)
from src.market_activity_discovery_signal_boundary_v0 import (
    seal_market_activity_discovery_signal_boundary_v0,
)
from src.market_observation_batch_v0 import (
    MarketLifecycleWriteV0,
    MarketObservationWriteV0,
    MarketTradeWriteV0,
    record_market_observations_batch_v0,
)
from src.market_opportunity_episode_batch_v0 import (
    MarketContinuationTriggerWriteV0,
    record_market_continuation_triggers_batch_v0,
)
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_opportunity_radar import MarketLifecycleObservation
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


@dataclass(frozen=True)
class DeferredResearchHandoffV0:
    handoff: MarketActivityDiscoveryHandoffV0


DeferredOperationV0 = (
    MarketObservationWriteV0 | MarketContinuationTriggerWriteV0 | DeferredResearchHandoffV0
)


@dataclass
class SignalPlaneEpisodeTrackerV0:
    """In-memory cache of the canonical episode already durably opened per token.

    It never creates or mutates a durable episode. A trigger can bypass synchronous
    SQLite only when its local observation clock is provably inside the already-open
    persisted episode window. Any ambiguous/replay/late-earlier case falls back to the
    canonical store synchronously.
    """

    active_by_token: dict[str, MarketOpportunityEpisode] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalChunkResultV0:
    unresolved_pools: tuple[str, ...]
    deferred_operations: tuple[DeferredOperationV0, ...]
    emitted_trigger_count: int
    first_trigger_count: int


@dataclass
class DurableResearchStateV0:
    observation_writes_attempted: int = 0
    observation_writes_inserted: int = 0
    observation_replays: int = 0
    observation_conflicts: int = 0
    batches_committed: int = 0
    continuation_trigger_writes_attempted: int = 0
    continuation_trigger_writes_inserted: int = 0
    continuation_trigger_replays: int = 0
    continuation_trigger_conflicts: int = 0
    continuation_trigger_batches_committed: int = 0
    research_handoffs_processed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "observation_writes_attempted": self.observation_writes_attempted,
            "observation_writes_inserted": self.observation_writes_inserted,
            "observation_replays": self.observation_replays,
            "observation_conflicts": self.observation_conflicts,
            "batches_committed": self.batches_committed,
            "continuation_trigger_writes_attempted": self.continuation_trigger_writes_attempted,
            "continuation_trigger_writes_inserted": self.continuation_trigger_writes_inserted,
            "continuation_trigger_replays": self.continuation_trigger_replays,
            "continuation_trigger_conflicts": self.continuation_trigger_conflicts,
            "continuation_trigger_batches_committed": self.continuation_trigger_batches_committed,
            "research_handoffs_processed": self.research_handoffs_processed,
            "errors": list(self.errors),
        }


def _defer_lifecycle(
    *,
    state: LiveDiscoveryPipelineStateV0,
    operations: list[DeferredOperationV0],
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
    state.kernel.ingest_lifecycle(observation)
    state.lifecycle_events_ingested += 1
    operations.append(
        MarketLifecycleWriteV0(
            acquisition_run_key=acquisition_run_key,
            event_key=event_key,
            source_provider=SOURCE_PROVIDER,
            observation=observation,
        )
    )


def _tracked_continuation_episode_v0(
    tracker: SignalPlaneEpisodeTrackerV0,
    *,
    token_mint: str,
    observed_at: int,
) -> MarketOpportunityEpisode | None:
    episode = tracker.active_by_token.get(token_mint)
    if episode is None:
        return None
    if episode.first_trigger_observed_at <= observed_at < episode.episode_closes_at:
        return episode
    return None


def process_canonical_chunk_signal_plane_v0(
    *,
    state: LiveDiscoveryPipelineStateV0,
    acquisition_run_key: str,
    carbon_output_path: Path,
    target_manifest_path: Path,
    discovery_start_wall_ns: int,
    discovery_close_wall_ns: int,
    episode_tracker: SignalPlaneEpisodeTrackerV0 | None = None,
) -> SignalChunkResultV0:
    """Process one decoded chunk with only signal-critical synchronous work.

    Observation persistence, continuation-trigger audit writes and Research Plane work
    are emitted as deferred operations. Only opening/recovering the canonical episode
    plus the exact first-trigger T0/forward boundary remain synchronous.
    """
    episode_tracker = episode_tracker or SignalPlaneEpisodeTrackerV0()
    ordered, pairing_errors = _canonical_rows_in_receive_order(
        carbon_output_path=carbon_output_path,
        target_manifest_path=target_manifest_path,
    )
    state.semantic_errors.extend(pairing_errors)
    state.canonical_events_paired += len(ordered)
    unresolved_for_lookup: set[str] = set()
    operations: list[DeferredOperationV0] = []
    emitted_before = state.triggers_emitted
    first_before = state.first_trigger_episodes

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
            _defer_lifecycle(
                state=state,
                operations=operations,
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
            _defer_lifecycle(
                state=state,
                operations=operations,
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
        operations.append(
            MarketTradeWriteV0(
                acquisition_run_key=acquisition_run_key,
                event_key=event_key,
                source_provider=SOURCE_PROVIDER,
                observation=observation,
            )
        )
        try:
            trigger = state.kernel.ingest_trade(observation)
        except Exception as exc:
            state.semantic_errors.append(
                f"{event_key}:kernel:{type(exc).__name__}:{exc}"
            )
            continue
        state.market_trade_adapted_events += 1
        if trigger is None:
            continue

        state.triggers_emitted += 1
        chain_as_of = trigger.features.chain_as_of
        if chain_as_of is None:
            state.semantic_errors.append(f"{event_key}:trigger_missing_chain_as_of")
            continue
        trigger_key = f"{event_key}:market-radar:{trigger.trigger_kind}"
        trigger_observed_at = int(trigger.as_of)

        tracked_episode = _tracked_continuation_episode_v0(
            episode_tracker,
            token_mint=trigger.token_mint,
            observed_at=trigger_observed_at,
        )
        if tracked_episode is not None:
            operations.append(
                MarketContinuationTriggerWriteV0(
                    acquisition_run_key=acquisition_run_key,
                    episode_key=tracked_episode.episode_key,
                    trigger_key=trigger_key,
                    token_mint=trigger.token_mint,
                    trigger_kind=trigger.trigger_kind,
                    direction=trigger.direction,
                    chain_time=int(chain_as_of),
                    observed_at=trigger_observed_at,
                    method_version=trigger.method_version,
                    venue=observation.venue,
                )
            )
            state.grouped_trigger_count += 1
            continue

        try:
            episode = assign_market_opportunity_trigger(
                acquisition_run_key=acquisition_run_key,
                trigger_key=trigger_key,
                token_mint=trigger.token_mint,
                trigger_kind=trigger.trigger_kind,
                direction=trigger.direction,
                chain_time=int(chain_as_of),
                observed_at=trigger_observed_at,
                method_version=trigger.method_version,
                venue=observation.venue,
            )
            episode_tracker.active_by_token[trigger.token_mint] = episode
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
            boundary = seal_market_activity_discovery_signal_boundary_v0(episode)
            episode = boundary.episode
            episode_tracker.active_by_token[trigger.token_mint] = episode
            state.signal_boundaries_sealed += 1
        except Exception as exc:
            state.persistence_errors.append(
                f"{event_key}:signal_boundary:{type(exc).__name__}:{exc}"
            )
            continue

        try:
            handoff = build_market_activity_discovery_handoff_v0(
                episode=episode,
                trigger_key=trigger_key,
            )
            if handoff is None:
                raise RuntimeError("canonical first trigger did not produce a handoff")
            operations.append(DeferredResearchHandoffV0(handoff=handoff))
        except Exception as exc:
            state.research_errors.append(
                f"{event_key}:research_handoff_build:{type(exc).__name__}:{exc}"
            )

    return SignalChunkResultV0(
        unresolved_pools=tuple(sorted(unresolved_for_lookup)),
        deferred_operations=tuple(operations),
        emitted_trigger_count=state.triggers_emitted - emitted_before,
        first_trigger_count=state.first_trigger_episodes - first_before,
    )


def drain_deferred_operations_v0(
    operations: Sequence[DeferredOperationV0],
    *,
    state: DurableResearchStateV0 | None = None,
    max_observation_batch_size: int = 256,
    max_continuation_trigger_batch_size: int = 512,
) -> DurableResearchStateV0:
    """Drain non-signal work outside the Signal Plane.

    Observation and continuation-trigger writes are independently batched. Before every
    Research handoff, both classes of earlier durable work are flushed so T0 sees the
    full observation prefix and trigger audit state preceding that first-trigger handoff.
    """
    if max_observation_batch_size <= 0:
        raise ValueError("max_observation_batch_size must be positive")
    if max_continuation_trigger_batch_size <= 0:
        raise ValueError("max_continuation_trigger_batch_size must be positive")
    state = state or DurableResearchStateV0()
    pending_observations: list[MarketObservationWriteV0] = []
    pending_continuations: list[MarketContinuationTriggerWriteV0] = []

    def flush_observations() -> None:
        if not pending_observations:
            return
        batch = tuple(pending_observations)
        pending_observations.clear()
        try:
            result = record_market_observations_batch_v0(batch)
            state.observation_writes_attempted += result.attempted
            state.observation_writes_inserted += result.inserted
            state.observation_replays += result.replayed
            state.observation_conflicts += result.conflicts
            state.batches_committed += 1
        except Exception as exc:
            state.errors.append(f"observation_batch:{type(exc).__name__}:{exc}")

    def flush_continuations() -> None:
        if not pending_continuations:
            return
        batch = tuple(pending_continuations)
        pending_continuations.clear()
        try:
            result = record_market_continuation_triggers_batch_v0(batch)
            state.continuation_trigger_writes_attempted += result.attempted
            state.continuation_trigger_writes_inserted += result.inserted
            state.continuation_trigger_replays += result.replayed
            state.continuation_trigger_conflicts += result.conflicts
            state.continuation_trigger_batches_committed += 1
        except Exception as exc:
            state.errors.append(f"continuation_trigger_batch:{type(exc).__name__}:{exc}")

    def flush_all() -> None:
        flush_observations()
        flush_continuations()

    for operation in operations:
        if isinstance(operation, (MarketTradeWriteV0, MarketLifecycleWriteV0)):
            pending_observations.append(operation)
            if len(pending_observations) >= max_observation_batch_size:
                flush_observations()
            continue
        if isinstance(operation, MarketContinuationTriggerWriteV0):
            pending_continuations.append(operation)
            if len(pending_continuations) >= max_continuation_trigger_batch_size:
                flush_continuations()
            continue
        if isinstance(operation, DeferredResearchHandoffV0):
            flush_all()
            try:
                result = process_market_activity_discovery_handoff_v0(operation.handoff)
                if result.provider_calls_performed != 0:
                    raise RuntimeError("Research Plane unexpectedly called a provider")
                state.research_handoffs_processed += 1
            except Exception as exc:
                state.errors.append(
                    f"research_handoff:{type(exc).__name__}:{exc}"
                )
            continue
        state.errors.append(f"unsupported_operation:{type(operation).__name__}")
    flush_all()
    return state
