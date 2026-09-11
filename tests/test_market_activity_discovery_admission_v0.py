import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_admission_v0 import (
    prepare_and_register_market_activity_episode_v0,
    register_considered_market_activity_episode_v0,
)
from src.market_activity_discovery_run_v0 import create_market_activity_discovery_run_v0
from src.market_activity_dynamics_v0 import build_market_activity_dynamics_v0
from src.market_first_prospective_coordinator import prepare_market_first_prospective_episode_v0
from src.market_intelligence_baseline import build_market_intelligence_baseline_v0
from src.market_opportunity_episode_store import (
    assign_market_opportunity_trigger,
    get_market_opportunity_episode,
)
from src.market_protocol_facts import build_market_protocol_facts_v0
from src.opportunity_snapshot_core import build_opportunity_snapshot_core_v1
from src.pump_creation_mode_facts import build_pump_creation_mode_facts_v0


class MarketActivityDiscoveryAdmissionV0Tests(unittest.TestCase):
    def _episode(self, *, run_key="RUN1"):
        return assign_market_opportunity_trigger(
            acquisition_run_key=run_key,
            trigger_key="trigger-1",
            token_mint="MINT_A",
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=120,
            observed_at=100,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def _t0_inputs(self, *, as_of=100, chain_as_of=120):
        protocol = build_market_protocol_facts_v0(token_mint="MINT_A", as_of=as_of)
        core = build_opportunity_snapshot_core_v1(
            token_mint="MINT_A",
            as_of=as_of,
            chain_as_of=chain_as_of,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(10, 30, 60, 300),
        )
        baseline = build_market_intelligence_baseline_v0(protocol=protocol, snapshot=core)
        mode = build_pump_creation_mode_facts_v0(token_mint="MINT_A", as_of=as_of)
        activity = build_market_activity_dynamics_v0(core)
        return baseline, mode, activity

    def test_success_path_freezes_exact_first_trigger_t0_and_schedules_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "success.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                baseline, mode, activity = self._t0_inputs()
                result = prepare_and_register_market_activity_episode_v0(
                    acquisition_run_key="RUN1",
                    episode_key=episode.episode_key,
                    considered_at=110,
                    decision_as_of=episode.first_trigger_observed_at,
                    market_intelligence=baseline,
                    pump_creation_mode=mode,
                    activity_dynamics=activity,
                )

        self.assertEqual(result.cohort_member.disposition, "ANALYZABLE_T0")
        self.assertTrue(result.cohort_member.primary_analysis_eligible)
        self.assertIsNotNone(result.preparation)
        self.assertEqual(result.preparation.snapshot.decision_as_of, 100)
        self.assertEqual(result.preparation.snapshot.market_intelligence.chain_as_of, 120)
        self.assertEqual(
            result.cohort_member.snapshot_payload_sha256,
            result.preparation.snapshot_record.payload_sha256,
        )
        self.assertEqual(
            [item.horizon_seconds for item in result.preparation.forward_outcomes],
            [300, 900, 3600],
        )
        self.assertEqual(
            [item.target_at for item in result.preparation.forward_outcomes],
            [400, 1000, 3700],
        )

    def test_decision_delay_after_first_trigger_is_rejected_before_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late-t0.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                baseline, mode, activity = self._t0_inputs(as_of=110)
                with self.assertRaises(ValueError):
                    prepare_and_register_market_activity_episode_v0(
                        acquisition_run_key="RUN1",
                        episode_key=episode.episode_key,
                        considered_at=110,
                        decision_as_of=110,
                        market_intelligence=baseline,
                        pump_creation_mode=mode,
                        activity_dynamics=activity,
                    )
                loaded = get_market_opportunity_episode(episode.episode_key)
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.decision_as_of)

    def test_mismatched_chain_anchor_is_rejected_before_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-chain-anchor.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                baseline, mode, activity = self._t0_inputs(chain_as_of=119)
                with self.assertRaises(ValueError):
                    prepare_and_register_market_activity_episode_v0(
                        acquisition_run_key="RUN1",
                        episode_key=episode.episode_key,
                        considered_at=110,
                        decision_as_of=100,
                        market_intelligence=baseline,
                        pump_creation_mode=mode,
                        activity_dynamics=activity,
                    )
                loaded = get_market_opportunity_episode(episode.episode_key)
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.decision_as_of)

    def test_exact_success_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                baseline, mode, activity = self._t0_inputs()
                kwargs = dict(
                    acquisition_run_key="RUN1",
                    episode_key=episode.episode_key,
                    considered_at=110,
                    decision_as_of=100,
                    market_intelligence=baseline,
                    pump_creation_mode=mode,
                    activity_dynamics=activity,
                )
                first = prepare_and_register_market_activity_episode_v0(**kwargs)
                second = prepare_and_register_market_activity_episode_v0(**kwargs)

        self.assertEqual(first.cohort_member, second.cohort_member)
        self.assertEqual(first.preparation.snapshot_record, second.preparation.snapshot_record)
        self.assertEqual(first.preparation.forward_outcomes, second.preparation.forward_outcomes)

    def test_outside_window_rejects_before_episode_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                baseline, mode, activity = self._t0_inputs()
                with self.assertRaises(ValueError):
                    prepare_and_register_market_activity_episode_v0(
                        acquisition_run_key="RUN1",
                        episode_key=episode.episode_key,
                        considered_at=run.admission_closes_at,
                        decision_as_of=100,
                        market_intelligence=baseline,
                        pump_creation_mode=mode,
                        activity_dynamics=activity,
                    )
                loaded = get_market_opportunity_episode(episode.episode_key)

        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.decision_as_of)

    def test_missing_t0_path_preserves_episode_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                result = register_considered_market_activity_episode_v0(
                    acquisition_run_key="RUN1",
                    episode_key=episode.episode_key,
                    considered_at=110,
                )

        self.assertEqual(result.cohort_member.disposition, "T0_NOT_FROZEN")
        self.assertFalse(result.cohort_member.primary_analysis_eligible)
        self.assertIsNone(result.preparation)

    def test_failed_t0_validation_can_be_preserved_without_silent_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode()
                baseline, mode, _activity = self._t0_inputs(as_of=100)
                _bad_baseline, _bad_mode, bad_activity = self._t0_inputs(as_of=99)
                with self.assertRaises(ValueError):
                    prepare_and_register_market_activity_episode_v0(
                        acquisition_run_key="RUN1",
                        episode_key=episode.episode_key,
                        considered_at=110,
                        decision_as_of=100,
                        market_intelligence=baseline,
                        pump_creation_mode=mode,
                        activity_dynamics=bad_activity,
                    )
                missing = register_considered_market_activity_episode_v0(
                    acquisition_run_key="RUN1",
                    episode_key=episode.episode_key,
                    considered_at=110,
                )
                good_activity = self._t0_inputs(as_of=100)[2]
                prepared = prepare_market_first_prospective_episode_v0(
                    episode_key=episode.episode_key,
                    decision_as_of=100,
                    market_intelligence=baseline,
                    pump_creation_mode=mode,
                    activity_dynamics=good_activity,
                )
                with self.assertRaises(ValueError):
                    register_considered_market_activity_episode_v0(
                        acquisition_run_key="RUN1",
                        episode_key=episode.episode_key,
                        considered_at=110,
                        snapshot_record=prepared.snapshot_record,
                    )

        self.assertEqual(missing.cohort_member.disposition, "T0_NOT_FROZEN")

    def test_run_key_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mismatch.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=90
                )
                episode = self._episode(run_key="RUN2")
                with self.assertRaises(ValueError):
                    register_considered_market_activity_episode_v0(
                        acquisition_run_key="RUN1",
                        episode_key=episode.episode_key,
                        considered_at=110,
                    )


if __name__ == "__main__":
    unittest.main()
