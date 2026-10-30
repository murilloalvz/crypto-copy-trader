from dataclasses import dataclass
from statistics import median

from src.wallet_entry_context import EntrySeed


@dataclass(frozen=True)
class HoldingContextObservation:
    token_mint: str
    entry_at: int
    dex: str | None
    entry_price_usd: float
    post_6h_return_pct: float | None
    post_24h_return_pct: float | None
    post_48h_return_pct: float | None
    post_72h_return_pct: float | None
    mfe_24h_pct: float | None
    mae_24h_pct: float | None
    mfe_72h_pct: float | None
    mae_72h_pct: float | None


@dataclass(frozen=True)
class HoldingContextSummary:
    attempted_entries: int
    priced_entries: int
    failed_entries: int
    median_post_6h_return_pct: float | None
    median_post_24h_return_pct: float | None
    median_post_48h_return_pct: float | None
    median_post_72h_return_pct: float | None
    median_mfe_24h_pct: float | None
    median_mae_24h_pct: float | None
    median_mfe_72h_pct: float | None
    median_mae_72h_pct: float | None
    positive_24h_share_pct: float
    positive_72h_share_pct: float
    drawdown_30_24h_share_pct: float


def _nearest_close(
    candles: list[dict], target_ts: int, *, max_distance_seconds: int = 5_400
) -> float | None:
    candidates = [
        item
        for item in candles
        if item.get("timestamp") is not None and item.get("close") is not None
    ]
    if not candidates:
        return None
    selected = min(candidates, key=lambda item: abs(int(item["timestamp"]) - target_ts))
    if abs(int(selected["timestamp"]) - target_ts) > max_distance_seconds:
        return None
    value = float(selected["close"])
    return value if value > 0 else None


def _return_pct(start: float, end: float | None) -> float | None:
    if start <= 0 or end is None:
        return None
    return 100.0 * (end / start - 1.0)


def _path_extremes(
    candles: list[dict],
    *,
    entry_at: int,
    entry_price: float,
    horizon_seconds: int,
) -> tuple[float | None, float | None]:
    """Return MFE/MAE from full hourly candles strictly after the entry hour starts.

    The partial hour containing the entry is excluded because its high/low can include
    movement that happened before the wallet bought. This is conservative and can miss
    extrema during the remainder of the entry hour, but it avoids look-ahead contamination.
    """
    first_full_hour = ((entry_at // 3_600) + 1) * 3_600
    end_at = entry_at + horizon_seconds
    window = [
        item
        for item in candles
        if item.get("timestamp") is not None
        and first_full_hour <= int(item["timestamp"]) <= end_at
        and item.get("high") is not None
        and item.get("low") is not None
    ]
    if not window or entry_price <= 0:
        return None, None
    highs = [float(item["high"]) for item in window if float(item["high"]) > 0]
    lows = [float(item["low"]) for item in window if float(item["low"]) > 0]
    if not highs or not lows:
        return None, None
    mfe = 100.0 * (max(highs) / entry_price - 1.0)
    mae = 100.0 * (min(lows) / entry_price - 1.0)
    return mfe, mae


def analyze_holding_context(
    seed: EntrySeed,
    entry_price_usd: float,
    hourly_candles: list[dict],
    *,
    max_distance_seconds: int = 5_400,
) -> HoldingContextObservation:
    """Describe price evolution over horizons compatible with a multi-day holder.

    This is market-price research only. It does not reconstruct the wallet's realized PnL,
    execution price, position size or exact exit decisions.
    """
    targets = {
        hours: _nearest_close(
            hourly_candles,
            seed.entry_at + hours * 3_600,
            max_distance_seconds=max_distance_seconds,
        )
        for hours in (6, 24, 48, 72)
    }
    mfe_24, mae_24 = _path_extremes(
        hourly_candles,
        entry_at=seed.entry_at,
        entry_price=entry_price_usd,
        horizon_seconds=24 * 3_600,
    )
    mfe_72, mae_72 = _path_extremes(
        hourly_candles,
        entry_at=seed.entry_at,
        entry_price=entry_price_usd,
        horizon_seconds=72 * 3_600,
    )
    return HoldingContextObservation(
        token_mint=seed.token_mint,
        entry_at=seed.entry_at,
        dex=seed.dex,
        entry_price_usd=entry_price_usd,
        post_6h_return_pct=_return_pct(entry_price_usd, targets[6]),
        post_24h_return_pct=_return_pct(entry_price_usd, targets[24]),
        post_48h_return_pct=_return_pct(entry_price_usd, targets[48]),
        post_72h_return_pct=_return_pct(entry_price_usd, targets[72]),
        mfe_24h_pct=mfe_24,
        mae_24h_pct=mae_24,
        mfe_72h_pct=mfe_72,
        mae_72h_pct=mae_72,
    )


def _median_available(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return median(clean) if clean else None


def _share(values: list[bool]) -> float:
    return 100.0 * sum(values) / len(values) if values else 0.0


def summarize_holding_context(
    observations: list[HoldingContextObservation] | tuple[HoldingContextObservation, ...],
    *,
    attempted_entries: int | None = None,
) -> HoldingContextSummary:
    rows = list(observations)
    attempted = len(rows) if attempted_entries is None else attempted_entries
    if attempted < len(rows):
        raise ValueError("attempted_entries não pode ser menor que priced_entries")

    post24 = [item.post_24h_return_pct for item in rows if item.post_24h_return_pct is not None]
    post72 = [item.post_72h_return_pct for item in rows if item.post_72h_return_pct is not None]
    return HoldingContextSummary(
        attempted_entries=attempted,
        priced_entries=len(rows),
        failed_entries=attempted - len(rows),
        median_post_6h_return_pct=_median_available([item.post_6h_return_pct for item in rows]),
        median_post_24h_return_pct=_median_available(post24),
        median_post_48h_return_pct=_median_available([item.post_48h_return_pct for item in rows]),
        median_post_72h_return_pct=_median_available(post72),
        median_mfe_24h_pct=_median_available([item.mfe_24h_pct for item in rows]),
        median_mae_24h_pct=_median_available([item.mae_24h_pct for item in rows]),
        median_mfe_72h_pct=_median_available([item.mfe_72h_pct for item in rows]),
        median_mae_72h_pct=_median_available([item.mae_72h_pct for item in rows]),
        positive_24h_share_pct=_share([value > 0 for value in post24]),
        positive_72h_share_pct=_share([value > 0 for value in post72]),
        drawdown_30_24h_share_pct=_share([value <= -30 for value in post24]),
    )
