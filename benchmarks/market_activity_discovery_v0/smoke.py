from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile

from src import database
from src.market_activity_discovery_admission_v0 import (
    prepare_and_register_market_activity_episode_v0,
    register_considered_market_activity_episode_v0,
)
from src.market_activity_discovery_cohort_v0 import load_market_activity_discovery_members_v0
from src.market_activity_discovery_run_v0 import (
    MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
    close_market_activity_discovery_run_v0,
    create_market_activity_discovery_run_v0,
    load_market_activity_discovery_run_v0,
)
from src.market_activity_dynamics_v0 import build_market_activity_dynamics_v0
from src.market_intelligence_baseline import build_market_intelligence_baseline_v0
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_protocol_facts import build_market_protocol_facts_v0
from src.opportunity_forward_outcome_store import load_opportunity_forward_outcomes
from src.opportunity_snapshot_core import build_opportunity_snapshot_core_v1
from src.pump_creation_mode_facts import build_pump_creation_mode_facts_v0


SMOKE_VERSION = "market_activity_discovery_offline_smoke_v0_1_first_trigger_t0"
PASS_CLASSIFICATION = "PASS_MARKET_ACTIVITY_DISCOVERY_V0_OFFLINE_SMOKE"


def _t0_inputs(*, token_mint: str, as_of: int, chain_as_of: int):
    protocol = build_market_protocol_facts_v0(token_mint=token_mint, as_of=as_of)
    core = build_opportunity_snapshot_core_v1(
        token_mint=token_mint,
        as_of=as_of,
        chain_as_of=chain_as_of,
        flow_observations=(),
        quotes=(),
        flow_windows_seconds=(10, 30, 60, 300),
    )
    baseline = build_market_intelligence_baseline_v0(protocol=protocol, snapshot=core)
    mode = build_pump_creation_mode_facts_v0(token_mint=token_mint, as_of=as_of)
    activity = build_market_activity_dynamics_v0(core)
    return baseline, mode, activity


