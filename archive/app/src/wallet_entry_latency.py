import math
import statistics
from dataclasses import dataclass

from src.wallet_quote_drift import WalletQuotePathPoint


@dataclass(frozen=True)
class WalletEntryLatencyDelaySummary:
    delay_seconds: int
    buy_event_count: int
    quoted_event_count: int
    coverage_pct: float
    median_chain_to_detection_seconds: float | None
    median_detection_to_quote_seconds: float | None
    median_chain_to_quote_seconds: float | None
    p95_chain_to_quote_seconds: float | None
    max_chain_to_quote_seconds: float | None
    within_30s_share_pct: float
    within_60s_share_pct: float
    within_120s_share_pct: float


@dataclass(frozen=True)
class WalletEntryLatencySummary:
    buy_event_count: int
    wallet_count: int
    token_count: int
    delays: tuple[WalletEntryLatencyDelaySummary, ...]


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[index]


def _share(values: list[float], threshold: float) -> float:
    return 100.0 * sum(value <= threshold for value in values) / len(values) if values else 0.0


def summarize_wallet_entry_latency(
    points: list[WalletQuotePathPoint] | tuple[WalletQuotePathPoint, ...],
    *,
    buy_event_count: int,
) -> WalletEntryLatencySummary:
    """Summarize actual chain-time -> route-quote availability.

    Quote delays in Wallet Quote Watch are scheduled *after detection*. They are not end-to-end
    delays from the source wallet's on-chain swap. This audit makes that distinction explicit:

        chain_time -> observed_at -> configured delay -> scheduler/request -> quote_observed_at

    The output is purely an observability/execution-path diagnostic. It does not measure PnL,
    fill probability or strategy edge.
    """
    if buy_event_count < 0:
        raise ValueError("buy_event_count must be non-negative")

    # Keep at most one successful quote per event/delay. If malformed duplicate data exists,
    # choose the earliest received quote deterministically rather than double-counting it.
    unique: dict[tuple[str, int], WalletQuotePathPoint] = {}
    for item in points:
        if item.delay_seconds < 0:
            raise ValueError("quote delay must be non-negative")
        if item.wallet_observed_at < item.wallet_chain_time:
            raise ValueError("wallet observation cannot precede chain time")
        if item.quote_observed_at < item.wallet_observed_at:
            raise ValueError("quote observation cannot precede wallet detection")
        key = (item.source_event_key, item.delay_seconds)
        current = unique.get(key)
        if current is None or (
            item.quote_observed_at,
            item.completed_at,
            item.requested_at,
        ) < (
            current.quote_observed_at,
            current.completed_at,
            current.requested_at,
        ):
            unique[key] = item

    selected = tuple(unique.values())
    summaries: list[WalletEntryLatencyDelaySummary] = []
    for delay in sorted({item.delay_seconds for item in selected}):
        group = [item for item in selected if item.delay_seconds == delay]
        chain_to_detection = [
            float(item.wallet_observed_at - item.wallet_chain_time) for item in group
        ]
        detection_to_quote = [
            float(item.quote_observed_at - item.wallet_observed_at) for item in group
        ]
        chain_to_quote = [
            float(item.quote_observed_at - item.wallet_chain_time) for item in group
        ]
        summaries.append(
            WalletEntryLatencyDelaySummary(
                delay_seconds=delay,
                buy_event_count=buy_event_count,
                quoted_event_count=len(group),
                coverage_pct=(100.0 * len(group) / buy_event_count if buy_event_count else 0.0),
                median_chain_to_detection_seconds=(
                    statistics.median(chain_to_detection) if chain_to_detection else None
                ),
                median_detection_to_quote_seconds=(
                    statistics.median(detection_to_quote) if detection_to_quote else None
                ),
                median_chain_to_quote_seconds=(
                    statistics.median(chain_to_quote) if chain_to_quote else None
                ),
                p95_chain_to_quote_seconds=_p95(chain_to_quote),
                max_chain_to_quote_seconds=(max(chain_to_quote) if chain_to_quote else None),
                within_30s_share_pct=_share(chain_to_quote, 30.0),
                within_60s_share_pct=_share(chain_to_quote, 60.0),
                within_120s_share_pct=_share(chain_to_quote, 120.0),
            )
        )

    # Wallet/token counts describe the successful route sample, not all BUYs. Coverage remains
    # explicit in each delay so missing quotes cannot disappear from interpretation.
    return WalletEntryLatencySummary(
        buy_event_count=buy_event_count,
        wallet_count=len({item.wallet_address for item in selected}),
        token_count=len({item.token_mint for item in selected}),
        delays=tuple(summaries),
    )
