"""Score-free Market-First intelligence baseline.

This module composes already-validated causal protocol facts and opportunity snapshot
features into one immutable research surface. It intentionally does NOT assign an
opportunity score, confidence, recommendation, TAKE/SKIP action, or social evidence.

The baseline is descriptive. It answers questions such as:
- what lifecycle/protocol state was causally known at T0?
- how intense and directionally imbalanced was observed flow?
- how broad/repetitive was participant activity where identity coverage permits it?
- what price response was observed over the same causal window?
- what executable quote/liquidity/impact evidence was actually available?
- when same-unit quote flow/reserve evidence exists, how large was flow relative to
  the event-reported liquidity surface?

The generic FlowTradeObservation still carries USD notional while protocol reserves
can be raw token/quote units, so those quantities are never divided. Optional
``MatchedUnitFlowFactsV0`` closes that dimensional gap only when numerator and
denominator are explicitly expressed in the same quote asset and raw unit.
"""

from dataclasses import dataclass

from src.market_protocol_facts import MarketProtocolFactsV0
from src.matched_unit_flow import MatchedUnitFlowFactsV0
from src.opportunity_snapshot_core import (
    ExecutionSurfaceFeatures,
    FlowWindowFeatures,
    OpportunitySnapshotCoreV1,
)


MARKET_INTELLIGENCE_BASELINE_VERSION = (
    "market_intelligence_baseline_v0_1_matched_unit_flow"
)


@dataclass(frozen=True)
class MarketWindowMicrostructureFactsV0:
    window_seconds: int
    event_count: int
    event_rate_per_second: float
    buy_count: int
    sell_count: int
    buy_event_share_pct: float | None
    event_imbalance_pct: float | None
    unique_buy_wallet_count: int
    unique_sell_wallet_count: int
    wallet_identity_coverage_pct: float | None
    repeated_wallet_event_share_pct: float | None
    notional_coverage_pct: float | None
    signed_notional_usd: float | None
    notional_imbalance_pct: float | None
    price_coverage_pct: float | None
    return_pct: float | None
    median_observation_lag_seconds: float | None
    max_observation_lag_seconds: int | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class MarketIntelligenceBaselineV0:
    method_version: str
    token_mint: str
    as_of: int
    lifecycle_label: str
    protocol: MarketProtocolFactsV0
    windows: tuple[MarketWindowMicrostructureFactsV0, ...]
    execution: ExecutionSurfaceFeatures
    matched_unit_flow: MatchedUnitFlowFactsV0 | None
    liquidity_normalized_flow_available: bool
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _window_facts(window: FlowWindowFeatures) -> MarketWindowMicrostructureFactsV0:
    event_count = int(window.event_count)
    directional_count = int(window.buy_count) + int(window.sell_count)
    buy_share = (
        100.0 * float(window.buy_count) / directional_count
        if directional_count > 0
        else None
    )
    event_imbalance = (
        100.0 * (float(window.buy_count) - float(window.sell_count)) / directional_count
        if directional_count > 0
        else None
    )
    return MarketWindowMicrostructureFactsV0(
        window_seconds=int(window.window_seconds),
        event_count=event_count,
        event_rate_per_second=event_count / float(window.window_seconds),
        buy_count=int(window.buy_count),
        sell_count=int(window.sell_count),
        buy_event_share_pct=buy_share,
        event_imbalance_pct=event_imbalance,
        unique_buy_wallet_count=int(window.unique_buy_wallet_count),
        unique_sell_wallet_count=int(window.unique_sell_wallet_count),
        wallet_identity_coverage_pct=window.wallet_identity_coverage_pct,
        repeated_wallet_event_share_pct=window.repeated_wallet_event_share_pct,
        notional_coverage_pct=window.notional_coverage_pct,
        signed_notional_usd=window.signed_notional_usd,
        notional_imbalance_pct=window.notional_imbalance_pct,
        price_coverage_pct=window.price_coverage_pct,
        return_pct=window.return_pct,
        median_observation_lag_seconds=window.median_observation_lag_seconds,
        max_observation_lag_seconds=window.max_observation_lag_seconds,
        data_quality_flags=tuple(window.data_quality_flags),
    )


def build_market_intelligence_baseline_v0(
    *,
    protocol: MarketProtocolFactsV0,
    snapshot: OpportunitySnapshotCoreV1,
    matched_unit_flow: MatchedUnitFlowFactsV0 | None = None,
) -> MarketIntelligenceBaselineV0:
    """Compose causal Market-First facts known at the same exact T0.

    Inputs must already have been built causally. This boundary refuses token or clock
    mismatches rather than silently joining evidence from different snapshots.
    Social/event evidence is intentionally outside this type and remains an independent
    research track.
    """

    if protocol.token_mint != snapshot.token_mint:
        raise ValueError("protocol and snapshot token_mint must match")
    if protocol.as_of != snapshot.as_of:
        raise ValueError("protocol and snapshot as_of must match exactly")
    if matched_unit_flow is not None:
        if matched_unit_flow.token_mint != protocol.token_mint:
            raise ValueError("matched_unit_flow token_mint must match baseline token")
        if matched_unit_flow.as_of != protocol.as_of:
            raise ValueError("matched_unit_flow as_of must match baseline as_of exactly")

    windows = tuple(_window_facts(window) for window in snapshot.flow_windows)

    quality = set(protocol.data_quality_flags)
    quality.update(snapshot.data_quality_flags)
    for window in windows:
        quality.update(window.data_quality_flags)
    quality.update(snapshot.execution.data_quality_flags)

    matched_available = bool(matched_unit_flow and matched_unit_flow.available)
    if matched_unit_flow is not None:
        quality.update(matched_unit_flow.data_quality_flags)
        for surface in matched_unit_flow.surface_windows:
            quality.update(surface.data_quality_flags)
    if not matched_available:
        quality.add("matched_unit_liquidity_normalized_flow_unavailable")

    if not windows:
        quality.add("flow_windows_unavailable")

    provenance = list(protocol.provenance_keys)
    if matched_unit_flow is not None:
        provenance.extend(matched_unit_flow.provenance_keys)

    return MarketIntelligenceBaselineV0(
        method_version=MARKET_INTELLIGENCE_BASELINE_VERSION,
        token_mint=protocol.token_mint,
        as_of=protocol.as_of,
        lifecycle_label=protocol.lifecycle_label,
        protocol=protocol,
        windows=windows,
        execution=snapshot.execution,
        matched_unit_flow=matched_unit_flow,
        liquidity_normalized_flow_available=matched_available,
        provenance_keys=tuple(dict.fromkeys(provenance)),
        data_quality_flags=tuple(sorted(quality)),
    )
