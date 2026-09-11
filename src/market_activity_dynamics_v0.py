from __future__ import annotations

from dataclasses import dataclass
import math

from src.opportunity_snapshot_core import FlowWindowFeatures, OpportunitySnapshotCoreV1


MARKET_ACTIVITY_DYNAMICS_VERSION = "market_activity_dynamics_v0_discovery"
REQUIRED_CUMULATIVE_WINDOWS_SECONDS = (10, 30, 60, 300)


@dataclass(frozen=True)
class MarketActivityIntervalV0:
    start_offset_seconds: int
    end_offset_seconds: int
    duration_seconds: int
    observed_event_count: int
    observed_buy_count: int
    observed_sell_count: int
    observed_event_rate_per_second: float
    observed_buy_rate_per_second: float
    observed_sell_rate_per_second: float
    observed_total_notional_usd: float | None
    observed_signed_notional_usd: float | None
    observed_total_notional_rate_usd_per_second: float | None
    observed_signed_notional_rate_usd_per_second: float | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class MarketActivityRateComparisonV0:
    recent_interval: str
    prior_interval: str
    observed_event_rate_ratio: float | None
    observed_buy_rate_ratio: float | None
    observed_sell_rate_ratio: float | None
    observed_total_notional_rate_ratio: float | None


@dataclass(frozen=True)
class MarketActivityParticipantContextV0:
    cumulative_window_seconds: int
    observed_event_count: int
    unique_buy_wallet_count: int
    unique_sell_wallet_count: int
    wallet_identity_coverage_pct: float | None
    repeated_wallet_event_share_pct: float | None


@dataclass(frozen=True)
class MarketActivityDynamicsV0:
    method_version: str
    token_mint: str
    as_of: int
    chain_as_of: int | None
    intervals: tuple[MarketActivityIntervalV0, ...]
    adjacent_rate_comparisons: tuple[MarketActivityRateComparisonV0, ...]
    participant_context: tuple[MarketActivityParticipantContextV0, ...]
    data_quality_flags: tuple[str, ...]


