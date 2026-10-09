from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from src.market_observation_store import StoredMarketTrade, load_market_trades


EXCEPTIONAL_TRADE_PREENTRY_VERSION = "exceptional_trade_preentry_v56_dual_cutoff"
DEFAULT_PREENTRY_WINDOWS_SECONDS = (10, 30, 60, 300)


@dataclass(frozen=True)
class ExceptionalTradeReferenceV56:
    """One wallet entry used only as a causal reference clock.

    This object deliberately contains no profit/outcome label. Outcome labels must remain in a
    separate research layer so future information cannot leak into feature construction.
    """

    reference_key: str
    acquisition_run_key: str
    wallet_address: str
    token_mint: str
    entry_chain_time: int
    entry_observed_at: int


@dataclass(frozen=True)
class PreEntryParticipationWindowV56:
    window_seconds: int
    event_count: int
    buy_count: int
    sell_count: int
    wallet_identity_coverage_pct: float | None
    unique_wallet_count: int | None
    unique_buy_wallet_count: int | None
    unique_sell_wallet_count: int | None
    repeated_wallet_event_share_pct: float | None
    top1_wallet_event_share_pct: float | None
    top3_wallet_event_share_pct: float | None
    buy_sell_wallet_overlap_count: int | None
    buy_sell_wallet_overlap_share_pct: float | None
    notional_coverage_pct: float | None
    buy_notional_share_pct: float | None
    price_coverage_pct: float | None
    return_pct: float | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class ExceptionalTradePreEntrySnapshotV56:
    method_version: str
    reference_key: str
    acquisition_run_key: str
    wallet_address: str
    token_mint: str
    market_cutoff_chain_time: int
    knowledge_cutoff_observed_at: int
    windows: tuple[PreEntryParticipationWindowV56, ...]
    candidate_rows_seen: int
    rows_strictly_preentry: int
    excluded_same_or_later_market_time: int
    excluded_not_known_before_entry: int
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def validate_reference_v56(reference: ExceptionalTradeReferenceV56) -> None:
    _required(reference.reference_key, "reference_key")
    _required(reference.acquisition_run_key, "acquisition_run_key")
    _required(reference.wallet_address, "wallet_address")
    _required(reference.token_mint, "token_mint")
    if reference.entry_chain_time < 0 or reference.entry_observed_at < 0:
        raise ValueError("entry clocks must be non-negative")
    if reference.entry_observed_at < reference.entry_chain_time:
        raise ValueError("entry_observed_at cannot precede entry_chain_time")


def _coverage(known: int, total: int) -> float | None:
    if total <= 0:
        return None
    return 100.0 * known / total


