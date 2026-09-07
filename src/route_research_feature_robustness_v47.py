from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from src.route_research_feature_review_v47 import CausalFeatureRowV47, GroupingV47


@dataclass(frozen=True)
class RobustReturnMetricsV47:
    n: int
    positive_share_pct: float | None
    mean_return_pct: float | None
    median_return_pct: float | None
    profit_factor: float | None
    best_return_pct: float | None
    worst_return_pct: float | None
    mean_without_best_pct: float | None
    largest_winner_share_gross_profit_pct: float | None


def robust_return_metrics_v47(values: list[float]) -> RobustReturnMetricsV47:
    normalized = [float(item) for item in values]
    if any(not math.isfinite(item) for item in normalized):
        raise ValueError("return values must be finite")
    if not normalized:
        return RobustReturnMetricsV47(
            n=0,
            positive_share_pct=None,
            mean_return_pct=None,
            median_return_pct=None,
            profit_factor=None,
            best_return_pct=None,
            worst_return_pct=None,
            mean_without_best_pct=None,
            largest_winner_share_gross_profit_pct=None,
        )

    positives = [item for item in normalized if item > 0]
    negatives = [item for item in normalized if item < 0]
    gross_profit = sum(positives)
    gross_loss = -sum(negatives)
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (math.inf if gross_profit > 0 else None)
    )
    best = max(normalized)
    mean_without_best = (
        (sum(normalized) - best) / (len(normalized) - 1)
        if len(normalized) > 1
        else None
    )
    largest_winner_share = (
        100.0 * max(positives) / gross_profit
        if gross_profit > 0 and positives
        else 0.0
    )
    return RobustReturnMetricsV47(
        n=len(normalized),
        positive_share_pct=100.0 * len(positives) / len(normalized),
        mean_return_pct=sum(normalized) / len(normalized),
        median_return_pct=float(median(normalized)),
        profit_factor=profit_factor,
        best_return_pct=best,
        worst_return_pct=min(normalized),
        mean_without_best_pct=mean_without_best,
        largest_winner_share_gross_profit_pct=largest_winner_share,
    )


def group_label_values_v47(
    *,
    rows: tuple[CausalFeatureRowV47, ...],
    grouping: GroupingV47,
    horizon_seconds: int,
    scope: str,
    group: str,
) -> list[float]:
    if scope not in {"A", "B", "ALL"}:
        raise ValueError("scope must be A, B, or ALL")
    if group not in grouping.ordered_groups:
        raise ValueError(f"unknown group {group!r} for feature {grouping.feature_name}")

    values: list[float] = []
    for row in rows:
        if scope != "ALL" and row.cohort != scope:
            continue
        key = (row.acquisition_run_key, row.episode_key)
        if grouping.assignments.get(key) != group:
            continue
        label = row.labels.get(horizon_seconds)
        if label is None:
            continue
        value = float(label)
        if not math.isfinite(value):
            raise ValueError("available label must be finite")
        values.append(value)
    return values