def _finite_non_negative(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _window_index(snapshot: OpportunitySnapshotCoreV1) -> dict[int, FlowWindowFeatures]:
    indexed: dict[int, FlowWindowFeatures] = {}
    for window in snapshot.flow_windows:
        seconds = int(window.window_seconds)
        if seconds in indexed:
            raise ValueError("duplicate cumulative flow window")
        indexed[seconds] = window
    missing = [item for item in REQUIRED_CUMULATIVE_WINDOWS_SECONDS if item not in indexed]
    if missing:
        raise ValueError(f"missing required cumulative flow windows: {missing}")
    return indexed


def _window_total_notional(window: FlowWindowFeatures) -> float | None:
    if window.buy_notional_usd is None or window.sell_notional_usd is None:
        return None
    buy = _finite_non_negative(window.buy_notional_usd, "buy_notional_usd")
    sell = _finite_non_negative(window.sell_notional_usd, "sell_notional_usd")
    return buy + sell


def _difference_count(outer: int, inner: int, name: str) -> int:
    value = int(outer) - int(inner)
    if value < 0:
        raise ValueError(f"nested cumulative {name} decreased")
    return value


def _difference_total_notional(
    *,
    outer: FlowWindowFeatures,
    inner: FlowWindowFeatures | None,
) -> tuple[float | None, float | None]:
    outer_total = _window_total_notional(outer)
    outer_signed = outer.signed_notional_usd
    if inner is None:
        if outer_total is None or outer_signed is None:
            return None, None
        signed = float(outer_signed)
        if not math.isfinite(signed):
            raise ValueError("signed_notional_usd must be finite when present")
        return outer_total, signed

    inner_total = _window_total_notional(inner)
    inner_signed = inner.signed_notional_usd
    if (
        outer_total is None
        or inner_total is None
        or outer_signed is None
        or inner_signed is None
    ):
        return None, None

    total = outer_total - inner_total
    if total < -1e-9:
        raise ValueError("nested cumulative total notional decreased")
    total = max(0.0, total)
    signed = float(outer_signed) - float(inner_signed)
    if not math.isfinite(signed):
        raise ValueError("derived signed notional must be finite")
    return total, signed


def _build_interval(
    *,
    start: int,
    end: int,
    outer: FlowWindowFeatures,
    inner: FlowWindowFeatures | None,
) -> MarketActivityIntervalV0:
    duration = end - start
    if duration <= 0:
        raise ValueError("activity interval duration must be positive")

    inner_events = int(inner.event_count) if inner is not None else 0
    inner_buys = int(inner.buy_count) if inner is not None else 0
    inner_sells = int(inner.sell_count) if inner is not None else 0
    events = _difference_count(outer.event_count, inner_events, "event_count")
    buys = _difference_count(outer.buy_count, inner_buys, "buy_count")
    sells = _difference_count(outer.sell_count, inner_sells, "sell_count")
    if buys + sells != events:
        raise ValueError("derived buy_count + sell_count must equal event_count")

    total_notional, signed_notional = _difference_total_notional(outer=outer, inner=inner)
    flags = set(outer.data_quality_flags)
    if inner is not None:
        flags.update(inner.data_quality_flags)
    if events > 0 and total_notional is None:
        flags.add("interval_notional_unavailable_from_cumulative_coverage")

    return MarketActivityIntervalV0(
        start_offset_seconds=start,
        end_offset_seconds=end,
        duration_seconds=duration,
        observed_event_count=events,
        observed_buy_count=buys,
        observed_sell_count=sells,
        observed_event_rate_per_second=events / float(duration),
        observed_buy_rate_per_second=buys / float(duration),
        observed_sell_rate_per_second=sells / float(duration),
        observed_total_notional_usd=total_notional,
        observed_signed_notional_usd=signed_notional,
        observed_total_notional_rate_usd_per_second=(
            total_notional / float(duration) if total_notional is not None else None
        ),
        observed_signed_notional_rate_usd_per_second=(
            signed_notional / float(duration) if signed_notional is not None else None
        ),
        data_quality_flags=tuple(sorted(flags)),
    )


def _safe_ratio(recent: float | None, prior: float | None) -> float | None:
    if recent is None or prior is None or prior <= 0:
        return None
    value = recent / prior
    return value if math.isfinite(value) else None


def _label(interval: MarketActivityIntervalV0) -> str:
    return f"{interval.start_offset_seconds}_{interval.end_offset_seconds}s"


def _compare(
    recent: MarketActivityIntervalV0,
    prior: MarketActivityIntervalV0,
) -> MarketActivityRateComparisonV0:
    return MarketActivityRateComparisonV0(
        recent_interval=_label(recent),
        prior_interval=_label(prior),
        observed_event_rate_ratio=_safe_ratio(
            recent.observed_event_rate_per_second,
            prior.observed_event_rate_per_second,
        ),
        observed_buy_rate_ratio=_safe_ratio(
            recent.observed_buy_rate_per_second,
            prior.observed_buy_rate_per_second,
        ),
        observed_sell_rate_ratio=_safe_ratio(
            recent.observed_sell_rate_per_second,
            prior.observed_sell_rate_per_second,
        ),
        observed_total_notional_rate_ratio=_safe_ratio(
            recent.observed_total_notional_rate_usd_per_second,
            prior.observed_total_notional_rate_usd_per_second,
        ),
    )


def build_market_activity_dynamics_v0(
    snapshot: OpportunitySnapshotCoreV1,
) -> MarketActivityDynamicsV0:
    """Derive score-free T0 market activity dynamics from existing cumulative windows.

    Counts describe observations available in the frozen snapshot; they do not claim chain-complete
    intensity. Unique-wallet counts remain cumulative context and are never subtracted across nested
    windows because the same wallet may participate in more than one interval.
    """

    if not snapshot.token_mint.strip():
        raise ValueError("snapshot token_mint cannot be empty")
    if int(snapshot.as_of) < 0:
        raise ValueError("snapshot as_of must be non-negative")
    if snapshot.chain_as_of is not None and int(snapshot.chain_as_of) < 0:
        raise ValueError("snapshot chain_as_of must be non-negative when present")

    windows = _window_index(snapshot)
    w10, w30, w60, w300 = (windows[item] for item in REQUIRED_CUMULATIVE_WINDOWS_SECONDS)
    intervals = (
        _build_interval(start=0, end=10, outer=w10, inner=None),
        _build_interval(start=10, end=30, outer=w30, inner=w10),
        _build_interval(start=30, end=60, outer=w60, inner=w30),
        _build_interval(start=60, end=300, outer=w300, inner=w60),
    )
    comparisons = (
        _compare(intervals[0], intervals[1]),
        _compare(intervals[1], intervals[2]),
        _compare(intervals[2], intervals[3]),
    )
    participant_context = tuple(
        MarketActivityParticipantContextV0(
            cumulative_window_seconds=window.window_seconds,
            observed_event_count=window.event_count,
            unique_buy_wallet_count=window.unique_buy_wallet_count,
            unique_sell_wallet_count=window.unique_sell_wallet_count,
            wallet_identity_coverage_pct=window.wallet_identity_coverage_pct,
            repeated_wallet_event_share_pct=window.repeated_wallet_event_share_pct,
        )
        for window in (w10, w30, w60)
    )

    flags = set(snapshot.data_quality_flags)
    flags.add("observed_activity_only_no_chain_completeness_claim")
    for interval in intervals:
        flags.update(interval.data_quality_flags)
    if sum(item.observed_event_count for item in intervals) == 0:
        flags.add("no_observed_activity_not_proven_true_zero")

    return MarketActivityDynamicsV0(
        method_version=MARKET_ACTIVITY_DYNAMICS_VERSION,
        token_mint=snapshot.token_mint,
        as_of=int(snapshot.as_of),
        chain_as_of=(int(snapshot.chain_as_of) if snapshot.chain_as_of is not None else None),
        intervals=intervals,
        adjacent_rate_comparisons=comparisons,
        participant_context=participant_context,
        data_quality_flags=tuple(sorted(flags)),
    )
