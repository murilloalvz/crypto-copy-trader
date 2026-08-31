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


@dataclass(frozen=True)
class ExitContextObservation:
    token_mint: str
    entry_at: int
    first_sell_at: int
    last_sell_at: int
    sell_count: int
    entry_dex: str | None
    entry_price_usd: float
    first_sell_price_usd: float
    last_sell_price_usd: float
    first_exit_hours: float
    last_exit_hours: float
    first_sell_return_pct: float
    last_sell_return_pct: float
    first_to_last_sell_change_pct: float


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
    median_first_to_last_sell_change_pct: float | None


def _return_pct(start: float, end: float) -> float:
    if start <= 0 or end <= 0:
        raise ValueError("preços precisam ser positivos")
    return 100.0 * (end / start - 1.0)


def analyze_exit_context(
    seed: ExitCycleSeed,
    *,
    entry_price_usd: float,
    first_sell_price_usd: float,
    last_sell_price_usd: float,
) -> ExitContextObservation:
    """Describe price proxies at observed sell times relative to the first observed buy.

    This is intentionally not realized PnL. Prices come from market candles near the on-chain
    timestamps, not from the wallet's exact fills, and the first observed buy can be incomplete
    if the local backfill does not cover the wallet's full history.
    """
    if seed.first_sell_at < seed.entry_at or seed.last_sell_at < seed.first_sell_at:
        raise ValueError("ordem temporal inválida no ciclo observado")
    if seed.sell_count < 1:
        raise ValueError("sell_count precisa ser >= 1")

    return ExitContextObservation(
        token_mint=seed.token_mint,
        entry_at=seed.entry_at,
        first_sell_at=seed.first_sell_at,
        last_sell_at=seed.last_sell_at,
        sell_count=seed.sell_count,
        entry_dex=seed.entry_dex,
        entry_price_usd=entry_price_usd,
        first_sell_price_usd=first_sell_price_usd,
        last_sell_price_usd=last_sell_price_usd,
        first_exit_hours=(seed.first_sell_at - seed.entry_at) / 3_600.0,
        last_exit_hours=(seed.last_sell_at - seed.entry_at) / 3_600.0,
        first_sell_return_pct=_return_pct(entry_price_usd, first_sell_price_usd),
        last_sell_return_pct=_return_pct(entry_price_usd, last_sell_price_usd),
        first_to_last_sell_change_pct=_return_pct(first_sell_price_usd, last_sell_price_usd),
    )


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


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
        median_first_to_last_sell_change_pct=_median(
            [item.first_to_last_sell_change_pct for item in multi_sell]
        ),
    )