def run_offline_smoke() -> dict[str, object]:
    original_settings = database.settings
    with tempfile.TemporaryDirectory() as directory:
        database.settings = SimpleNamespace(database_path=Path(directory) / "market-activity-smoke.db")
        try:
            started_at = 1_000
            run = create_market_activity_discovery_run_v0(
                acquisition_run_key="SMOKE_RUN_V0",
                cohort_key="SMOKE_COHORT_V0",
                started_at=started_at,
            )
            if run.admission_closes_at != started_at + MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS:
                raise AssertionError("smoke run did not freeze the preregistered six-hour window")

            analyzable_episode = assign_market_opportunity_trigger(
                acquisition_run_key=run.acquisition_run_key,
                trigger_key="smoke-trigger-analyzable",
                token_mint="SMOKE_MINT_A",
                trigger_kind="activity_acceleration",
                direction="upward_pressure",
                chain_time=1_100,
                observed_at=1_010,
                method_version="market_opportunity_radar_v1",
                venue="pump",
            )
            baseline, mode, activity = _t0_inputs(
                token_mint="SMOKE_MINT_A",
                as_of=analyzable_episode.first_trigger_observed_at,
                chain_as_of=analyzable_episode.first_trigger_chain_time,
            )
            first = prepare_and_register_market_activity_episode_v0(
                acquisition_run_key=run.acquisition_run_key,
                episode_key=analyzable_episode.episode_key,
                considered_at=1_020,
                decision_as_of=analyzable_episode.first_trigger_observed_at,
                market_intelligence=baseline,
                pump_creation_mode=mode,
                activity_dynamics=activity,
            )
            replay = prepare_and_register_market_activity_episode_v0(
                acquisition_run_key=run.acquisition_run_key,
                episode_key=analyzable_episode.episode_key,
                considered_at=1_020,
                decision_as_of=analyzable_episode.first_trigger_observed_at,
                market_intelligence=baseline,
                pump_creation_mode=mode,
                activity_dynamics=activity,
            )
            if first.cohort_member != replay.cohort_member:
                raise AssertionError("exact admission replay was not idempotent")
            if first.preparation is None or replay.preparation is None:
                raise AssertionError("successful smoke admission lost T0 preparation")
            if first.preparation.snapshot_record != replay.preparation.snapshot_record:
                raise AssertionError("exact T0 replay changed immutable snapshot lineage")
            if first.preparation.snapshot.decision_as_of != analyzable_episode.first_trigger_observed_at:
                raise AssertionError("offline smoke T0 drifted past first trigger observation")
            if first.preparation.snapshot.market_intelligence.chain_as_of != analyzable_episode.first_trigger_chain_time:
                raise AssertionError("offline smoke chain anchor drifted from first trigger")

            missing_episode = assign_market_opportunity_trigger(
                acquisition_run_key=run.acquisition_run_key,
                trigger_key="smoke-trigger-missing",
                token_mint="SMOKE_MINT_B",
                trigger_kind="activity_acceleration",
                direction="upward_pressure",
                chain_time=1_120,
                observed_at=1_030,
                method_version="market_opportunity_radar_v1",
                venue="pump",
            )
            missing = register_considered_market_activity_episode_v0(
                acquisition_run_key=run.acquisition_run_key,
                episode_key=missing_episode.episode_key,
                considered_at=1_040,
            )
            if missing.cohort_member.disposition != "T0_NOT_FROZEN":
                raise AssertionError("missing T0 episode did not remain in denominator")

            late_episode = assign_market_opportunity_trigger(
                acquisition_run_key=run.acquisition_run_key,
                trigger_key="smoke-trigger-late",
                token_mint="SMOKE_MINT_C",
                trigger_kind="activity_acceleration",
                direction="upward_pressure",
                chain_time=1_130,
                observed_at=1_050,
                method_version="market_opportunity_radar_v1",
                venue="pump",
            )
            late_rejected = False
            try:
                register_considered_market_activity_episode_v0(
                    acquisition_run_key=run.acquisition_run_key,
                    episode_key=late_episode.episode_key,
                    considered_at=run.admission_closes_at,
                )
            except ValueError:
                late_rejected = True
            if not late_rejected:
                raise AssertionError("half-open admission boundary accepted an episode at close")

            closed = close_market_activity_discovery_run_v0(
                acquisition_run_key=run.acquisition_run_key,
                observed_at=run.admission_closes_at,
            )
            restarted = load_market_activity_discovery_run_v0(
                acquisition_run_key=run.acquisition_run_key
            )
            if closed.status != "CLOSED" or restarted != closed:
                raise AssertionError("closed run did not survive restart/load exactly")

            members = load_market_activity_discovery_members_v0(
                cohort_key=run.cohort_key,
                acquisition_run_key=run.acquisition_run_key,
            )
            dispositions: dict[str, int] = {}
            for member in members:
                dispositions[member.disposition] = dispositions.get(member.disposition, 0) + 1
            if dispositions != {"ANALYZABLE_T0": 1, "T0_NOT_FROZEN": 1}:
                raise AssertionError(f"unexpected smoke denominator dispositions: {dispositions}")

            outcomes = load_opportunity_forward_outcomes(
                acquisition_run_key=run.acquisition_run_key,
                episode_key=analyzable_episode.episode_key,
            )
            if [item.horizon_seconds for item in outcomes] != [300, 900, 3600]:
                raise AssertionError("smoke forward horizons differ from frozen defaults")
            if [item.target_at for item in outcomes] != [1_310, 1_910, 4_610]:
                raise AssertionError("smoke forward targets are not anchored to first-trigger T0")
            if any(item.status != "PENDING" for item in outcomes):
                raise AssertionError("offline smoke must not fabricate completed outcomes")

            return {
                "smoke_version": SMOKE_VERSION,
                "classification": PASS_CLASSIFICATION,
                "valid_smoke": True,
                "run_status": closed.status,
                "started_at": run.started_at,
                "admission_closes_at": run.admission_closes_at,
                "duration_seconds": run.admission_closes_at - run.started_at,
                "cohort_denominator": len(members),
                "dispositions": dispositions,
                "analyzable_decision_as_of": first.preparation.snapshot.decision_as_of,
                "analyzable_chain_as_of": first.preparation.snapshot.market_intelligence.chain_as_of,
                "analyzable_forward_outcomes": len(outcomes),
                "forward_horizons_seconds": [item.horizon_seconds for item in outcomes],
                "forward_statuses": [item.status for item in outcomes],
                "late_boundary_rejected": late_rejected,
                "exact_replay_idempotent": True,
                "economic_edge_evaluated": False,
                "provider_calls_performed": 0,
            }
        finally:
            database.settings = original_settings


def main() -> int:
    result = run_offline_smoke()
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result.get("valid_smoke") else 1


if __name__ == "__main__":
    raise SystemExit(main())
