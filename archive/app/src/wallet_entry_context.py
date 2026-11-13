from collections import Counter
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class EntrySeed:
    token_mint: str
    entry_at: int
    dex: str | None


@dataclass(frozen=True)
class EntryContextObservation:
    token_mint: str
    entry_at: int
    dex: str | None
    entry_price_usd: float
    pre_5m_return_pct: float | None
    pre_15m_return_pct: float | None
    pre_60m_return_pct: float | None
    post_5m_return_pct: float | None
    post_15m_return_pct: float | None
    post_60m_return_pct: float | None
    pre_60m_range_position_pct: float | None
    pre_60m_amplitude_pct: float | None
    context_label: str


@dataclass(frozen=True)
class EntryContextSummary:
    attempted_entries: int
    priced_entries: int
    failed_entries: int
    dex_mix: dict[str, int]
    context_counts: dict[str, int]
    median_pre_5m_return_pct: float | None
    median_pre_15m_return_pct: float | None
    median_pre_60m_return_pct: float | None
    median_post_5m_return_pct: float | None
    median_post_15m_return_pct: float | None
    median_post_60m_return_pct: float | None
    median_pre_60m_range_position_pct: float | None
    median_pre_60m_amplitude_pct: float | None
    pre15_up_5_share_pct: float
    pre15_down_5_share_pct: float
    near_pre60_high_share_pct: float


def _nearest_close(
    candles: list[dict], target_ts: int, *, max_distance_seconds: int = 90
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


def _return_pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return 100.0 * (end / start - 1.0)


def _pre_range_metrics(
    candles: list[dict], entry_ts: int, entry_price: float
) -> tuple[float | None, float | None]:
    window = [
        item
        for item in candles
        if item.get("timestamp") is not None
        and entry_ts - 3_600 <= int(item["timestamp"]) <= entry_ts
        and item.get("high") is not None
        and item.get("low") is not None
    ]
    if not window:
        return None, None
    low = min(float(item["low"]) for item in window)
    high = max(float(item["high"]) for item in window)
    if low <= 0 or high <= 0:
        return None, None
    amplitude = 100.0 * (high / low - 1.0)
    if high <= low:
        return 50.0, amplitude
    position = 100.0 * (entry_price - low) / (high - low)
    return max(0.0, min(100.0, position)), amplitude


def _context_label(
    pre_15m: float | None,
    pre_60m: float | None,
    range_position: float | None,
) -> str:
    """Broad descriptive bucket based only on information before the observed buy.

    The thresholds are deliberately coarse research heuristics. They are not trading rules
    and must not be promoted into wave_v3 without separate validation.
    """
    if pre_15m is None or range_position is None:
        return "insufficient_price_context"
    if pre_15m >= 5.0 and range_position >= 70.0:
        return "momentum_breakout_like"
    if pre_15m <= -5.0 and range_position <= 30.0:
        return "dip_like"
    if pre_60m is not None and pre_60m >= 10.0 and range_position >= 70.0:
        return "extended_momentum_like"
    return "mixed_neutral"


def analyze_entry_candles(
    seed: EntrySeed,
    candles: list[dict],
    *,
    max_distance_seconds: int = 90,
) -> EntryContextObservation | None:
    """Describe market-price context around one observed first buy.

    Candles are expected to contain timestamp/open/high/low/close keys. The returned
    post-entry fields are descriptive outcomes only; the context label uses pre-entry data.
    """
    entry_ts = seed.entry_at - seed.entry_at % 60
    entry_price = _nearest_close(
        candles, entry_ts, max_distance_seconds=max_distance_seconds
    )
    if entry_price is None:
        return None

    prices = {
        offset: _nearest_close(
            candles,
            entry_ts + offset,
            max_distance_seconds=max_distance_seconds,
        )
        for offset in (-3_600, -900, -300, 300, 900, 3_600)
    }
    pre_5 = _return_pct(prices[-300], entry_price)
    pre_15 = _return_pct(prices[-900], entry_price)
    pre_60 = _return_pct(prices[-3_600], entry_price)
    post_5 = _return_pct(entry_price, prices[300])
    post_15 = _return_pct(entry_price, prices[900])
    post_60 = _return_pct(entry_price, prices[3_600])
    range_position, amplitude = _pre_range_metrics(candles, entry_ts, entry_price)

    return EntryContextObservation(
        token_mint=seed.token_mint,
        entry_at=seed.entry_at,
        dex=seed.dex,
        entry_price_usd=entry_price,
        pre_5m_return_pct=pre_5,
        pre_15m_return_pct=pre_15,
        pre_60m_return_pct=pre_60,
        post_5m_return_pct=post_5,
        post_15m_return_pct=post_15,
        post_60m_return_pct=post_60,
        pre_60m_range_position_pct=range_position,
        pre_60m_amplitude_pct=amplitude,
        context_label=_context_label(pre_15, pre_60, range_position),
    )


def _median_available(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return median(clean) if clean else None


def _share(values: list[bool]) -> float:
    return 100.0 * sum(values) / len(values) if values else 0.0


def summarize_entry_context(
    observations: list[EntryContextObservation] | tuple[EntryContextObservation, ...],
    *,
    attempted_entries: int | None = None,
) -> EntryContextSummary:
    rows = list(observations)
    attempted = len(rows) if attempted_entries is None else attempted_entries
    if attempted < len(rows):
        raise ValueError("attempted_entries não pode ser menor que priced_entries")

    pre15 = [item.pre_15m_return_pct for item in rows if item.pre_15m_return_pct is not None]
    positions = [
        item.pre_60m_range_position_pct
        for item in rows
        if item.pre_60m_range_position_pct is not None
    ]
    return EntryContextSummary(
        attempted_entries=attempted,
        priced_entries=len(rows),
        failed_entries=attempted - len(rows),
        dex_mix=dict(Counter(item.dex or "unknown" for item in rows).most_common()),
        context_counts=dict(Counter(item.context_label for item in rows).most_common()),
        median_pre_5m_return_pct=_median_available([item.pre_5m_return_pct for item in rows]),
        median_pre_15m_return_pct=_median_available([item.pre_15m_return_pct for item in rows]),
        median_pre_60m_return_pct=_median_available([item.pre_60m_return_pct for item in rows]),
        median_post_5m_return_pct=_median_available([item.post_5m_return_pct for item in rows]),
        median_post_15m_return_pct=_median_available([item.post_15m_return_pct for item in rows]),
        median_post_60m_return_pct=_median_available([item.post_60m_return_pct for item in rows]),
        median_pre_60m_range_position_pct=_median_available(positions),
        median_pre_60m_amplitude_pct=_median_available(
            [item.pre_60m_amplitude_pct for item in rows]
        ),
        pre15_up_5_share_pct=_share([value >= 5.0 for value in pre15]),
        pre15_down_5_share_pct=_share([value <= -5.0 for value in pre15]),
        near_pre60_high_share_pct=_share([value >= 70.0 for value in positions]),
    )
