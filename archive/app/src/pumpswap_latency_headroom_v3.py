from __future__ import annotations

from dataclasses import dataclass

from src.pumpswap_sequence_barrier_trace_v50 import percentile_v50


OFFICIAL_PIPELINE_P95_SECONDS = 5.0
EARLY_WARNING_FRACTION = 0.80
EARLY_WARNING_SECONDS = OFFICIAL_PIPELINE_P95_SECONDS * EARLY_WARNING_FRACTION


@dataclass(frozen=True)
class LatencyStageHeadroomV3:
    stage: str
    p95_seconds: float
    share_of_official_gate_pct: float
    early_warning: bool


@dataclass(frozen=True)
class LatencyHeadroomReportV3:
    stages: tuple[LatencyStageHeadroomV3, ...]
    dominant_stage: str
    dominant_stage_p95_seconds: float
    warning_stages: tuple[str, ...]


def _stage(name: str, values) -> LatencyStageHeadroomV3:
    p95 = percentile_v50(tuple(float(value) for value in values), 0.95)
    return LatencyStageHeadroomV3(
        stage=name,
        p95_seconds=p95,
        share_of_official_gate_pct=(
            100.0 * p95 / OFFICIAL_PIPELINE_P95_SECONDS
            if OFFICIAL_PIPELINE_P95_SECONDS
            else 0.0
        ),
        early_warning=p95 >= EARLY_WARNING_SECONDS,
    )


def build_latency_headroom_report_v3(
    *,
    sequence_snapshot,
    resolver_snapshot,
    priority_snapshot=None,
    commit_snapshot=None,
) -> LatencyHeadroomReportV3:
    """Build non-authoritative early warnings from already-observed causal stage clocks.

    The official systems gate remains Pump/PumpSwap end-to-end p95 <=5s. This report intentionally
    does not create a second pass/fail rule and does not add stage latencies together because many
    stages overlap. It only warns when one individual stage consumes >=80% of the official budget,
    giving engineering headroom before the frozen gate is actually breached.
    """

    rows = tuple(sequence_snapshot.rows)
    stages = [
        _stage(
            "self_ingress_to_normalization",
            (row.self_ingress_to_normalization_seconds for row in rows),
        ),
        _stage(
            "global_prefix_normalization_barrier",
            (row.prefix_normalization_barrier_seconds for row in rows),
        ),
        _stage(
            "reservation_to_submit",
            (
                row.reservation_to_submit_seconds
                for row in rows
                if row.reservation_to_submit_seconds is not None
            ),
        ),
        _stage(
            "submit_to_dependency_ready",
            (
                row.submit_to_dependency_ready_seconds
                for row in rows
                if row.submit_to_dependency_ready_seconds is not None
            ),
        ),
        _stage("resolver_total", resolver_snapshot.total_resolve_seconds),
        _stage("resolver_pool_lock_hold", resolver_snapshot.pool_lock_hold_seconds),
        _stage("resolver_network_account_wait", resolver_snapshot.network_account_wait_seconds),
        _stage("resolver_durable_mapping_write", resolver_snapshot.durable_mapping_write_seconds),
        _stage("resolver_canonical_reload", resolver_snapshot.canonical_reload_seconds),
    ]

    if priority_snapshot is not None:
        stages.extend(
            [
                _stage(
                    "stateful_ready_queue",
                    priority_snapshot.stateful_queue_wait_seconds,
                ),
                _stage(
                    "demoted_ready_queue",
                    priority_snapshot.demoted_queue_wait_seconds,
                ),
            ]
        )

    if commit_snapshot is not None:
        stages.extend(
            [
                _stage(
                    "pump_commit_lane_queue",
                    commit_snapshot.pump_lane_queue_wait_seconds,
                ),
                _stage(
                    "pumpswap_commit_lane_queue",
                    commit_snapshot.pumpswap_lane_queue_wait_seconds,
                ),
                _stage(
                    "cross_source_token_lock",
                    commit_snapshot.token_lock_wait_seconds,
                ),
            ]
        )

    dominant = max(stages, key=lambda item: item.p95_seconds)
    warnings = tuple(item.stage for item in stages if item.early_warning)
    return LatencyHeadroomReportV3(
        stages=tuple(stages),
        dominant_stage=dominant.stage,
        dominant_stage_p95_seconds=dominant.p95_seconds,
        warning_stages=warnings,
    )
