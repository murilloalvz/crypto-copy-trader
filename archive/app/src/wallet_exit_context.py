from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class ExitCycleSeed:
    token_mint: str
    entry_at: int
    first_sell_at: int
    last_sell_at: int
    sell_count: int
    entry_dex: str | None
    reentry_at: int | None = None


@dataclass(frozen=True)
class ExitCycleExtraction:
    cycles: tuple[ExitCycleSeed, ...]
    token_count: int
    no_observed_buy_token_count: int
    no_sell_after_buy_token_count: int
    excluded_preexisting_inventory_token_count: int


@dataclass(frozen=True)
class ExitContextObservation:
    token_mint: str
    entry_at: int
    first_sell_at: int
    last_sell_at: int
    sell_count: int
    entry_dex: str | None
    reentry_at: int | None
    entry_price_usd: float
    first_sell_price_usd: float
    last_sell_price_usd: float
    first_exit_hours: float
    last_exit_hours: float
    first_sell_return_pct: float
    last_sell_return_pct: float
    first_to_last_sell_change_pct: float
    mfe_before_first_sell_pct: float | None
    mae_before_first_sell_pct: float | None
    first_sell_vs_pre_exit_peak_pct: float | None
    path_complete_before_first_sell: bool


@dataclass(frozen=True)
class ExitContextSummary:
    attempted_cycles: int
    priced_cycles: int
    failed_cycles: int
    median_first_exit_hours: float | None
    median_last_exit_hours: float | None
    median_first_sell_return_pct: float | None
    median_last_sell_return_pct: float | None
    positive_first_sell_share_pct: float
    first_sell_up_20_share_pct: float
    negative_first_sell_share_pct: float
    multi_sell_cycle_share_pct: float
    reentry_after_cycle_share_pct: float
    median_first_to_last_sell_change_pct: float | None
    path_complete_share_pct: float
    median_mfe_before_first_sell_pct: float | None
    median_mae_before_first_sell_pct: float | None
    median_first_sell_vs_pre_exit_peak_pct: float | None


def _return_pct(start: float, end: float) -> float:
    if start <= 0 or end <= 0:
        raise ValueError("preços precisam ser positivos")
    return 100.0 * (end / start - 1.0)


def extract_exit_cycle_seeds(swaps: list[dict]) -> ExitCycleExtraction:
    """Extract the first clean observed buy->sell cycle for each token.

    Tokens with an observed sell before their first observed buy are excluded because the
    synchronized window may start with pre-existing inventory. When a buy occurs after the
    first sell, the first cycle ends immediately before that re-entry so later cycles are not
    silently merged into the original position.
    """
    clean = [
        item
        for item in swaps
        if item.get("token_mint")
        and item.get("block_time") is not None
        and item.get("token_change") is not None
        and float(item["token_change"]) != 0
    ]
    clean.sort(key=lambda item: (str(item["token_mint"]), int(item["block_time"])))

    per_token: dict[str, list[dict]] = {}
    for item in clean:
        per_token.setdefault(str(item["token_mint"]), []).append(item)

    cycles: list[ExitCycleSeed] = []
    no_buy = no_sell_after_buy = preexisting = 0
    for token_mint, token_swaps in per_token.items():
        buys = [item for item in token_swaps if float(item["token_change"]) > 0]
        sells = [item for item in token_swaps if float(item["token_change"]) < 0]
        if not buys:
            no_buy += 1
            continue

        first_buy = buys[0]
        first_buy_at = int(first_buy["block_time"])
        if any(int(item["block_time"]) < first_buy_at for item in sells):
            preexisting += 1
            continue

        sells_after_buy = [
            item for item in sells if int(item["block_time"]) >= first_buy_at
        ]
        if not sells_after_buy:
            no_sell_after_buy += 1
            continue

        first_sell_at = int(sells_after_buy[0]["block_time"])
        reentries = [
            item for item in buys if int(item["block_time"]) > first_sell_at
        ]
        reentry_at = int(reentries[0]["block_time"]) if reentries else None
        first_cycle_sells = [
            item
            for item in sells_after_buy
            if reentry_at is None or int(item["block_time"]) < reentry_at
        ]
        if not first_cycle_sells:
            no_sell_after_buy += 1
            continue

        cycles.append(
            ExitCycleSeed(
                token_mint=token_mint,
                entry_at=first_buy_at,
                first_sell_at=int(first_cycle_sells[0]["block_time"]),
                last_sell_at=int(first_cycle_sells[-1]["block_time"]),
                sell_count=len(first_cycle_sells),
                entry_dex=first_buy.get("dex"),
                reentry_at=reentry_at,
            )
        )

    cycles.sort(key=lambda item: item.entry_at)
    return ExitCycleExtraction(
        cycles=tuple(cycles),
        token_count=len(per_token),
        no_observed_buy_token_count=no_buy,
        no_sell_after_buy_token_count=no_sell_after_buy,
        excluded_preexisting_inventory_token_count=preexisting,
    )


