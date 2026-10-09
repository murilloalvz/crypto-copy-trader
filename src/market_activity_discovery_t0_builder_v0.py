"""Provider-free T0 builder for Market Activity Discovery V0.

This Research Plane helper reconstructs no future evidence. It reads only trade rows from
the same acquisition run that were locally available by the canonical episode's first
trigger observation, anchors market windows to the first trigger chain time, deliberately
uses no global quote store, and leaves unavailable protocol/Mayhem evidence explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.market_activity_dynamics_v0 import (
    MarketActivityDynamicsV0,
    build_market_activity_dynamics_v0,
)
from src.market_intelligence_baseline import (
    MarketIntelligenceBaselineV0,
    build_market_intelligence_baseline_v0,
)
from src.market_observation_store import StoredMarketTrade, load_market_trades
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.market_protocol_facts import build_market_protocol_facts_v0
from src.opportunity_snapshot_core import (
    FlowTradeObservation,
    OpportunitySnapshotCoreV1,
    build_opportunity_snapshot_core_v1,
)
from src.pump_creation_mode_facts import (
    PumpCreationModeFactsV0,
    build_pump_creation_mode_facts_v0,
)


MARKET_ACTIVITY_DISCOVERY_T0_BUILDER_VERSION = (
    "market_activity_discovery_t0_builder_v0_first_trigger_run_scoped"
)
EXECUTION_CONTEXT_POLICY = "MISSING_NO_RUN_SCOPED_QUOTE_SOURCE_V0"
PROTOCOL_CONTEXT_POLICY = "MISSING_NO_RUN_SCOPED_PROTOCOL_SOURCE_V0"
PUMP_CREATION_MODE_POLICY = "MISSING_NO_RUN_SCOPED_CREATE_V2_SOURCE_V0"


@dataclass(frozen=True)
class MarketActivityDiscoveryT0BuildV0:
    method_version: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    decision_as_of: int
    chain_as_of: int
    flow_row_count: int
    flow_event_keys: tuple[str, ...]
    flow_source_providers: tuple[str, ...]
    execution_context_policy: str
    protocol_context_policy: str
    pump_creation_mode_policy: str
    provider_calls_performed: int
    opportunity_snapshot: OpportunitySnapshotCoreV1
    market_intelligence: MarketIntelligenceBaselineV0
    pump_creation_mode: PumpCreationModeFactsV0
    activity_dynamics: MarketActivityDynamicsV0


def _to_flow(row: StoredMarketTrade) -> FlowTradeObservation:
    item = row.observation
    return FlowTradeObservation(
        token_mint=item.token_mint,
        side=item.side,
        chain_time=int(item.chain_time),
        observed_at=int(item.observed_at),
        wallet_address=item.wallet_address,
        notional_usd=item.notional_usd,
        price_usd=item.price_usd,
    )


def build_market_activity_discovery_t0_v0(
    episode: MarketOpportunityEpisode,
) -> MarketActivityDiscoveryT0BuildV0:
    """Build exact first-trigger T0 from same-run persisted market trades only.

    No quote/provider/protocol API is called. ``decision_as_of`` and ``chain_as_of`` are
    copied from the canonical episode's independent local/chain first-trigger clocks.
    The global causal quote store is intentionally not read because it is not scoped by
    ``acquisition_run_key`` and could contaminate a fresh research run.
    """

    if not episode.acquisition_run_key.strip() or not episode.episode_key.strip():
        raise ValueError("episode run/key identity cannot be empty")
    if not episode.token_mint.strip():
        raise ValueError("episode token_mint cannot be empty")
    decision_as_of = int(episode.first_trigger_observed_at)
    chain_as_of = int(episode.first_trigger_chain_time)
    if decision_as_of < 0 or chain_as_of < 0:
        raise ValueError("episode first-trigger clocks must be non-negative")

    chain_after = chain_as_of - 300 if chain_as_of >= 300 else None
    stored_rows = load_market_trades(
        acquisition_run_key=episode.acquisition_run_key,
        token_mint=episode.token_mint,
        as_of=decision_as_of,
        chain_time_after=chain_after,
    )
    # Defensive upper-chain filter. The store query intentionally has no chain upper bound;
    # the snapshot builder also enforces the same anchor, but provenance must describe only
    # rows actually eligible for this T0.
    eligible_rows = tuple(
        row for row in stored_rows if int(row.observation.chain_time) <= chain_as_of
    )
    flow = tuple(_to_flow(row) for row in eligible_rows)

    core = build_opportunity_snapshot_core_v1(
        token_mint=episode.token_mint,
        as_of=decision_as_of,
        chain_as_of=chain_as_of,
        flow_observations=flow,
        quotes=(),
        flow_windows_seconds=(10, 30, 60, 300),
    )
    protocol = build_market_protocol_facts_v0(
        token_mint=episode.token_mint,
        as_of=decision_as_of,
    )
    baseline = build_market_intelligence_baseline_v0(
        protocol=protocol,
        snapshot=core,
    )
    flow_event_keys = tuple(row.event_key for row in eligible_rows)
    flow_sources = tuple(dict.fromkeys(row.source_provider for row in eligible_rows))
    provenance = tuple(dict.fromkeys((*baseline.provenance_keys, *flow_event_keys)))
    quality = set(baseline.data_quality_flags)
    quality.update(
        {
            "market_activity_discovery_run_scoped_flow_only",
            "execution_context_missing_no_run_scoped_quote_source",
            "protocol_context_missing_no_run_scoped_protocol_source",
            "pump_creation_mode_missing_no_run_scoped_create_v2_source",
        }
    )
    baseline = replace(
        baseline,
        provenance_keys=provenance,
        data_quality_flags=tuple(sorted(quality)),
    )
    pump_creation_mode = build_pump_creation_mode_facts_v0(
        token_mint=episode.token_mint,
        as_of=decision_as_of,
    )
    activity = build_market_activity_dynamics_v0(core)

    if baseline.as_of != decision_as_of or activity.as_of != decision_as_of:
        raise RuntimeError("T0 builder produced a local clock mismatch")
    if baseline.chain_as_of != chain_as_of or activity.chain_as_of != chain_as_of:
        raise RuntimeError("T0 builder produced a chain anchor mismatch")

    return MarketActivityDiscoveryT0BuildV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_T0_BUILDER_VERSION,
        acquisition_run_key=episode.acquisition_run_key,
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        decision_as_of=decision_as_of,
        chain_as_of=chain_as_of,
        flow_row_count=len(eligible_rows),
        flow_event_keys=flow_event_keys,
        flow_source_providers=flow_sources,
        execution_context_policy=EXECUTION_CONTEXT_POLICY,
        protocol_context_policy=PROTOCOL_CONTEXT_POLICY,
        pump_creation_mode_policy=PUMP_CREATION_MODE_POLICY,
        provider_calls_performed=0,
        opportunity_snapshot=core,
        market_intelligence=baseline,
        pump_creation_mode=pump_creation_mode,
        activity_dynamics=activity,
    )