def _window(
    rows: list[StoredMarketTrade],
    *,
    reference: ExceptionalTradeReferenceV56,
    window_seconds: int,
) -> PreEntryParticipationWindowV56:
    lower = reference.entry_chain_time - window_seconds
    eligible = [
        item
        for item in rows
        if lower < item.observation.chain_time < reference.entry_chain_time
        and item.observation.observed_at < reference.entry_observed_at
    ]
    eligible.sort(
        key=lambda item: (
            item.observation.chain_time,
            item.observation.observed_at,
            item.event_key,
        )
    )

    buys = [item for item in eligible if item.observation.side == "buy"]
    sells = [item for item in eligible if item.observation.side == "sell"]

    known_wallet_rows = [item for item in eligible if item.observation.wallet_address]
    wallet_coverage = _coverage(len(known_wallet_rows), len(eligible))
    wallets_complete = bool(eligible) and len(known_wallet_rows) == len(eligible)

    unique_wallet_count = None
    unique_buy_wallet_count = None
    unique_sell_wallet_count = None
    repeated_share = None
    top1_share = None
    top3_share = None
    overlap_count = None
    overlap_share = None

    if wallets_complete:
        wallet_events = [str(item.observation.wallet_address) for item in eligible]
        wallet_counts: dict[str, int] = {}
        for wallet in wallet_events:
            wallet_counts[wallet] = wallet_counts.get(wallet, 0) + 1
        ordered_counts = sorted(wallet_counts.values(), reverse=True)
        unique_wallet_count = len(wallet_counts)
        unique_buy_wallets = {
            str(item.observation.wallet_address) for item in buys
        }
        unique_sell_wallets = {
            str(item.observation.wallet_address) for item in sells
        }
        unique_buy_wallet_count = len(unique_buy_wallets)
        unique_sell_wallet_count = len(unique_sell_wallets)
        repeated_share = 100.0 * (len(wallet_events) - len(wallet_counts)) / len(wallet_events)
        top1_share = 100.0 * ordered_counts[0] / len(wallet_events)
        top3_share = 100.0 * sum(ordered_counts[:3]) / len(wallet_events)
        overlap = unique_buy_wallets & unique_sell_wallets
        overlap_count = len(overlap)
        overlap_share = (
            100.0 * len(overlap) / len(wallet_counts) if wallet_counts else None
        )

    known_notionals = [item for item in eligible if item.observation.notional_usd is not None]
    notional_coverage = _coverage(len(known_notionals), len(eligible))
    notionals_complete = bool(eligible) and len(known_notionals) == len(eligible)
    buy_notional_share = None
    if notionals_complete:
        buy_notional = sum(float(item.observation.notional_usd or 0.0) for item in buys)
        sell_notional = sum(float(item.observation.notional_usd or 0.0) for item in sells)
        total_notional = buy_notional + sell_notional
        if total_notional > 0:
            buy_notional_share = 100.0 * buy_notional / total_notional

    known_prices = [item for item in eligible if item.observation.price_usd is not None]
    price_coverage = _coverage(len(known_prices), len(eligible))
    prices_complete = bool(eligible) and len(known_prices) == len(eligible)
    return_pct = None
    if prices_complete and len(eligible) >= 2:
        first = float(eligible[0].observation.price_usd or 0.0)
        last = float(eligible[-1].observation.price_usd or 0.0)
        if first > 0 and last > 0:
            value = 100.0 * (last / first - 1.0)
            return_pct = value if math.isfinite(value) else None

    flags: list[str] = []
    if not eligible:
        flags.append("no_strictly_preentry_events")
    if eligible and not wallets_complete:
        flags.append("partial_wallet_identity_coverage")
    if eligible and not notionals_complete:
        flags.append("partial_notional_coverage")
    if eligible and not prices_complete:
        flags.append("partial_price_coverage")

    return PreEntryParticipationWindowV56(
        window_seconds=window_seconds,
        event_count=len(eligible),
        buy_count=len(buys),
        sell_count=len(sells),
        wallet_identity_coverage_pct=wallet_coverage,
        unique_wallet_count=unique_wallet_count,
        unique_buy_wallet_count=unique_buy_wallet_count,
        unique_sell_wallet_count=unique_sell_wallet_count,
        repeated_wallet_event_share_pct=repeated_share,
        top1_wallet_event_share_pct=top1_share,
        top3_wallet_event_share_pct=top3_share,
        buy_sell_wallet_overlap_count=overlap_count,
        buy_sell_wallet_overlap_share_pct=overlap_share,
        notional_coverage_pct=notional_coverage,
        buy_notional_share_pct=buy_notional_share,
        price_coverage_pct=price_coverage,
        return_pct=return_pct,
        data_quality_flags=tuple(flags),
    )


def build_exceptional_trade_preentry_snapshot_v56(
    *,
    reference: ExceptionalTradeReferenceV56,
    stored_trades: Iterable[StoredMarketTrade],
    windows_seconds: tuple[int, ...] = DEFAULT_PREENTRY_WINDOWS_SECONDS,
) -> ExceptionalTradePreEntrySnapshotV56:
    """Build a strict pre-entry market snapshot without using any future outcome label.

    Two independent cutoffs are enforced:
    - market time must be strictly before ``entry_chain_time``;
    - knowledge time must be strictly before ``entry_observed_at``.

    Same-second market events are deliberately excluded because this store does not provide a
    canonical within-second ordering relative to an external wallet entry. This is conservative and
    prevents target-entry or same-tick leakage.
    """

    validate_reference_v56(reference)
    if not windows_seconds or any(item <= 0 for item in windows_seconds):
        raise ValueError("windows_seconds must contain positive values")
    if len(set(windows_seconds)) != len(windows_seconds):
        raise ValueError("windows_seconds must be unique")

    candidate_rows = [
        item
        for item in stored_trades
        if item.acquisition_run_key == reference.acquisition_run_key
        and item.observation.token_mint == reference.token_mint
    ]
    candidate_rows.sort(
        key=lambda item: (
            item.observation.chain_time,
            item.observation.observed_at,
            item.event_key,
        )
    )

    same_or_later = sum(
        1
        for item in candidate_rows
        if item.observation.chain_time >= reference.entry_chain_time
    )
    not_known = sum(
        1
        for item in candidate_rows
        if item.observation.chain_time < reference.entry_chain_time
        and item.observation.observed_at >= reference.entry_observed_at
    )
    strict_rows = [
        item
        for item in candidate_rows
        if item.observation.chain_time < reference.entry_chain_time
        and item.observation.observed_at < reference.entry_observed_at
    ]

    windows = tuple(
        _window(
            strict_rows,
            reference=reference,
            window_seconds=seconds,
        )
        for seconds in sorted(windows_seconds)
    )

    flags: list[str] = []
    if not strict_rows:
        flags.append("no_causal_preentry_market_evidence")
    if not_known:
        flags.append("preentry_chain_events_not_known_before_reference_entry")
    if same_or_later:
        flags.append("same_or_later_market_events_excluded")

    return ExceptionalTradePreEntrySnapshotV56(
        method_version=EXCEPTIONAL_TRADE_PREENTRY_VERSION,
        reference_key=reference.reference_key,
        acquisition_run_key=reference.acquisition_run_key,
        wallet_address=reference.wallet_address,
        token_mint=reference.token_mint,
        market_cutoff_chain_time=reference.entry_chain_time,
        knowledge_cutoff_observed_at=reference.entry_observed_at,
        windows=windows,
        candidate_rows_seen=len(candidate_rows),
        rows_strictly_preentry=len(strict_rows),
        excluded_same_or_later_market_time=same_or_later,
        excluded_not_known_before_entry=not_known,
        data_quality_flags=tuple(flags),
    )


