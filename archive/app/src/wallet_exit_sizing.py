from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class ExitSizingObservation:
    token_mint: str
    observed_bought_qty: float
    first_sell_qty: float
    total_cycle_sell_qty: float
    sell_count: int
    first_sell_fraction_pct: float
    total_sold_fraction_pct: float
    observed_runner_after_first_sell_pct: float
    quantity_anomaly: bool
    coverage_class: str


@dataclass(frozen=True)
class ExitSizingSummary:
    token_count: int
    multi_sell_token_count: int
    median_first_sell_fraction_pct: float | None
    median_total_sold_fraction_pct: float | None
    median_runner_after_first_sell_pct: float | None
    first_sell_below_50_share_pct: float
    multi_sell_share_pct: float
    quantity_anomaly_share_pct: float
    complete_like_count: int
    partial_or_open_count: int
    complete_multi_sell_count: int
    median_complete_multi_first_sell_fraction_pct: float | None
    median_complete_multi_runner_pct: float | None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _share(values: list[bool]) -> float:
    return 100.0 * sum(values) / len(values) if values else 0.0


def _coverage_class(total_fraction: float) -> str:
    # This is deliberately descriptive, not a claim that the position really closed.
    # Swap-only inventory can be distorted by transfers, token mechanics or incomplete backfill.
    if total_fraction > 105.0:
        return "quantity_anomaly"
    if total_fraction >= 90.0:
        return "complete_like"
    return "partial_or_open"


def analyze_exit_sizing(swaps: list[dict]) -> list[ExitSizingObservation]:
    """Estimate observed first-sale sizing from swap token deltas only.

    The denominator is the sum of observed swap buys before the first observed sell. This is
    intentionally a proxy: non-swap transfers, pre-existing inventory, token mechanics and an
    incomplete local history can make the inferred fractions differ from the wallet's true
    position sizing.
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

    observations: list[ExitSizingObservation] = []
    for token_mint, token_swaps in per_token.items():
        buys = [item for item in token_swaps if float(item["token_change"]) > 0]
        sells = [item for item in token_swaps if float(item["token_change"]) < 0]
        if not buys or not sells:
            continue

        first_buy_at = int(buys[0]["block_time"])
        if any(int(item["block_time"]) < first_buy_at for item in sells):
            continue

        sells_after_buy = [item for item in sells if int(item["block_time"]) >= first_buy_at]
        if not sells_after_buy:
            continue
        first_sell_at = int(sells_after_buy[0]["block_time"])

        pre_first_sell_buys = [
            item for item in buys if first_buy_at <= int(item["block_time"]) <= first_sell_at
        ]
        bought_qty = sum(float(item["token_change"]) for item in pre_first_sell_buys)
        if bought_qty <= 0:
            continue

        reentries = [item for item in buys if int(item["block_time"]) > first_sell_at]
        reentry_at = int(reentries[0]["block_time"]) if reentries else None
        cycle_sells = [
            item
            for item in sells_after_buy
            if reentry_at is None or int(item["block_time"]) < reentry_at
        ]
        if not cycle_sells:
            continue

        first_sell_qty = abs(float(cycle_sells[0]["token_change"]))
        total_sell_qty = sum(abs(float(item["token_change"])) for item in cycle_sells)
        first_fraction = 100.0 * first_sell_qty / bought_qty
        total_fraction = 100.0 * total_sell_qty / bought_qty
        runner = max(0.0, 100.0 - first_fraction)
        anomaly = first_fraction > 105.0 or total_fraction > 105.0

        observations.append(
            ExitSizingObservation(
                token_mint=token_mint,
                observed_bought_qty=bought_qty,
                first_sell_qty=first_sell_qty,
                total_cycle_sell_qty=total_sell_qty,
                sell_count=len(cycle_sells),
                first_sell_fraction_pct=first_fraction,
                total_sold_fraction_pct=total_fraction,
                observed_runner_after_first_sell_pct=runner,
                quantity_anomaly=anomaly,
                coverage_class=_coverage_class(total_fraction),
            )
        )

    observations.sort(key=lambda item: item.token_mint)
    return observations


def summarize_exit_sizing(
    observations: list[ExitSizingObservation] | tuple[ExitSizingObservation, ...],
) -> ExitSizingSummary:
    rows = list(observations)
    multi = [item for item in rows if item.sell_count >= 2]
    complete = [item for item in rows if item.coverage_class == "complete_like"]
    partial = [item for item in rows if item.coverage_class == "partial_or_open"]
    complete_multi = [item for item in complete if item.sell_count >= 2]
    return ExitSizingSummary(
        token_count=len(rows),
        multi_sell_token_count=len(multi),
        median_first_sell_fraction_pct=_median([item.first_sell_fraction_pct for item in rows]),
        median_total_sold_fraction_pct=_median([item.total_sold_fraction_pct for item in rows]),
        median_runner_after_first_sell_pct=_median(
            [item.observed_runner_after_first_sell_pct for item in multi]
        ),
        first_sell_below_50_share_pct=_share(
            [item.first_sell_fraction_pct < 50.0 for item in rows]
        ),
        multi_sell_share_pct=_share([item.sell_count >= 2 for item in rows]),
        quantity_anomaly_share_pct=_share([item.quantity_anomaly for item in rows]),
        complete_like_count=len(complete),
        partial_or_open_count=len(partial),
        complete_multi_sell_count=len(complete_multi),
        median_complete_multi_first_sell_fraction_pct=_median(
            [item.first_sell_fraction_pct for item in complete_multi]
        ),
        median_complete_multi_runner_pct=_median(
            [item.observed_runner_after_first_sell_pct for item in complete_multi]
        ),
    )
