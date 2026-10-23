from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import route_research_signal_plane_bridge_v0 as bridge
import signal_plane_v68_promotion_v0 as promotion
import src.route_research_forward_collection_v43 as forward_collection
from src.config import settings
from src.jupiter_research_exit_route import JupiterResearchExitRouteProbe
from src.opportunity_route_research_store import load_route_research_outcomes
from src.provider_start_pacer_v44 import ProviderStartPacerV44
from src.route_research_evaluation import evaluate_route_research_run


VERSION = "signal_plane_forward_cohort_v0"
SUBCOHORT_CAP = 40
SUBCOHORT_MIN_DECISIONS = 30


@dataclass(frozen=True)
class SignalPlaneForwardCohortResult:
    run_key: str
    bridge_classification: str
    decision_count: int
    scheduled_count: int
    exact_three_horizons_per_decision: bool
    forward_classification: str
    target_lateness_p95_seconds: int | None
    lineage_violations: int
    descriptive_ready_horizons: int
    passed: bool


class _PacedExitProbeSignalPlaneV0(JupiterResearchExitRouteProbe):
    pacer: ProviderStartPacerV44 | None = None

    def capture(self, outcome):
        if self.pacer is None:
            raise RuntimeError("signal-plane exit pacer not configured")
        self.pacer.wait_for_slot()
        return super().capture(outcome)


def _cohort_schedule_audit(run_key: str) -> tuple[int, int, bool]:
    outcomes = load_route_research_outcomes(acquisition_run_key=run_key)
    by_episode: dict[str, set[int]] = {}
    for item in outcomes:
        by_episode.setdefault(item.episode_key, set()).add(item.horizon_seconds)
    complete = sum(
        1
        for horizons in by_episode.values()
        if horizons == {300, 900, 3600}
    )
    return len(by_episode), len(outcomes), complete == len(by_episode)


def _descriptive_readiness(run_key: str) -> tuple[int, int]:
    evaluation = evaluate_route_research_run(acquisition_run_key=run_key)
    ready = sum(
        1
        for metrics in evaluation.horizons
        if metrics.classification == "DESCRIPTIVE_SAMPLE_READY_FOR_ANALYSIS"
    )
    return int(evaluation.lineage_violations), ready


