from __future__ import annotations

from dataclasses import dataclass
import math

from src.route_research_feature_review_v47 import CausalFeatureRowV47
from src.route_research_feature_robustness_v47 import (
    RobustReturnMetricsV47,
    robust_return_metrics_v47,
)


V68_FEATURE_NAME = "flow60_buy_share_pct"
V68_PRIMARY_HORIZON_SECONDS = 900
# Canonical published cutpoints from the completed v55 discovery output.
# They are frozen exactly as published before any v68 acquisition begins.
V68_LOW_MAX = 57.1429
V68_MID_MAX = 65.7143
V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT = 5
V68_GROUPS = ("LOW", "MID", "HIGH")
V68_FAVORABLE_GROUP = "LOW"
V68_OPPOSITE_GROUP = "HIGH"


@dataclass(frozen=True)
class PrimaryGateV68:
    classification: str
    feature_known: int
    feature_total: int
    feature_coverage_pct: float
    support_ok: bool
    same_direction_ok: bool
    favorable_positive_median_both: bool
    favorable_pf_gt_one_both: bool
    aggregate_favorable_pf_gt_one: bool
    aggregate_favorable_mean_without_best_positive: bool


def frozen_flow60_buy_share_group_v68(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("flow60_buy_share_pct must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("flow60_buy_share_pct must be finite")
    if not 0.0 <= numeric <= 100.0:
        raise ValueError("flow60_buy_share_pct must be between 0 and 100")
    if numeric <= V68_LOW_MAX:
        return "LOW"
    if numeric <= V68_MID_MAX:
        return "MID"
    return "HIGH"


def feature_coverage_v68(rows: tuple[CausalFeatureRowV47, ...]) -> tuple[int, int, float]:
    known = 0
    for row in rows:
        value = row.features.get(V68_FEATURE_NAME)
        if value is None:
            continue
        frozen_flow60_buy_share_group_v68(value)
        known += 1
    total = len(rows)
    return known, total, (100.0 * known / total if total else 0.0)


def group_metrics_v68(
    *,
    rows: tuple[CausalFeatureRowV47, ...],
    horizon_seconds: int,
    scope: str,
) -> dict[str, RobustReturnMetricsV47]:
    if scope not in {"A", "B", "ALL"}:
        raise ValueError("scope must be A, B, or ALL")
    values: dict[str, list[float]] = {group: [] for group in V68_GROUPS}
    for row in rows:
        if scope != "ALL" and row.cohort != scope:
            continue
        raw = row.features.get(V68_FEATURE_NAME)
        if raw is None:
            continue
        group = frozen_flow60_buy_share_group_v68(raw)
        label = row.labels.get(horizon_seconds)
        if label is None:
            continue
        numeric = float(label)
        if not math.isfinite(numeric):
            raise ValueError("available route-only label must be finite")
        values[group].append(numeric)
    return {group: robust_return_metrics_v47(values[group]) for group in V68_GROUPS}


def _favorable_minus_opposite_median(
    metrics: dict[str, RobustReturnMetricsV47],
) -> float | None:
    favorable = metrics[V68_FAVORABLE_GROUP].median_return_pct
    opposite = metrics[V68_OPPOSITE_GROUP].median_return_pct
    if favorable is None or opposite is None:
        return None
    return favorable - opposite


def primary_gate_v68(*, rows: tuple[CausalFeatureRowV47, ...]) -> PrimaryGateV68:
    known, total, coverage = feature_coverage_v68(rows)
    if total == 0 or known != total:
        return PrimaryGateV68(
            classification="FAIL_V68_FEATURE_OBSERVABILITY",
            feature_known=known,
            feature_total=total,
            feature_coverage_pct=coverage,
            support_ok=False,
            same_direction_ok=False,
            favorable_positive_median_both=False,
            favorable_pf_gt_one_both=False,
            aggregate_favorable_pf_gt_one=False,
            aggregate_favorable_mean_without_best_positive=False,
        )

    by_scope = {
        scope: group_metrics_v68(
            rows=rows,
            horizon_seconds=V68_PRIMARY_HORIZON_SECONDS,
            scope=scope,
        )
        for scope in ("A", "B", "ALL")
    }

    support_ok = all(
        by_scope[scope][V68_FAVORABLE_GROUP].n >= V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT
        and by_scope[scope][V68_OPPOSITE_GROUP].n >= V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT
        for scope in ("A", "B")
    )
    if not support_ok:
        return PrimaryGateV68(
            classification="INCONCLUSIVE_V68_PRIMARY_SUPPORT",
            feature_known=known,
            feature_total=total,
            feature_coverage_pct=coverage,
            support_ok=False,
            same_direction_ok=False,
            favorable_positive_median_both=False,
            favorable_pf_gt_one_both=False,
            aggregate_favorable_pf_gt_one=False,
            aggregate_favorable_mean_without_best_positive=False,
        )

    deltas = {
        scope: _favorable_minus_opposite_median(by_scope[scope])
        for scope in ("A", "B", "ALL")
    }
    same_direction_ok = all(delta is not None and delta > 0 for delta in deltas.values())

    favorable_positive_median_both = all(
        by_scope[scope][V68_FAVORABLE_GROUP].median_return_pct is not None
        and by_scope[scope][V68_FAVORABLE_GROUP].median_return_pct > 0
        for scope in ("A", "B")
    )
    favorable_pf_gt_one_both = all(
        by_scope[scope][V68_FAVORABLE_GROUP].profit_factor is not None
        and by_scope[scope][V68_FAVORABLE_GROUP].profit_factor > 1
        for scope in ("A", "B")
    )
    aggregate_favorable_pf_gt_one = (
        by_scope["ALL"][V68_FAVORABLE_GROUP].profit_factor is not None
        and by_scope["ALL"][V68_FAVORABLE_GROUP].profit_factor > 1
    )
    aggregate_favorable_mean_without_best_positive = (
        by_scope["ALL"][V68_FAVORABLE_GROUP].mean_without_best_pct is not None
        and by_scope["ALL"][V68_FAVORABLE_GROUP].mean_without_best_pct > 0
    )

    passed = all(
        (
            same_direction_ok,
            favorable_positive_median_both,
            favorable_pf_gt_one_both,
            aggregate_favorable_pf_gt_one,
            aggregate_favorable_mean_without_best_positive,
        )
    )
    return PrimaryGateV68(
        classification=(
            "PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS"
            if passed
            else "FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS"
        ),
        feature_known=known,
        feature_total=total,
        feature_coverage_pct=coverage,
        support_ok=True,
        same_direction_ok=same_direction_ok,
        favorable_positive_median_both=favorable_positive_median_both,
        favorable_pf_gt_one_both=favorable_pf_gt_one_both,
        aggregate_favorable_pf_gt_one=aggregate_favorable_pf_gt_one,
        aggregate_favorable_mean_without_best_positive=(
            aggregate_favorable_mean_without_best_positive
        ),
    )