def _pre_first_sell_path_metrics(
    candles: list[dict],
    *,
    entry_at: int,
    first_sell_at: int,
    entry_price_usd: float,
    first_sell_price_usd: float,
) -> tuple[float | None, float | None, float | None, bool]:
    """Measure conservative MFE/MAE using only full hourly candles before first sell.

    The entry hour is excluded because it contains price action before the observed buy. The
    hour containing the first sell is also excluded unless it was fully completed before the
    sell timestamp, preventing post-sell movement from leaking into the pre-exit path.
    """
    if entry_price_usd <= 0 or first_sell_price_usd <= 0:
        raise ValueError("preços precisam ser positivos")

    first_full_hour = ((entry_at // 3_600) + 1) * 3_600
    latest_full_hour = (first_sell_at // 3_600 - 1) * 3_600
    if latest_full_hour < first_full_hour:
        return None, None, None, False

    window = [
        item
        for item in candles
        if item.get("timestamp") is not None
        and first_full_hour <= int(item["timestamp"]) <= latest_full_hour
        and int(item["timestamp"]) + 3_600 <= first_sell_at
        and item.get("high") is not None
        and item.get("low") is not None
    ]
    if not window:
        return None, None, None, False

    highs = [float(item["high"]) for item in window if float(item["high"]) > 0]
    lows = [float(item["low"]) for item in window if float(item["low"]) > 0]
    if not highs or not lows:
        return None, None, None, False

    timestamps = [int(item["timestamp"]) for item in window]
    complete = min(timestamps) <= first_full_hour and max(timestamps) >= latest_full_hour
    peak_price = max(highs)
    mfe = 100.0 * (peak_price / entry_price_usd - 1.0)
    mae = 100.0 * (min(lows) / entry_price_usd - 1.0)
    sell_vs_peak = 100.0 * (first_sell_price_usd / peak_price - 1.0)
    return mfe, mae, sell_vs_peak, complete


def analyze_exit_context(
    seed: ExitCycleSeed,
    *,
    entry_price_usd: float,
    first_sell_price_usd: float,
    last_sell_price_usd: float,
    pre_first_sell_hourly_candles: list[dict] | None = None,
) -> ExitContextObservation:
    """Describe market-price proxies at the wallet's observed sell timestamps.

    This is not realized PnL. Prices come from market candles near on-chain timestamps rather
    than exact fills. The first observed buy can also be incomplete when local backfill does
    not cover the wallet's full history.
    """
    if seed.first_sell_at < seed.entry_at or seed.last_sell_at < seed.first_sell_at:
        raise ValueError("ordem temporal inválida no ciclo observado")
    if seed.sell_count < 1:
        raise ValueError("sell_count precisa ser >= 1")

    mfe = mae = sell_vs_peak = None
    path_complete = False
    if pre_first_sell_hourly_candles is not None:
        mfe, mae, sell_vs_peak, path_complete = _pre_first_sell_path_metrics(
            pre_first_sell_hourly_candles,
            entry_at=seed.entry_at,
            first_sell_at=seed.first_sell_at,
            entry_price_usd=entry_price_usd,
            first_sell_price_usd=first_sell_price_usd,
        )

    return ExitContextObservation(
        token_mint=seed.token_mint,
        entry_at=seed.entry_at,
        first_sell_at=seed.first_sell_at,
        last_sell_at=seed.last_sell_at,
        sell_count=seed.sell_count,
        entry_dex=seed.entry_dex,
        reentry_at=seed.reentry_at,
        entry_price_usd=entry_price_usd,
        first_sell_price_usd=first_sell_price_usd,
        last_sell_price_usd=last_sell_price_usd,
        first_exit_hours=(seed.first_sell_at - seed.entry_at) / 3_600.0,
        last_exit_hours=(seed.last_sell_at - seed.entry_at) / 3_600.0,
        first_sell_return_pct=_return_pct(entry_price_usd, first_sell_price_usd),
        last_sell_return_pct=_return_pct(entry_price_usd, last_sell_price_usd),
        first_to_last_sell_change_pct=_return_pct(first_sell_price_usd, last_sell_price_usd),
        mfe_before_first_sell_pct=mfe,
        mae_before_first_sell_pct=mae,
        first_sell_vs_pre_exit_peak_pct=sell_vs_peak,
        path_complete_before_first_sell=path_complete,
    )


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _median_available(values: list[float | None]) -> float | None:
    return _median([float(value) for value in values if value is not None])


def _share(values: list[bool]) -> float:
    return 100.0 * sum(values) / len(values) if values else 0.0


def summarize_exit_context(
    observations: list[ExitContextObservation] | tuple[ExitContextObservation, ...],
    *,
    attempted_cycles: int | None = None,
) -> ExitContextSummary:
    rows = list(observations)
    attempted = len(rows) if attempted_cycles is None else attempted_cycles
    if attempted < len(rows):
        raise ValueError("attempted_cycles não pode ser menor que priced_cycles")

    first_returns = [item.first_sell_return_pct for item in rows]
    multi_sell = [item for item in rows if item.sell_count >= 2]
    path_rows = [item for item in rows if item.path_complete_before_first_sell]
    return ExitContextSummary(
        attempted_cycles=attempted,
        priced_cycles=len(rows),
        failed_cycles=attempted - len(rows),
        median_first_exit_hours=_median([item.first_exit_hours for item in rows]),
        median_last_exit_hours=_median([item.last_exit_hours for item in rows]),
        median_first_sell_return_pct=_median(first_returns),
        median_last_sell_return_pct=_median([item.last_sell_return_pct for item in rows]),
        positive_first_sell_share_pct=_share([value > 0 for value in first_returns]),
        first_sell_up_20_share_pct=_share([value >= 20.0 for value in first_returns]),
        negative_first_sell_share_pct=_share([value < 0 for value in first_returns]),
        multi_sell_cycle_share_pct=_share([item.sell_count >= 2 for item in rows]),
        reentry_after_cycle_share_pct=_share([item.reentry_at is not None for item in rows]),
        median_first_to_last_sell_change_pct=_median(
            [item.first_to_last_sell_change_pct for item in multi_sell]
        ),
        path_complete_share_pct=_share(
            [item.path_complete_before_first_sell for item in rows]
        ),
        median_mfe_before_first_sell_pct=_median_available(
            [item.mfe_before_first_sell_pct for item in path_rows]
        ),
        median_mae_before_first_sell_pct=_median_available(
            [item.mae_before_first_sell_pct for item in path_rows]
        ),
        median_first_sell_vs_pre_exit_peak_pct=_median_available(
            [item.first_sell_vs_pre_exit_peak_pct for item in path_rows]
        ),
    )