def run_signal_plane_forward_cohort_v0(
    *,
    run_key: str,
    bootstrap_report: Path,
    promotion_report: Path | None = None,
    acquisition_duration_seconds: float = 120.0,
    cargo: str = "cargo",
    max_episodes: int = SUBCOHORT_CAP,
    min_research_decisions: int = SUBCOHORT_MIN_DECISIONS,
    research_workers: int = 4,
    hazard_workers: int = 4,
    forward_workers: int = 6,
    forward_poll_ms: int = 100,
    target_lateness_p95_max_seconds: int = 2,
    hazard_wait_timeout_seconds: int = 30,
    hazard_rpc_timeout_seconds: int = 3,
    jupiter_timeout_seconds: int = 5,
    research_notional_usd: float = 25.0,
    research_slippage_bps: int = 100,
    hazard_start_interval_ms: int = 650,
    entry_start_interval_ms: int = 1000,
    exit_start_interval_ms: int = 250,
    downstream_drain_timeout_seconds: float = 120.0,
    artifact_root: Path = Path("artifacts/signal_plane_forward_cohort_v0"),
) -> SignalPlaneForwardCohortResult:
    base = str(run_key).strip()
    if not base:
        raise ValueError("run_key cannot be empty")
    is_v68_fresh = "v68-flow60-fresh" in base.lower()
    if is_v68_fresh:
        if promotion_report is None:
            raise ValueError(
                "fresh V68 Signal Plane cohort requires a promotion report"
            )
        promotion_ok, promotion_detail = promotion.validate_promotion_report(
            Path(promotion_report)
        )
        if not promotion_ok:
            raise ValueError(
                "fresh V68 Signal Plane cohort promotion invalid: "
                + promotion_detail
            )
    if max_episodes != SUBCOHORT_CAP:
        raise ValueError(
            f"Signal Plane V68 migration freezes max_episodes={SUBCOHORT_CAP}"
        )
    if min_research_decisions != SUBCOHORT_MIN_DECISIONS:
        raise ValueError(
            "Signal Plane V68 migration freezes "
            f"min_research_decisions={SUBCOHORT_MIN_DECISIONS}"
        )
    if min(
        acquisition_duration_seconds,
        research_workers,
        hazard_workers,
        forward_workers,
        forward_poll_ms,
        target_lateness_p95_max_seconds,
        hazard_wait_timeout_seconds,
        hazard_rpc_timeout_seconds,
        jupiter_timeout_seconds,
        downstream_drain_timeout_seconds,
    ) <= 0:
        raise ValueError("cohort counts/timeouts must be positive")
    if min(
        hazard_start_interval_ms,
        entry_start_interval_ms,
        exit_start_interval_ms,
    ) < 0:
        raise ValueError("provider pacing intervals cannot be negative")
    if research_notional_usd != 25.0:
        raise ValueError("V68 migration freezes research_notional_usd=25.0")
    if research_slippage_bps != 100:
        raise ValueError("V68 migration freezes research_slippage_bps=100")

    artifact_root.mkdir(parents=True, exist_ok=True)
    shadow_output = artifact_root / f"{base}-signal-plane-shadow.json"
    bridge_output = artifact_root / f"{base}-route-research-bridge.json"

    bridge_report = asyncio.run(
        bridge.run_bridge(
            run_key=base,
            bootstrap_report=Path(bootstrap_report),
            allow_v68_fresh_run_key=is_v68_fresh,
            duration_seconds=acquisition_duration_seconds,
            shadow_output=shadow_output,
            report_output=bridge_output,
            cargo=cargo,
            max_episodes=max_episodes,
            research_workers=research_workers,
            hazard_workers=hazard_workers,
            hazard_wait_timeout_seconds=hazard_wait_timeout_seconds,
            hazard_rpc_timeout_seconds=hazard_rpc_timeout_seconds,
            jupiter_timeout_seconds=jupiter_timeout_seconds,
            research_notional_usd=research_notional_usd,
            research_slippage_bps=research_slippage_bps,
            hazard_start_interval_ms=hazard_start_interval_ms,
            entry_start_interval_ms=entry_start_interval_ms,
            downstream_drain_timeout_seconds=downstream_drain_timeout_seconds,
        )
    )

    if bridge_report.get("classification") != bridge.PASS_CLASSIFICATION:
        return SignalPlaneForwardCohortResult(
            run_key=base,
            bridge_classification=str(bridge_report.get("classification")),
            decision_count=0,
            scheduled_count=0,
            exact_three_horizons_per_decision=False,
            forward_classification="NOT_STARTED_BRIDGE_FAIL",
            target_lateness_p95_seconds=None,
            lineage_violations=0,
            descriptive_ready_horizons=0,
            passed=False,
        )

    decision_count, scheduled_count, schedule_complete = _cohort_schedule_audit(base)
    if (
        decision_count < min_research_decisions
        or not schedule_complete
        or scheduled_count != decision_count * 3
    ):
        return SignalPlaneForwardCohortResult(
            run_key=base,
            bridge_classification=str(bridge_report["classification"]),
            decision_count=decision_count,
            scheduled_count=scheduled_count,
            exact_three_horizons_per_decision=schedule_complete,
            forward_classification="INCONCLUSIVE_SIGNAL_PLANE_COHORT_LT_MINIMUM",
            target_lateness_p95_seconds=None,
            lineage_violations=0,
            descriptive_ready_horizons=0,
            passed=False,
        )

    exit_pacer = ProviderStartPacerV44(interval_ms=exit_start_interval_ms)
    _PacedExitProbeSignalPlaneV0.pacer = exit_pacer
    original_probe = forward_collection.JupiterResearchExitRouteProbe
    try:
        forward_collection.JupiterResearchExitRouteProbe = (
            _PacedExitProbeSignalPlaneV0
        )
        collection = forward_collection.collect_route_research_forward_v43(
            acquisition_run_key=base,
            api_key=settings.jupiter_api_key,
            workers=forward_workers,
            poll_ms=forward_poll_ms,
            jupiter_timeout_seconds=jupiter_timeout_seconds,
            slippage_bps=research_slippage_bps,
        )
    finally:
        forward_collection.JupiterResearchExitRouteProbe = original_probe
        _PacedExitProbeSignalPlaneV0.pacer = None

    lateness_p95 = collection.target_lateness_p95_seconds
    lineage_violations, ready_horizons = _descriptive_readiness(base)
    passed = (
        collection.classification
        == "PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE"
        and lateness_p95 is not None
        and lateness_p95 <= target_lateness_p95_max_seconds
        and lineage_violations == 0
        and ready_horizons == 3
    )

    return SignalPlaneForwardCohortResult(
        run_key=base,
        bridge_classification=str(bridge_report["classification"]),
        decision_count=decision_count,
        scheduled_count=scheduled_count,
        exact_three_horizons_per_decision=schedule_complete,
        forward_classification=collection.classification,
        target_lateness_p95_seconds=lateness_p95,
        lineage_violations=lineage_violations,
        descriptive_ready_horizons=ready_horizons,
        passed=passed,
    )
