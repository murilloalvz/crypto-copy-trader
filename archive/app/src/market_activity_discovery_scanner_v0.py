"""Run-scoped catch-up scanner for Market Activity Discovery V0.

The canonical episode store is already durable research evidence. This scanner uses that
store as restart recovery: while the discovery run remains OPEN, it enumerates every
canonical episode whose first-trigger local clock falls inside the frozen half-open run
window, skips episodes with an already-immutable cohort disposition, and processes only
previously unregistered first-trigger handoffs.

No provider call or economic analysis is performed.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.database import connection
from src.market_activity_discovery_cohort_v0 import (
    MarketActivityDiscoveryCohortMemberV0,
    load_market_activity_discovery_members_v0,
)
from src.market_activity_discovery_handoff_v0 import build_market_activity_discovery_handoff_v0
from src.market_activity_discovery_research_processor_v0 import (
    MarketActivityDiscoveryResearchProcessingV0,
    process_market_activity_discovery_handoff_v0,
)
from src.market_activity_discovery_run_v0 import (
    MarketActivityDiscoveryRunV0,
    load_market_activity_discovery_run_v0,
)
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    ensure_market_opportunity_episode_schema,
)


MARKET_ACTIVITY_DISCOVERY_SCANNER_VERSION = "market_activity_discovery_scanner_v0"


@dataclass(frozen=True)
class MarketActivityDiscoveryScanEntryV0:
    episode_key: str
    first_trigger_observed_at: int
    action: str
    disposition: str | None


@dataclass(frozen=True)
class MarketActivityDiscoveryScanV0:
    method_version: str
    acquisition_run_key: str
    cohort_key: str
    candidate_episode_count: int
    newly_processed_count: int
    already_registered_count: int
    entries: tuple[MarketActivityDiscoveryScanEntryV0, ...]
    provider_calls_performed: int
    economic_edge_evaluated: bool


def _row_to_episode(row) -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key=str(row["episode_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        token_mint=str(row["token_mint"]),
        first_trigger_key=str(row["first_trigger_key"]),
        first_trigger_kind=str(row["first_trigger_kind"]),
        first_trigger_direction=str(row["first_trigger_direction"]),
        first_trigger_chain_time=int(row["first_trigger_chain_time"]),
        first_trigger_observed_at=int(row["first_trigger_observed_at"]),
        episode_closes_at=int(row["episode_closes_at"]),
        decision_as_of=(
            int(row["decision_as_of"]) if row["decision_as_of"] is not None else None
        ),
    )


def load_market_activity_discovery_candidate_episodes_v0(
    run: MarketActivityDiscoveryRunV0,
) -> tuple[MarketOpportunityEpisode, ...]:
    """Load exact canonical episodes in the frozen first-trigger admission window."""

    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint, first_trigger_key,
                first_trigger_kind, first_trigger_direction, first_trigger_chain_time,
                first_trigger_observed_at, episode_closes_at, decision_as_of
            FROM market_opportunity_episodes
            WHERE acquisition_run_key=?
              AND first_trigger_observed_at>=?
              AND first_trigger_observed_at<?
            ORDER BY first_trigger_observed_at, id""",
            (
                run.acquisition_run_key,
                int(run.started_at),
                int(run.admission_closes_at),
            ),
        ).fetchall()
    return tuple(_row_to_episode(row) for row in rows)


def scan_open_market_activity_discovery_run_v0(
    *,
    acquisition_run_key: str,
) -> MarketActivityDiscoveryScanV0:
    """Idempotently catch up every unregistered canonical episode for one OPEN run."""

    run = load_market_activity_discovery_run_v0(acquisition_run_key=acquisition_run_key)
    if run is None:
        raise ValueError("market activity discovery run not found")
    if run.status != "OPEN":
        raise ValueError("catch-up scan requires an OPEN discovery run")

    candidates = load_market_activity_discovery_candidate_episodes_v0(run)
    entries: list[MarketActivityDiscoveryScanEntryV0] = []
    processed = 0
    skipped = 0

    for episode in candidates:
        existing = load_market_activity_discovery_members_v0(
            cohort_key=run.cohort_key,
            acquisition_run_key=run.acquisition_run_key,
            episode_key=episode.episode_key,
        )
        if existing:
            if len(existing) != 1:
                raise RuntimeError("cohort identity uniqueness violated during catch-up scan")
            member: MarketActivityDiscoveryCohortMemberV0 = existing[0]
            skipped += 1
            entries.append(
                MarketActivityDiscoveryScanEntryV0(
                    episode_key=episode.episode_key,
                    first_trigger_observed_at=episode.first_trigger_observed_at,
                    action="ALREADY_REGISTERED_IMMUTABLE",
                    disposition=member.disposition,
                )
            )
            continue

        handoff = build_market_activity_discovery_handoff_v0(
            episode=episode,
            trigger_key=episode.first_trigger_key,
        )
        if handoff is None:
            raise RuntimeError("canonical first trigger failed to produce discovery handoff")
        result: MarketActivityDiscoveryResearchProcessingV0 = (
            process_market_activity_discovery_handoff_v0(handoff)
        )
        if result.provider_calls_performed != 0:
            raise RuntimeError("catch-up processing unexpectedly performed provider calls")
        processed += 1
        entries.append(
            MarketActivityDiscoveryScanEntryV0(
                episode_key=episode.episode_key,
                first_trigger_observed_at=episode.first_trigger_observed_at,
                action="PROCESSED_ANALYZABLE_T0",
                disposition=result.admission.cohort_member.disposition,
            )
        )

    return MarketActivityDiscoveryScanV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_SCANNER_VERSION,
        acquisition_run_key=run.acquisition_run_key,
        cohort_key=run.cohort_key,
        candidate_episode_count=len(candidates),
        newly_processed_count=processed,
        already_registered_count=skipped,
        entries=tuple(entries),
        provider_calls_performed=0,
        economic_edge_evaluated=False,
    )
