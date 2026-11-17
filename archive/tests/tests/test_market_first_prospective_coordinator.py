import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_dynamics_v0 import build_market_activity_dynamics_v0
from src.market_episode_research_snapshot import MarketRegimeResearchFactsV0
from src.market_episode_research_snapshot_store import (
    load_market_episode_research_snapshot_record_v0,
)
from src.market_first_prospective_coordinator import (
    MARKET_FIRST_PROSPECTIVE_COORDINATOR_VERSION,
    prepare_market_first_prospective_episode_v0,
)
from src.market_intelligence_baseline import build_market_intelligence_baseline_v0
from src.market_opportunity_episode_store import (
    assign_market_opportunity_trigger,
    get_market_opportunity_episode,
)
from src.market_protocol_facts import build_market_protocol_facts_v0
from src.opportunity_forward_outcome_store import load_opportunity_forward_outcomes
from src.opportunity_snapshot_core import build_opportunity_snapshot_core_v1
from src.pump_creation_mode_facts import build_pump_creation_mode_facts_v0


class MarketFirstProspectiveCoordinatorV0Tests(unittest.TestCase):
    def _episode(self):
        return assign_market_opportunity_trigger(
            acquisition_run_key="run-a",
            trigger_key="trigger-1",
            token_mint="MINT_A",
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=120,
            observed_at=100,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def _baseline(self, *, as_of=110, token_mint="MINT_A", chain_as_of=None):
        protocol = build_market_protocol_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
        )
        core = build_opportunity_snapshot_core_v1(
            token_mint=token_mint,
            as_of=as_of,
            chain_as_of=chain_as_of,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(30,),
        )
        return build_market_intelligence_baseline_v0(protocol=protocol, snapshot=core)

    def _activity(self, *, as_of=110, token_mint="MINT_A", chain_as_of=None):
        core = build_opportunity_snapshot_core_v1(
            token_mint=token_mint,
            as_of=as_of,
            chain_as_of=chain_as_of,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(10, 30, 60, 300),
        )
        return build_market_activity_dynamics_v0(core)

    def _mode(self, *, as_of=110, token_mint="MINT_A"):
        return build_pump_creation_mode_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
        )

    def _regime(self, *, latest_chain_time=130):
        return MarketRegimeResearchFactsV0(
            method_version="covered_page_hinkley_v0",
            detector="river.PageHinkley",
            metric="event_count",
            detection_count=1,
            latest_detection_chain_time=latest_chain_time,
            observed_bins_consumed=10,
            missing_bins_skipped=0,
            detector_resets_due_to_missing=0,
            contiguous_segments=1,
        )

    def test_freezes_persists_t0_then_schedules_pending_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prospective.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                result = prepare_market_first_prospective_episode_v0(
                    episode_key=episode.episode_key,
                    decision_as_of=110,
                    market_intelligence=self._baseline(),
                    pump_creation_mode=self._mode(),
                    activity_dynamics=self._activity(),
                    regime=self._regime(),
                    horizons_seconds=(15, 30),
                )
                stored = load_market_episode_research_snapshot_record_v0(
                    acquisition_run_key="run-a",
                    episode_key=episode.episode_key,
                    snapshot_method_version=result.snapshot.method_version,
                )

        self.assertEqual(result.method_version, MARKET_FIRST_PROSPECTIVE_COORDINATOR_VERSION)
        self.assertEqual(result.episode.decision_as_of, 110)
        self.assertEqual(result.snapshot.decision_as_of, 110)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.payload_sha256, result.snapshot_record.payload_sha256)
        payload = stored.payload()
        self.assertEqual(payload["episode_key"], episode.episode_key)
        self.assertEqual(
            payload["activity_dynamics"]["method_version"],
            result.snapshot.activity_dynamics.method_version,
        )
        self.assertEqual([item.horizon_seconds for item in result.forward_outcomes], [15, 30])
        self.assertEqual([item.target_at for item in result.forward_outcomes], [125, 140])
        self.assertTrue(all(item.status == "PENDING" for item in result.forward_outcomes))

    def test_exact_replay_with_activity_dynamics_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                first = prepare_market_first_prospective_episode_v0(
                    episode_key=episode.episode_key,
                    decision_as_of=110,
                    market_intelligence=self._baseline(),
                    pump_creation_mode=self._mode(),
                    activity_dynamics=self._activity(),
                    horizons_seconds=(15, 30),
                )
                second = prepare_market_first_prospective_episode_v0(
                    episode_key=episode.episode_key,
                    decision_as_of=110,
                    market_intelligence=self._baseline(),
                    pump_creation_mode=self._mode(),
                    activity_dynamics=self._activity(),
                    horizons_seconds=(15, 30),
                )

        self.assertEqual(first.snapshot_record, second.snapshot_record)
        self.assertEqual(first.forward_outcomes, second.forward_outcomes)

    def test_divergent_snapshot_replay_fails_before_new_horizon_is_scheduled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                prepare_market_first_prospective_episode_v0(
                    episode_key=episode.episode_key,
                    decision_as_of=110,
                    market_intelligence=self._baseline(),
                    pump_creation_mode=self._mode(),
                    horizons_seconds=(15,),
                )
                with self.assertRaises(ValueError):
                    prepare_market_first_prospective_episode_v0(
                        episode_key=episode.episode_key,
                        decision_as_of=110,
                        market_intelligence=self._baseline(),
                        pump_creation_mode=self._mode(),
                        activity_dynamics=self._activity(),
                        regime=self._regime(),
                        horizons_seconds=(15, 30),
                    )
                outcomes = load_opportunity_forward_outcomes(
                    acquisition_run_key="run-a",
                    episode_key=episode.episode_key,
                )

        self.assertEqual([item.horizon_seconds for item in outcomes], [15])

    def test_mismatched_local_t0_input_does_not_freeze_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-input.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                with self.assertRaises(ValueError):
                    prepare_market_first_prospective_episode_v0(
                        episode_key=episode.episode_key,
                        decision_as_of=110,
                        market_intelligence=self._baseline(as_of=109),
                        pump_creation_mode=self._mode(),
                        horizons_seconds=(15,),
                    )
                loaded = get_market_opportunity_episode(episode.episode_key)

        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.decision_as_of)

    def test_mismatched_activity_t0_does_not_freeze_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-activity.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                with self.assertRaises(ValueError):
                    prepare_market_first_prospective_episode_v0(
                        episode_key=episode.episode_key,
                        decision_as_of=110,
                        market_intelligence=self._baseline(),
                        pump_creation_mode=self._mode(),
                        activity_dynamics=self._activity(as_of=109),
                        horizons_seconds=(15,),
                    )
                loaded = get_market_opportunity_episode(episode.episode_key)

        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.decision_as_of)

    def test_invalid_horizons_do_not_freeze_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-horizon.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                with self.assertRaises(ValueError):
                    prepare_market_first_prospective_episode_v0(
                        episode_key=episode.episode_key,
                        decision_as_of=110,
                        market_intelligence=self._baseline(),
                        pump_creation_mode=self._mode(),
                        horizons_seconds=(15, 15),
                    )
                loaded = get_market_opportunity_episode(episode.episode_key)

        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.decision_as_of)

    def test_regime_chain_clock_ahead_of_local_t0_remains_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dual-clock.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                result = prepare_market_first_prospective_episode_v0(
                    episode_key=episode.episode_key,
                    decision_as_of=110,
                    market_intelligence=self._baseline(),
                    pump_creation_mode=self._mode(),
                    activity_dynamics=self._activity(),
                    regime=self._regime(latest_chain_time=999),
                    horizons_seconds=(15,),
                )

        self.assertEqual(result.snapshot.regime.latest_detection_chain_time, 999)
        self.assertEqual(result.snapshot.decision_as_of, 110)


if __name__ == "__main__":
    unittest.main()
