from __future__ import annotations

from dataclasses import dataclass
import math

from src.route_research_feature_review_v47 import CausalFeatureRowV47
from src.route_research_feature_robustness_v47 import (
    RobustReturnMetricsV47,
    robust_return_metrics_v47,
)


V48_FEATURE_NAME = "flow60_event_count"
V48_PRIMARY_HORIZON_SECONDS = 900
V48_LOW_MAX = 25
V48_MID_MAX = 47
V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT = 5
V48_GROUPS = ("LOW", "MID", "HIGH")


@dataclass(frozen=True)
class PrimaryGateV48:
    classification: str
    feature_known: int
    feature_total: int
    feature_coverage_pct: float
    support_ok: bool
    same_direction_ok: bool
    low_positive_median_both: bool
    low_pf_gt_one_both: bool
    aggregate_low_pf_gt_one: bool
    aggregate_low_mean_without_best_positive: bool


def frozen_flow60_group_v48(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("flow60_event_count must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("flow60_event_count must be finite")
    if numeric < 0:
        raise ValueError("flow60_event_count cannot be negative")
    if numeric <= V48_LOW_MAX:
        return "LOW"
    if numeric <= V48_MID_MAX:
        return "MID"
    return "HIGH"


def feature_coverage_v48(rows: tuple[CausalFeatureRowV47, ...]) -> tuple[int, int, float]:
    known = 0
    for row in rows:
        value = row.features.get(V48_FEATURE_NAME)
        if value is None:
            continue
        frozen_flow60_group_v48(value)
        known += 1
    total = len(rows)
    return known, total, (100.0 * known / total if total else 0.0)


def group_metrics_v48(
    *,
    rows: tuple[CausalFeatureRowV47, ...],
    horizon_seconds: int,
    scope: str,
) -> dict[str, RobustReturnMetricsV47]:
    if scope not in {"A", "B", "ALL"}:
        raise ValueError("scope must be A, B, or ALL")
    values: dict[str, list[float]] = {group: [] for group in V48_GROUPS}
    for row in rows:
        if scope != "ALL" and row.cohort != scope:
            continue
        raw = row.features.get(V48_FEATURE_NAME)
        if raw is None:
            continue
        group = frozen_flow60_group_v48(raw)
        label = row.labels.get(horizon_seconds)
        if label is None:
            continue
        numeric = float(label)
        if not math.isfinite(numeric):
            raise ValueError("available route-only label must be finite")
        values[group].append(numeric)
    return {group: robust_return_metrics_v47(values[group]) for group in V48_GROUPS}


def _median_delta_low_minus_high(metrics: dict[str, RobustReturnMetricsV47]) -> float | None:
    low = metrics["LOW"].median_return_pct
    high = metrics["HIGH"].median_return_pct
    if low is None or high is None:
        return None
    return low - high


def primary_gate_v48(*, rows: tuple[CausalFeatureRowV47, ...]) -> PrimaryGateV48:
    known, total, coverage = feature_coverage_v48(rows)
    if total == 0 or known != total:
        return PrimaryGateV48(
            classification="FAIL_V48_FEATURE_OBSERVABILITY",
            feature_known=known,
            feature_total=total,
            feature_coverage_pct=coverage,
            support_ok=False,
            same_direction_ok=False,
            low_positive_median_both=False,
            low_pf_gt_one_both=False,
            aggregate_low_pf_gt_one=False,
            aggregate_low_mean_without_best_positive=False,
        )

    by_scope = {
        scope: group_metrics_v48(
            rows=rows,
            horizon_seconds=V48_PRIMARY_HORIZON_SECONDS,
            scope=scope,
        )
        for scope in ("A", "B", "ALL")
    }
    support_ok = all(
        by_scope[scope]["LOW"].n >= V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT
        and by_scope[scope]["HIGH"].n >= V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT
        for scope in ("A", "B")
    )
    if not support_ok:
        return PrimaryGateV48(
            classification="INCONCLUSIVE_V48_PRIMARY_SUPPORT",
            feature_known=known,
            feature_total=total,
            feature_coverage_pct=coverage,
            support_ok=False,
            same_direction_ok=False,
            low_positive_median_both=False,
            low_pf_gt_one_both=False,
            aggregate_low_pf_gt_one=False,
            aggregate_low_mean_without_best_positive=False,
        )

    deltas = {scope: _median_delta_low_minus_high(by_scope[scope]) for scope in ("A", "B", "ALL")}
    same_direction_ok = all(delta is not None and delta > 0 for delta in deltas.values())
    low_positive_median_both = all(
        by_scope[scope]["LOW"].median_return_pct is not None
        and by_scope[scope]["LOW"].median_return_pct > 0
        for scope in ("A", "B")
    )
    low_pf_gt_one_both = all(
        by_scope[scope]["LOW"].profit_factor is not None
        and by_scope[scope]["LOW"].profit_factor > 1
        for scope in ("A", "B")
    )
    aggregate_low_pf_gt_one = (
        by_scope["ALL"]["LOW"].profit_factor is not None
        and by_scope["ALL"]["LOW"].profit_factor > 1
    )
    aggregate_low_mean_without_best_positive = (
        by_scope["ALL"]["LOW"].mean_without_best_pct is not None
        and by_scope["ALL"]["LOW"].mean_without_best_pct > 0
    )
    passed = all(
        (
            same_direction_ok,
            low_positive_median_both,
            low_pf_gt_one_both,
            aggregate_low_pf_gt_one,
            aggregate_low_mean_without_best_positive,
        )
    )
    return PrimaryGateV48(
        classification=(
            "PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS"
            if passed
            else "FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS"
        ),
        feature_known=known,
        feature_total=total,
        feature_coverage_pct=coverage,
        support_ok=True,
        same_direction_ok=same_direction_ok,
        low_positive_median_both=low_positive_median_both,
        low_pf_gt_one_both=low_pf_gt_one_both,
        aggregate_low_pf_gt_one=aggregate_low_pf_gt_one,
        aggregate_low_mean_without_best_positive=aggregate_low_mean_without_best_positive,
    )
