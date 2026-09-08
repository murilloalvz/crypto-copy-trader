from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Iterable

from src.market_opportunity_radar import MarketTradeObservation


PARTICIPANT_DISTRIBUTION_RESEARCH_VERSION = (
    "participant_distribution_research_v1_causal_event_structure"
)

_EPISTEMIC_CAUTIONS = (
    "distinct_addresses_are_not_independent_traders",
    "participant_concentration_is_descriptive_not_manipulation_evidence",
    "participant_repetition_is_descriptive_not_wash_trading_evidence",
)


@dataclass(frozen=True)
class ParticipantDistributionWindow:
    """Score-free participant-distribution evidence known by one causal cutoff.

    The builder intentionally exposes raw descriptive structure only. It does not assign an
    economic direction, threshold, label, score, or entry decision.

    Structural buyer metrics are emitted only when every BUY event in the window has wallet
    identity. Computing concentration on a selected known-wallet subset would systematically
    understate missing-identity uncertainty, so partial buyer identity makes those metrics
    unavailable instead of silently biased.
    """

    method_version: str
    token_mint: str
    as_of: int
    window_seconds: int
    market_event_count: int
    buy_event_count: int
    sell_event_count: int
    known_market_wallet_event_count: int
    known_unique_market_wallet_count: int
    market_wallet_identity_coverage_pct: float | None
    known_buy_wallet_event_count: int
    known_unique_buy_wallet_count: int
    buyer_wallet_identity_coverage_pct: float | None
    buyer_breadth_ratio: float | None
    buyer_repeated_event_share_pct: float | None
    top1_buyer_event_share_pct: float | None
    top3_buyer_event_share_pct: float | None
    participant_buy_event_hhi: float | None
    data_quality_flags: tuple[str, ...]
    epistemic_cautions: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _coverage_pct(known_count: int, total_count: int) -> float | None:
    if total_count <= 0:
        return None
    return 100.0 * known_count / total_count


def _validate_trade(item: MarketTradeObservation) -> None:
    _required(item.token_mint, "trade token_mint")
    if item.side not in {"buy", "sell"}:
        raise ValueError("trade side must be buy or sell")
    if int(item.chain_time) < 0 or int(item.observed_at) < 0:
        raise ValueError("trade timestamps must be non-negative")
    if int(item.observed_at) < int(item.chain_time):
        raise ValueError("trade observed_at cannot precede chain_time")
    if item.wallet_address is not None and not str(item.wallet_address).strip():
        raise ValueError("trade wallet_address cannot be blank")


def _top_k_event_share_pct(counts: Counter[str], *, total_events: int, k: int) -> float | None:
    if total_events <= 0 or not counts:
        return None
    top = sorted(counts.values(), reverse=True)[:k]
    return 100.0 * sum(top) / total_events


def _event_hhi(counts: Counter[str], *, total_events: int) -> float | None:
    """Return Herfindahl-Hirschman concentration over buyer event shares in [0, 1]."""

    if total_events <= 0 or not counts:
        return None
    value = sum((count / total_events) ** 2 for count in counts.values())
    if not math.isfinite(value):
        return None
    return value


def build_participant_distribution_window(
    *,
    token_mint: str,
    as_of: int,
    window_seconds: int,
    observations: Iterable[MarketTradeObservation],
) -> ParticipantDistributionWindow:
    """Measure causal participant distribution without changing radar or research decisions.

    Dual-clock inclusion rule:
    - market membership: ``as_of - window_seconds < chain_time <= as_of``;
    - knowledge membership: ``observed_at <= as_of``.

    A historical event discovered after ``as_of`` therefore cannot be backfilled into the
    feature. Observations for other tokens are ignored after validation.
    """

    token = _required(token_mint, "token_mint")
    cutoff = int(as_of)
    window = int(window_seconds)
    if cutoff < 0:
        raise ValueError("as_of must be non-negative")
    if window <= 0:
        raise ValueError("window_seconds must be positive")

    lower_bound = cutoff - window
    eligible: list[MarketTradeObservation] = []
    for item in observations:
        _validate_trade(item)
        if item.token_mint != token:
            continue
        if lower_bound < int(item.chain_time) <= cutoff and int(item.observed_at) <= cutoff:
            eligible.append(item)

    eligible.sort(
        key=lambda item: (
            int(item.chain_time),
            int(item.observed_at),
            item.transaction_key or "",
            item.wallet_address or "",
        )
    )

    buys = [item for item in eligible if item.side == "buy"]
    sells = [item for item in eligible if item.side == "sell"]

    market_wallet_events = [
        str(item.wallet_address) for item in eligible if item.wallet_address is not None
    ]
    buy_wallet_events = [
        str(item.wallet_address) for item in buys if item.wallet_address is not None
    ]

    market_coverage = _coverage_pct(len(market_wallet_events), len(eligible))
    buyer_coverage = _coverage_pct(len(buy_wallet_events), len(buys))

    known_market_wallets = set(market_wallet_events)
    known_buy_wallets = set(buy_wallet_events)

    buyer_identity_complete = bool(buys) and len(buy_wallet_events) == len(buys)
    buyer_counts: Counter[str] = Counter(buy_wallet_events)

    buyer_breadth_ratio = None
    buyer_repeated_share = None
    top1_share = None
    top3_share = None
    buyer_hhi = None
    if buyer_identity_complete:
        buy_count = len(buys)
        unique_buyers = len(known_buy_wallets)
        buyer_breadth_ratio = unique_buyers / buy_count
        buyer_repeated_share = 100.0 * (buy_count - unique_buyers) / buy_count
        top1_share = _top_k_event_share_pct(buyer_counts, total_events=buy_count, k=1)
        top3_share = _top_k_event_share_pct(buyer_counts, total_events=buy_count, k=3)
        buyer_hhi = _event_hhi(buyer_counts, total_events=buy_count)

    quality: list[str] = []
    if not eligible:
        quality.append("no_market_events_in_window")
    if eligible and len(market_wallet_events) < len(eligible):
        quality.append("partial_market_wallet_identity_coverage")
    if not buys:
        quality.append("no_buy_events_in_window")
    elif not buyer_identity_complete:
        quality.append("partial_buyer_wallet_identity_coverage")
        quality.append("buyer_structural_metrics_unavailable_due_to_partial_identity")

    return ParticipantDistributionWindow(
        method_version=PARTICIPANT_DISTRIBUTION_RESEARCH_VERSION,
        token_mint=token,
        as_of=cutoff,
        window_seconds=window,
        market_event_count=len(eligible),
        buy_event_count=len(buys),
        sell_event_count=len(sells),
        known_market_wallet_event_count=len(market_wallet_events),
        known_unique_market_wallet_count=len(known_market_wallets),
        market_wallet_identity_coverage_pct=market_coverage,
        known_buy_wallet_event_count=len(buy_wallet_events),
        known_unique_buy_wallet_count=len(known_buy_wallets),
        buyer_wallet_identity_coverage_pct=buyer_coverage,
        buyer_breadth_ratio=buyer_breadth_ratio,
        buyer_repeated_event_share_pct=buyer_repeated_share,
        top1_buyer_event_share_pct=top1_share,
        top3_buyer_event_share_pct=top3_share,
        participant_buy_event_hhi=buyer_hhi,
        data_quality_flags=tuple(quality),
        epistemic_cautions=_EPISTEMIC_CAUTIONS,
    )
