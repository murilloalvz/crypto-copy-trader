"""Score-free Market-First intelligence baseline.

This module composes already-validated causal protocol facts and opportunity snapshot
features into one immutable research surface. It intentionally does NOT assign an
opportunity score, confidence, recommendation, TAKE/SKIP action, or social evidence.

Local ``as_of`` is the evidence-availability cutoff. Flow windows additionally carry
an explicit same-domain ``chain_as_of`` anchor; snapshot and matched-unit flow must
use the same anchor before their metrics can be joined.
"""

from dataclasses import dataclass

from src.market_protocol_facts import MarketProtocolFactsV0
from src.matched_unit_flow import MatchedUnitFlowFactsV0
from src.opportunity_snapshot_core import (
    ExecutionSurfaceFeatures,
    FlowWindowFeatures,
    OpportunitySnapshotCoreV1,
)


MARKET_INTELLIGENCE_BASELINE_VERSION = "market_intelligence_baseline_v0_2_clock_domains"


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
    chain_as_of: int | None
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
    """Compose causal Market-First facts known at one local T0 and chain anchor."""

    if protocol.token_mint != snapshot.token_mint:
        raise ValueError("protocol and snapshot token_mint must match")
    if protocol.as_of != snapshot.as_of:
        raise ValueError("protocol and snapshot as_of must match exactly")
    if matched_unit_flow is not None:
        if matched_unit_flow.token_mint != protocol.token_mint:
            raise ValueError("matched_unit_flow token_mint must match baseline token")
        if matched_unit_flow.as_of != protocol.as_of:
            raise ValueError("matched_unit_flow as_of must match baseline as_of exactly")
        if matched_unit_flow.chain_as_of != snapshot.chain_as_of:
            raise ValueError(
                "matched_unit_flow chain_as_of must match snapshot chain_as_of exactly"
            )

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
        chain_as_of=snapshot.chain_as_of,
        lifecycle_label=protocol.lifecycle_label,
        protocol=protocol,
        windows=windows,
        execution=snapshot.execution,
        matched_unit_flow=matched_unit_flow,
        liquidity_normalized_flow_available=matched_available,
        provenance_keys=tuple(dict.fromkeys(provenance)),
        data_quality_flags=tuple(sorted(quality)),
    )
