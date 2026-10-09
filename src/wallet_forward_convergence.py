import statistics
from dataclasses import dataclass

from src.wallet_quote_watch import ForwardBuyEvent


@dataclass(frozen=True)
class ForwardWalletConvergenceEvent:
    """One causal multi-wallet BUY convergence observed in forward time.

    ``trigger_observation_key`` is the exact BUY whose arrival first made the unique-wallet
    threshold true inside the rolling window. The event is descriptive research evidence;
    it is not a trade instruction and it does not imply that the wallets have edge.
    """

    token_mint: str
    triggered_at: int
    trigger_event_id: int
    trigger_observation_key: str
    trigger_wallet_address: str
    window_seconds: int
    min_unique_buy_wallets: int
    unique_buy_wallet_count: int
    participating_wallets: tuple[str, ...]
    first_buy_observed_at: int
    latest_buy_observed_at: int
    convergence_span_seconds: int
    trigger_source_lag_seconds: int


@dataclass(frozen=True)
class ForwardWalletConvergenceSummary:
    buy_event_count: int
    buy_wallet_count: int
    buy_token_count: int
    convergence_event_count: int
    convergence_token_count: int
    median_convergence_span_seconds: float | None
    median_trigger_source_lag_seconds: float | None
    p95_trigger_source_lag_seconds: float | None


def _validate_buy_event(item: ForwardBuyEvent) -> None:
    if item.id <= 0:
        raise ValueError("forward buy event id must be positive")
    if not item.observation_key.strip():
        raise ValueError("forward buy observation_key cannot be empty")
    if not item.wallet_address.strip() or not item.token_mint.strip():
        raise ValueError("forward buy wallet/token cannot be empty")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("forward buy timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("forward buy observed_at cannot precede chain_time")


def _ordered_unique_wallets(events: list[ForwardBuyEvent]) -> tuple[str, ...]:
    first_seen: dict[str, tuple[int, int]] = {}
    for item in events:
        key = item.wallet_address
        stamp = (item.observed_at, item.id)
        if key not in first_seen or stamp < first_seen[key]:
            first_seen[key] = stamp
    return tuple(
        address
        for address, _ in sorted(first_seen.items(), key=lambda pair: (pair[1], pair[0]))
    )


def build_forward_wallet_convergence_events(
    buy_events: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    *,
    window_seconds: int = 300,
    min_unique_buy_wallets: int = 2,
    token_cooldown_seconds: int = 1800,
) -> tuple[ForwardWalletConvergenceEvent, ...]:
    """Detect threshold-crossing convergence using only information observed by that instant.

    A convergence is emitted only when the current BUY makes the rolling unique-wallet count
    cross from below ``min_unique_buy_wallets`` to at least that threshold. A token cooldown
    prevents repeated bursts of the same token from inflating the sample. All ordering uses
    ``observed_at`` rather than retrospective chain time, preserving forward causality.
    """

    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if min_unique_buy_wallets < 2:
        raise ValueError("min_unique_buy_wallets must be >= 2")
    if token_cooldown_seconds < 0:
        raise ValueError("token_cooldown_seconds must be non-negative")

    ordered = sorted(buy_events, key=lambda item: (item.observed_at, item.id))
    seen_ids: set[int] = set()
    seen_keys: set[str] = set()
    for item in ordered:
        _validate_buy_event(item)
        if item.id in seen_ids:
            raise ValueError("forward buy event ids must be unique")
        if item.observation_key in seen_keys:
            raise ValueError("forward buy observation keys must be unique")
        seen_ids.add(item.id)
        seen_keys.add(item.observation_key)

    history_by_token: dict[str, list[ForwardBuyEvent]] = {}
    last_emitted_at: dict[str, int] = {}
    output: list[ForwardWalletConvergenceEvent] = []

    for item in ordered:
        token_history = history_by_token.setdefault(item.token_mint, [])
        window_start = max(0, item.observed_at - window_seconds)
        token_history[:] = [
            previous
            for previous in token_history
            if previous.observed_at >= window_start
        ]

        before_wallets = {previous.wallet_address for previous in token_history}
        token_history.append(item)
        after_wallets = {previous.wallet_address for previous in token_history}

        crossed = (
            len(before_wallets) < min_unique_buy_wallets
            and len(after_wallets) >= min_unique_buy_wallets
        )
        if not crossed:
            continue

        previous_emission = last_emitted_at.get(item.token_mint)
        if (
            previous_emission is not None
            and item.observed_at - previous_emission < token_cooldown_seconds
        ):
            continue

        participating = _ordered_unique_wallets(token_history)
        first_at = min(previous.observed_at for previous in token_history)
        latest_at = max(previous.observed_at for previous in token_history)
        output.append(
            ForwardWalletConvergenceEvent(
                token_mint=item.token_mint,
                triggered_at=item.observed_at,
                trigger_event_id=item.id,
                trigger_observation_key=item.observation_key,
                trigger_wallet_address=item.wallet_address,
                window_seconds=window_seconds,
                min_unique_buy_wallets=min_unique_buy_wallets,
                unique_buy_wallet_count=len(after_wallets),
                participating_wallets=participating,
                first_buy_observed_at=first_at,
                latest_buy_observed_at=latest_at,
                convergence_span_seconds=latest_at - first_at,
                trigger_source_lag_seconds=item.observed_at - item.chain_time,
            )
        )
        last_emitted_at[item.token_mint] = item.observed_at

    return tuple(output)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((0.95 * len(ordered) + 0.999999)) - 1))
    return ordered[index]


def summarize_forward_wallet_convergence(
    buy_events: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    convergence_events: list[ForwardWalletConvergenceEvent]
    | tuple[ForwardWalletConvergenceEvent, ...],
) -> ForwardWalletConvergenceSummary:
    buys = list(buy_events)
    events = list(convergence_events)
    spans = [float(item.convergence_span_seconds) for item in events]
    lags = [float(item.trigger_source_lag_seconds) for item in events]
    return ForwardWalletConvergenceSummary(
        buy_event_count=len(buys),
        buy_wallet_count=len({item.wallet_address for item in buys}),
        buy_token_count=len({item.token_mint for item in buys}),
        convergence_event_count=len(events),
        convergence_token_count=len({item.token_mint for item in events}),
        median_convergence_span_seconds=(statistics.median(spans) if spans else None),
        median_trigger_source_lag_seconds=(statistics.median(lags) if lags else None),
        p95_trigger_source_lag_seconds=_p95(lags),
    )
