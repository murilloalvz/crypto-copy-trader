from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from src.market_opportunity_radar import MarketTradeObservation


TEMPORAL_FLOW_STRUCTURE_VERSION = "temporal_flow_structure_v1_t0_anchored_dual_clock"


@dataclass(frozen=True)
class TemporalFlowStructureWindow:
    """Outcome-blind temporal shape of market events before an episode market anchor.

    The market window is anchored independently from the knowledge cutoff. Future use should
    normally set ``market_anchor_time`` to episode T0 and ``knowledge_as_of`` to the corresponding
    research decision cutoff. This makes the feature insensitive to variable pipeline latency while
    still excluding observations that were not known by decision time.

    No economic direction is assigned to burstiness, persistence, or late activity.
    """

    method_version: str
    token_mint: str
    market_anchor_time: int
    knowledge_as_of: int
    lookback_seconds: int
    subwindow_seconds: int
    market_event_count: int
    buy_event_count: int
    sell_event_count: int
    subwindow_event_counts: tuple[int, ...]
    subwindow_buy_counts: tuple[int, ...]
    subwindow_sell_counts: tuple[int, ...]
    active_subwindow_count: int
    active_subwindow_share_pct: float
    max_subwindow_event_share_pct: float | None
    temporal_event_hhi: float | None
    early_half_event_count: int
    late_half_event_count: int
    late_event_share_pct: float | None
    late_to_early_event_ratio: float | None
    buy_active_subwindow_count: int
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_trade(item: MarketTradeObservation) -> None:
    _required(item.token_mint, "trade token_mint")
    if item.side not in {"buy", "sell"}:
        raise ValueError("trade side must be buy or sell")
    if int(item.chain_time) < 0 or int(item.observed_at) < 0:
        raise ValueError("trade timestamps must be non-negative")
    if int(item.observed_at) < int(item.chain_time):
        raise ValueError("trade observed_at cannot precede chain_time")


def _hhi(counts: tuple[int, ...], total: int) -> float | None:
    if total <= 0:
        return None
    value = sum((count / total) ** 2 for count in counts)
    return value if math.isfinite(value) else None


def build_temporal_flow_structure_window(
    *,
    token_mint: str,
    market_anchor_time: int,
    knowledge_as_of: int,
    lookback_seconds: int,
    subwindow_seconds: int,
    observations: Iterable[MarketTradeObservation],
) -> TemporalFlowStructureWindow:
    """Measure pre-anchor temporal persistence with explicit market and knowledge clocks.

    Market membership is ``anchor-lookback < chain_time <= anchor`` and knowledge membership is
    ``observed_at <= knowledge_as_of``. The lookback must divide evenly into an even number of
    subwindows so early/late halves have identical duration.
    """

    token = _required(token_mint, "token_mint")
    anchor = int(market_anchor_time)
    cutoff = int(knowledge_as_of)
    lookback = int(lookback_seconds)
    width = int(subwindow_seconds)
    if anchor < 0 or cutoff < 0:
        raise ValueError("market and knowledge timestamps must be non-negative")
    if anchor > cutoff:
        raise ValueError("market_anchor_time cannot be after knowledge_as_of")
    if lookback <= 0 or width <= 0:
        raise ValueError("lookback_seconds and subwindow_seconds must be positive")
    if lookback % width != 0:
        raise ValueError("lookback_seconds must be divisible by subwindow_seconds")
    bin_count = lookback // width
    if bin_count < 2 or bin_count % 2 != 0:
        raise ValueError("temporal structure requires an even number of at least two subwindows")

    lower_bound = anchor - lookback
    event_counts = [0] * bin_count
    buy_counts = [0] * bin_count
    sell_counts = [0] * bin_count

    for item in observations:
        _validate_trade(item)
        if item.token_mint != token:
            continue
        chain_time = int(item.chain_time)
        observed_at = int(item.observed_at)
        if not (lower_bound < chain_time <= anchor and observed_at <= cutoff):
            continue

        # Intervals are (lower, lower+width], ..., (anchor-width, anchor].
        offset = chain_time - lower_bound
        index = min((offset - 1) // width, bin_count - 1)
        event_counts[index] += 1
        if item.side == "buy":
            buy_counts[index] += 1
        else:
            sell_counts[index] += 1

    total = sum(event_counts)
    buy_total = sum(buy_counts)
    sell_total = sum(sell_counts)
    active = sum(1 for count in event_counts if count > 0)
    buy_active = sum(1 for count in buy_counts if count > 0)
    max_share = 100.0 * max(event_counts) / total if total else None
    event_hhi = _hhi(tuple(event_counts), total)

    half = bin_count // 2
    early = sum(event_counts[:half])
    late = sum(event_counts[half:])
    late_share = 100.0 * late / total if total else None
    late_to_early = late / early if early > 0 else None
    if late_to_early is not None and not math.isfinite(late_to_early):
        late_to_early = None

    flags: list[str] = []
    if total == 0:
        flags.append("no_market_events_in_temporal_window")
    if total > 0 and active == 1:
        flags.append("all_market_events_in_single_subwindow")
    if early == 0 and late > 0:
        flags.append("late_to_early_ratio_unavailable_zero_early_events")

    return TemporalFlowStructureWindow(
        method_version=TEMPORAL_FLOW_STRUCTURE_VERSION,
        token_mint=token,
        market_anchor_time=anchor,
        knowledge_as_of=cutoff,
        lookback_seconds=lookback,
        subwindow_seconds=width,
        market_event_count=total,
        buy_event_count=buy_total,
        sell_event_count=sell_total,
        subwindow_event_counts=tuple(event_counts),
        subwindow_buy_counts=tuple(buy_counts),
        subwindow_sell_counts=tuple(sell_counts),
        active_subwindow_count=active,
        active_subwindow_share_pct=100.0 * active / bin_count,
        max_subwindow_event_share_pct=max_share,
        temporal_event_hhi=event_hhi,
        early_half_event_count=early,
        late_half_event_count=late,
        late_event_share_pct=late_share,
        late_to_early_event_ratio=late_to_early,
        buy_active_subwindow_count=buy_active,
        data_quality_flags=tuple(flags),
    )
