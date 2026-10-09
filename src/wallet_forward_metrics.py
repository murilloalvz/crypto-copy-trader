from dataclasses import dataclass
from statistics import median

from src.opportunity_intelligence import WalletActionObservation


@dataclass(frozen=True)
class ForwardWalletLatencySummary:
    observation_count: int
    wallet_count: int
    token_count: int
    buy_count: int
    sell_count: int
    min_lag_seconds: float | None
    median_lag_seconds: float | None
    p95_lag_seconds: float | None
    max_lag_seconds: float | None
    within_15s_share_pct: float
    within_30s_share_pct: float
    within_60s_share_pct: float
    within_120s_share_pct: float


def _pct(count: int, total: int) -> float:
    return 100.0 * count / total if total else 0.0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_forward_wallet_latency(
    observations: list[WalletActionObservation]
    | tuple[WalletActionObservation, ...],
) -> ForwardWalletLatencySummary:
    rows = list(observations)
    lags: list[float] = []
    for item in rows:
        if item.side not in {"buy", "sell"}:
            raise ValueError("wallet side must be buy or sell")
        lag = item.observed_at - item.chain_time
        if lag < 0:
            raise ValueError("observed_at cannot be earlier than chain_time")
        lags.append(float(lag))

    return ForwardWalletLatencySummary(
        observation_count=len(rows),
        wallet_count=len({item.address for item in rows}),
        token_count=len({item.token_mint for item in rows}),
        buy_count=sum(item.side == "buy" for item in rows),
        sell_count=sum(item.side == "sell" for item in rows),
        min_lag_seconds=min(lags) if lags else None,
        median_lag_seconds=median(lags) if lags else None,
        p95_lag_seconds=_percentile(lags, 0.95),
        max_lag_seconds=max(lags) if lags else None,
        within_15s_share_pct=_pct(sum(lag <= 15 for lag in lags), len(lags)),
        within_30s_share_pct=_pct(sum(lag <= 30 for lag in lags), len(lags)),
        within_60s_share_pct=_pct(sum(lag <= 60 for lag in lags), len(lags)),
        within_120s_share_pct=_pct(sum(lag <= 120 for lag in lags), len(lags)),
    )


def summarize_forward_wallet_latency_by_address(
    observations: list[WalletActionObservation]
    | tuple[WalletActionObservation, ...],
) -> dict[str, ForwardWalletLatencySummary]:
    grouped: dict[str, list[WalletActionObservation]] = {}
    for item in observations:
        grouped.setdefault(item.address, []).append(item)
    return {
        address: summarize_forward_wallet_latency(group)
        for address, group in sorted(grouped.items())
    }
