import math
import statistics
from dataclasses import dataclass

from src.wallet_quote_watch import ForwardBuyEvent


DEFAULT_FOLLOWUP_HORIZONS_SECONDS = (15 * 60, 60 * 60, 6 * 60 * 60, 24 * 60 * 60)


@dataclass(frozen=True)
class ForwardExposureHorizonSummary:
    horizon_seconds: int
    eligible_buy_count: int
    ineligible_buy_count: int
    eligible_share_pct: float


@dataclass(frozen=True)
class WalletForwardExposureSummary:
    buy_count: int
    median_remaining_observation_seconds: float | None
    p10_remaining_observation_seconds: float | None
    min_remaining_observation_seconds: int | None
    max_remaining_observation_seconds: int | None
    horizons: tuple[ForwardExposureHorizonSummary, ...]


def _percentile_nearest_rank(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 <= percentile <= 1:
        raise ValueError("percentile must be between zero and one")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def summarize_wallet_forward_exposure(
    events: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    *,
    observation_window_end_at: int,
    horizons_seconds: tuple[int, ...] | list[int] = DEFAULT_FOLLOWUP_HORIZONS_SECONDS,
) -> WalletForwardExposureSummary:
    """Measure how much follow-up time each causal BUY actually had inside one run.

    Remaining exposure is measured from ``observed_at`` rather than ``chain_time`` because the
    system cannot prospectively observe a wallet action before it detects it. A BUY near the end
    of a bounded run is right-censored: absence of a later SELL/reentry is not evidence that the
    wallet would have held indefinitely.
    """

    if observation_window_end_at < 0:
        raise ValueError("observation window end must be non-negative")
    horizons = tuple(dict.fromkeys(int(item) for item in horizons_seconds))
    if any(item <= 0 for item in horizons):
        raise ValueError("follow-up horizons must be positive")

    items = list(events)
    if len({item.observation_key for item in items}) != len(items):
        raise ValueError("forward BUY events must be unique")

    remaining: list[int] = []
    for event in items:
        if event.observed_at > observation_window_end_at:
            raise ValueError("BUY observed_at cannot exceed observation window end")
        remaining.append(observation_window_end_at - event.observed_at)

    horizon_rows: list[ForwardExposureHorizonSummary] = []
    for horizon in horizons:
        eligible = sum(value >= horizon for value in remaining)
        total = len(remaining)
        horizon_rows.append(
            ForwardExposureHorizonSummary(
                horizon_seconds=horizon,
                eligible_buy_count=eligible,
                ineligible_buy_count=total - eligible,
                eligible_share_pct=(100.0 * eligible / total if total else 0.0),
            )
        )

    return WalletForwardExposureSummary(
        buy_count=len(items),
        median_remaining_observation_seconds=(
            float(statistics.median(remaining)) if remaining else None
        ),
        p10_remaining_observation_seconds=_percentile_nearest_rank(remaining, 0.10),
        min_remaining_observation_seconds=(min(remaining) if remaining else None),
        max_remaining_observation_seconds=(max(remaining) if remaining else None),
        horizons=tuple(horizon_rows),
    )
