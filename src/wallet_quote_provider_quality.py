from collections import Counter
from dataclasses import dataclass
from statistics import median

from src.causal_quote_store import ensure_causal_quote_schema
from src.database import connection
from src.wallet_quote_watch import ForwardBuyEvent, ensure_quote_attempt_schema


@dataclass(frozen=True)
class QuoteProviderQualityDelay:
    delay_seconds: int
    expected_count: int
    successful_quote_count: int
    metadata_count: int
    metadata_coverage_pct: float
    median_price_impact_pct_points: float | None
    p95_abs_price_impact_pct_points: float | None
    median_slippage_bps: float | None
    median_swap_usd_value: float | None
    routers: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class WalletQuoteProviderQualitySummary:
    buy_event_count: int
    expected_quote_count: int
    successful_quote_count: int
    metadata_count: int
    metadata_coverage_pct: float
    delays: tuple[QuoteProviderQualityDelay, ...]


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


def summarize_wallet_quote_provider_quality(
    events: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    *,
    delays_seconds: tuple[int, ...] | list[int],
) -> WalletQuoteProviderQualitySummary:
    """Summarize persisted Jupiter route metadata on the frozen expected event×delay grid.

    The provider fields are observational. Price impact is reported using Jupiter's raw sign;
    this module does not reinterpret it as realized slippage or fill cost. Historical quotes
    collected before metadata persistence remain NULL and are counted as missing metadata rather
    than retroactively reconstructed.
    """

    delays = tuple(dict.fromkeys(int(item) for item in delays_seconds))
    if any(delay < 0 for delay in delays):
        raise ValueError("quote delays must be non-negative")
    event_list = list(events)
    if len({item.id for item in event_list}) != len(event_list):
        raise ValueError("forward BUY event ids must be unique")

    expected_by_delay: dict[int, set[str]] = {
        delay: {
            f"wallet-forward:{event.id}:buy:+{delay}s:jupiter-v2"
            for event in event_list
        }
        for delay in delays
    }
    expected_all = set().union(*expected_by_delay.values()) if delays else set()
    rows_by_key: dict[str, dict] = {}

    ensure_quote_attempt_schema()
    ensure_causal_quote_schema()
    if expected_all:
        keys = tuple(sorted(expected_all))
        placeholders = ",".join("?" for _ in keys)
        with connection() as conn:
            result = conn.execute(
                f"""SELECT a.attempt_key, a.status, q.provider_router,
                    q.provider_slippage_bps, q.provider_price_impact_pct_points,
                    q.provider_swap_usd_value
                FROM causal_quote_attempts a
                LEFT JOIN causal_quote_observations q ON q.quote_key=a.quote_key
                WHERE a.attempt_key IN ({placeholders}) AND a.side='buy'""",
                keys,
            ).fetchall()
        rows_by_key = {str(row["attempt_key"]): dict(row) for row in result}

    delay_rows: list[QuoteProviderQualityDelay] = []
    successful_total = metadata_total = 0
    for delay in delays:
        expected = expected_by_delay[delay]
        successful = [
            rows_by_key[key]
            for key in expected
            if key in rows_by_key and rows_by_key[key].get("status") == "success"
        ]
        metadata = [
            row
            for row in successful
            if any(
                row.get(field) is not None
                for field in (
                    "provider_router",
                    "provider_slippage_bps",
                    "provider_price_impact_pct_points",
                    "provider_swap_usd_value",
                )
            )
        ]
        impacts = [
            float(row["provider_price_impact_pct_points"])
            for row in metadata
            if row.get("provider_price_impact_pct_points") is not None
        ]
        slippages = [
            float(row["provider_slippage_bps"])
            for row in metadata
            if row.get("provider_slippage_bps") is not None
        ]
        swap_values = [
            float(row["provider_swap_usd_value"])
            for row in metadata
            if row.get("provider_swap_usd_value") is not None
        ]
        routers = Counter(
            str(row["provider_router"])
            for row in metadata
            if row.get("provider_router")
        )
        successful_total += len(successful)
        metadata_total += len(metadata)
        delay_rows.append(
            QuoteProviderQualityDelay(
                delay_seconds=delay,
                expected_count=len(expected),
                successful_quote_count=len(successful),
                metadata_count=len(metadata),
                metadata_coverage_pct=(
                    100.0 * len(metadata) / len(successful) if successful else 0.0
                ),
                median_price_impact_pct_points=(median(impacts) if impacts else None),
                p95_abs_price_impact_pct_points=_percentile(
                    [abs(item) for item in impacts], 0.95
                ),
                median_slippage_bps=(median(slippages) if slippages else None),
                median_swap_usd_value=(median(swap_values) if swap_values else None),
                routers=tuple(routers.most_common()),
            )
        )

    return WalletQuoteProviderQualitySummary(
        buy_event_count=len(event_list),
        expected_quote_count=len(expected_all),
        successful_quote_count=successful_total,
        metadata_count=metadata_total,
        metadata_coverage_pct=(
            100.0 * metadata_total / successful_total if successful_total else 0.0
        ),
        delays=tuple(delay_rows),
    )