def load_exceptional_trade_preentry_snapshot_v56(
    *,
    reference: ExceptionalTradeReferenceV56,
    windows_seconds: tuple[int, ...] = DEFAULT_PREENTRY_WINDOWS_SECONDS,
) -> ExceptionalTradePreEntrySnapshotV56:
    """READ ONLY helper over persisted market observations."""

    validate_reference_v56(reference)
    max_window = max(windows_seconds)
    rows = load_market_trades(
        acquisition_run_key=reference.acquisition_run_key,
        token_mint=reference.token_mint,
        chain_time_after=max(0, reference.entry_chain_time - max_window - 1),
    )
    return build_exceptional_trade_preentry_snapshot_v56(
        reference=reference,
        stored_trades=rows,
        windows_seconds=windows_seconds,
    )


def derived_preentry_dynamics_v56(
    snapshot: ExceptionalTradePreEntrySnapshotV56,
) -> dict[str, float | int | None]:
    """Return simple descriptive transforms only; no score, threshold or recommendation."""

    indexed = {item.window_seconds: item for item in snapshot.windows}

    def rate_ratio(short: int, long: int) -> float | None:
        a = indexed.get(short)
        b = indexed.get(long)
        if a is None or b is None or b.event_count <= 0:
            return None
        short_rate = a.event_count / float(short)
        long_rate = b.event_count / float(long)
        if long_rate <= 0:
            return None
        value = short_rate / long_rate
        return value if math.isfinite(value) else None

    def unique_buy_rate_ratio(short: int, long: int) -> float | None:
        a = indexed.get(short)
        b = indexed.get(long)
        if (
            a is None
            or b is None
            or a.unique_buy_wallet_count is None
            or b.unique_buy_wallet_count is None
            or b.unique_buy_wallet_count <= 0
        ):
            return None
        short_rate = a.unique_buy_wallet_count / float(short)
        long_rate = b.unique_buy_wallet_count / float(long)
        if long_rate <= 0:
            return None
        value = short_rate / long_rate
        return value if math.isfinite(value) else None

    w30 = indexed.get(30)
    w60 = indexed.get(60)
    return {
        "event_rate_ratio_10_vs_60": rate_ratio(10, 60),
        "event_rate_ratio_30_vs_300": rate_ratio(30, 300),
        "unique_buy_wallet_rate_ratio_10_vs_60": unique_buy_rate_ratio(10, 60),
        "top1_wallet_event_share_30": (
            w30.top1_wallet_event_share_pct if w30 is not None else None
        ),
        "top1_wallet_event_share_60": (
            w60.top1_wallet_event_share_pct if w60 is not None else None
        ),
        "repeated_wallet_event_share_30": (
            w30.repeated_wallet_event_share_pct if w30 is not None else None
        ),
        "repeated_wallet_event_share_60": (
            w60.repeated_wallet_event_share_pct if w60 is not None else None
        ),
        "buy_sell_wallet_overlap_share_60": (
            w60.buy_sell_wallet_overlap_share_pct if w60 is not None else None
        ),
    }
