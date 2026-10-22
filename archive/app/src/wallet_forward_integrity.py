import math
import statistics
from dataclasses import dataclass

from src.opportunity_intelligence import WalletActionObservation


@dataclass(frozen=True)
class ForwardRunIntegritySummary:
    action_count: int
    observed_before_run_count: int
    chain_before_run_count: int
    negative_source_lag_count: int
    source_lag_over_300s_count: int
    source_lag_over_3600s_count: int
    source_lag_over_300s_share_pct: float
    max_source_lag_seconds: float | None
    median_source_lag_seconds: float | None
    p95_source_lag_seconds: float | None
    integrity_label: str


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))]


def summarize_forward_run_integrity(
    actions: list[WalletActionObservation] | tuple[WalletActionObservation, ...],
    *,
    run_started_at: int,
) -> ForwardRunIntegritySummary:
    """Audit causality boundaries without silently deleting suspicious observations.

    ``chain_before_run_count`` is deliberately reported rather than auto-dropped. A transaction
    can become observable shortly after the run starts even if its chain timestamp is a few
    seconds earlier; large source lag is the stronger sign of stale/bootstrap backfill. The v2
    collector prevents pre-start chain timestamps prospectively, but this audit keeps older runs
    interpretable instead of rewriting them.
    """

    if run_started_at < 0:
        raise ValueError("run_started_at must be non-negative")

    values: list[float] = []
    observed_before = chain_before = negative = over_300 = over_3600 = 0
    for item in actions:
        if item.chain_time < 0 or item.observed_at < 0:
            raise ValueError("wallet timestamps must be non-negative")
        lag = float(item.observed_at - item.chain_time)
        values.append(lag)
        observed_before += item.observed_at < run_started_at
        chain_before += item.chain_time < run_started_at
        negative += lag < 0
        over_300 += lag > 300
        over_3600 += lag > 3600

    count = len(actions)
    if negative or observed_before:
        label = "CAUSAL_BOUNDARY_FAILED"
    elif over_3600:
        label = "STALE_SOURCE_CRITICAL"
    elif over_300:
        label = "STALE_SOURCE_CAUTION"
    elif chain_before:
        label = "PRESTART_CHAIN_CAUTION"
    else:
        label = "CAUSAL_BOUNDARY_CLEAN"

    return ForwardRunIntegritySummary(
        action_count=count,
        observed_before_run_count=observed_before,
        chain_before_run_count=chain_before,
        negative_source_lag_count=negative,
        source_lag_over_300s_count=over_300,
        source_lag_over_3600s_count=over_3600,
        source_lag_over_300s_share_pct=(100.0 * over_300 / count if count else 0.0),
        max_source_lag_seconds=(max(values) if values else None),
        median_source_lag_seconds=(statistics.median(values) if values else None),
        p95_source_lag_seconds=_p95(values),
        integrity_label=label,
    )
