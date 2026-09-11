"""Pre-economic integrity audit for Market Activity Discovery V0.

This report intentionally never loads quote prices, returns, MFE, MAE, or any economic
label. It reconciles only the preregistered run denominator, immutable cohort dispositions,
T0 lineage, and forward-outcome scheduling/status so operational integrity can be judged
before feature/outcome associations are inspected.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_activity_discovery_cohort_v0 import load_market_activity_discovery_members_v0
from src.market_activity_discovery_run_v0 import load_market_activity_discovery_run_v0
from src.market_activity_discovery_scanner_v0 import (
    load_market_activity_discovery_candidate_episodes_v0,
)
from src.opportunity_forward_outcome_store import (
    FORWARD_OUTCOME_HORIZONS_SECONDS,
    load_opportunity_forward_outcomes,
)


MARKET_ACTIVITY_DISCOVERY_AUDIT_VERSION = "market_activity_discovery_audit_v0_pre_economic"


@dataclass(frozen=True)
class MarketActivityDiscoveryOutcomeStatusCountV0:
    horizon_seconds: int
    status: str
    count: int


@dataclass(frozen=True)
class MarketActivityDiscoveryAuditV0:
    method_version: str
    acquisition_run_key: str
    cohort_key: str
    run_status: str
    candidate_episode_count: int
    cohort_denominator: int
    disposition_counts: tuple[tuple[str, int], ...]
    analyzable_t0_count: int
    unregistered_candidate_episode_keys: tuple[str, ...]
    analyzable_missing_snapshot_lineage_episode_keys: tuple[str, ...]
    analyzable_missing_forward_horizons: tuple[tuple[str, tuple[int, ...]], ...]
    unexpected_outcome_episode_keys: tuple[str, ...]
    outcome_status_counts: tuple[MarketActivityDiscoveryOutcomeStatusCountV0, ...]
    integrity_ready_for_close_or_analysis: bool
    economic_edge_evaluated: bool


def build_market_activity_discovery_audit_v0(
    *,
    acquisition_run_key: str,
) -> MarketActivityDiscoveryAuditV0:
    """Reconcile denominator/T0/outcome metadata without inspecting economic values."""

    run = load_market_activity_discovery_run_v0(acquisition_run_key=acquisition_run_key)
    if run is None:
        raise ValueError("market activity discovery run not found")
    candidates = load_market_activity_discovery_candidate_episodes_v0(run)
    members = load_market_activity_discovery_members_v0(
        cohort_key=run.cohort_key,
        acquisition_run_key=run.acquisition_run_key,
    )
    outcomes = load_opportunity_forward_outcomes(
        acquisition_run_key=run.acquisition_run_key,
    )

    candidate_by_key = {item.episode_key: item for item in candidates}
    member_by_key = {item.episode_key: item for item in members}
    if len(candidate_by_key) != len(candidates):
        raise RuntimeError("duplicate canonical candidate episode identity")
    if len(member_by_key) != len(members):
        raise RuntimeError("duplicate cohort member identity")

    unregistered = tuple(
        item.episode_key for item in candidates if item.episode_key not in member_by_key
    )
    dispositions: dict[str, int] = {}
    analyzable_keys: set[str] = set()
    missing_lineage: list[str] = []
    for member in members:
        dispositions[member.disposition] = dispositions.get(member.disposition, 0) + 1
        if member.primary_analysis_eligible:
            analyzable_keys.add(member.episode_key)
            if (
                member.disposition != "ANALYZABLE_T0"
                or not member.snapshot_key
                or not member.snapshot_payload_sha256
                or not member.snapshot_method_version
                or not member.activity_dynamics_method_version
            ):
                missing_lineage.append(member.episode_key)

    outcome_horizons_by_episode: dict[str, set[int]] = {}
    status_counts: dict[tuple[int, str], int] = {}
    for outcome in outcomes:
        outcome_horizons_by_episode.setdefault(outcome.episode_key, set()).add(
            int(outcome.horizon_seconds)
        )
        key = (int(outcome.horizon_seconds), str(outcome.status))
        status_counts[key] = status_counts.get(key, 0) + 1

    expected_horizons = set(int(item) for item in FORWARD_OUTCOME_HORIZONS_SECONDS)
    missing_forward: list[tuple[str, tuple[int, ...]]] = []
    for episode_key in sorted(analyzable_keys):
        observed = outcome_horizons_by_episode.get(episode_key, set())
        missing = tuple(sorted(expected_horizons - observed))
        if missing:
            missing_forward.append((episode_key, missing))

    unexpected_outcome_episode_keys = tuple(
        sorted(set(outcome_horizons_by_episode) - analyzable_keys)
    )
    outcome_status_counts = tuple(
        MarketActivityDiscoveryOutcomeStatusCountV0(
            horizon_seconds=horizon,
            status=status,
            count=count,
        )
        for (horizon, status), count in sorted(status_counts.items())
    )

    ready = not (
        unregistered
        or missing_lineage
        or missing_forward
        or unexpected_outcome_episode_keys
    )
    return MarketActivityDiscoveryAuditV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_AUDIT_VERSION,
        acquisition_run_key=run.acquisition_run_key,
        cohort_key=run.cohort_key,
        run_status=run.status,
        candidate_episode_count=len(candidates),
        cohort_denominator=len(members),
        disposition_counts=tuple(sorted(dispositions.items())),
        analyzable_t0_count=len(analyzable_keys),
        unregistered_candidate_episode_keys=unregistered,
        analyzable_missing_snapshot_lineage_episode_keys=tuple(sorted(missing_lineage)),
        analyzable_missing_forward_horizons=tuple(missing_forward),
        unexpected_outcome_episode_keys=unexpected_outcome_episode_keys,
        outcome_status_counts=outcome_status_counts,
        integrity_ready_for_close_or_analysis=ready,
        economic_edge_evaluated=False,
    )
