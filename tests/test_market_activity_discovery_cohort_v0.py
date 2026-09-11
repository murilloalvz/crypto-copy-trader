import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_cohort_v0 import (
    MARKET_ACTIVITY_DISCOVERY_COHORT_VERSION,
    MarketActivityDiscoveryCohortMemberV0,
    register_market_activity_discovery_member_v0,
)
from src.market_activity_dynamics_v0 import MARKET_ACTIVITY_DYNAMICS_VERSION
from src.market_episode_research_snapshot import MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION
from src.market_episode_research_snapshot_store import MarketEpisodeResearchSnapshotRecordV0
from src.market_opportunity_episode_store import MarketOpportunityEpisode


class MarketActivityDiscoveryCohortV0Tests(unittest.TestCase):
    def _episode(self, *, decision_as_of=110):
        return MarketOpportunityEpisode(
            episode_key="EP1",
            acquisition_run_key="RUN1",
            token_mint="MINT_A",
            first_trigger_key="TR1",
            first_trigger_kind="activity_acceleration",
            first_trigger_direction="upward_pressure",
            first_trigger_chain_time=120,
            first_trigger_observed_at=100,
            episode_closes_at=160,
            decision_as_of=decision_as_of,
        )

    def _snapshot(self, *, activity=True, tamper_hash=False):
        payload = {
            "method_version": MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION,
            "episode_key": "EP1",
            "acquisition_run_key": "RUN1",
            "token_mint": "MINT_A",
            "decision_as_of": 110,
            "activity_dynamics": (
                {
                    "method_version": MARKET_ACTIVITY_DYNAMICS_VERSION,
                    "token_mint": "MINT_A",
                    "as_of": 110,
                    "chain_as_of": 125,
                    "intervals": [],
                    "adjacent_rate_comparisons": [],
                    "participant_context": [],
                    "data_quality_flags": [],
                }
                if activity
                else None
            ),
        }
        payload_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if tamper_hash:
            digest = "0" * 64
        return MarketEpisodeResearchSnapshotRecordV0(
            snapshot_key="market-episode-t0:v0:RUN1:EP1:test",
            acquisition_run_key="RUN1",
            episode_key="EP1",
            token_mint="MINT_A",
            decision_as_of=110,
            snapshot_method_version=MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION,
            payload_json=payload_json,
            payload_sha256=digest,
        )

    def test_analyzable_member_persists_exact_snapshot_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cohort.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                snapshot = self._snapshot()
                result = register_market_activity_discovery_member_v0(
                    cohort_key="DISCOVERY-A",
                    episode=self._episode(),
                    considered_at=111,
                    snapshot_record=snapshot,
                )

        self.assertEqual(result.method_version, MARKET_ACTIVITY_DISCOVERY_COHORT_VERSION)
        self.assertEqual(result.disposition, "ANALYZABLE_T0")
        self.assertTrue(result.primary_analysis_eligible)
        self.assertEqual(result.snapshot_payload_sha256, snapshot.payload_sha256)
        self.assertEqual(result.activity_dynamics_method_version, MARKET_ACTIVITY_DYNAMICS_VERSION)
        self.assertEqual(result.reason_codes, ())

    def test_exact_replay_is_idempotent_and_keeps_first_considered_at(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = register_market_activity_discovery_member_v0(
                    cohort_key="DISCOVERY-A",
                    episode=self._episode(),
                    considered_at=111,
                    snapshot_record=self._snapshot(),
                )
                second = register_market_activity_discovery_member_v0(
                    cohort_key="DISCOVERY-A",
                    episode=self._episode(),
                    considered_at=999,
                    snapshot_record=self._snapshot(),
                )

        self.assertEqual(first, second)
        self.assertEqual(second.first_considered_at, 111)

    def test_missing_snapshot_stays_in_denominator_and_cannot_be_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = register_market_activity_discovery_member_v0(
                    cohort_key="DISCOVERY-A",
                    episode=self._episode(),
                    considered_at=111,
                    snapshot_record=None,
                )
                with self.assertRaises(ValueError):
                    register_market_activity_discovery_member_v0(
                        cohort_key="DISCOVERY-A",
                        episode=self._episode(),
                        considered_at=120,
                        snapshot_record=self._snapshot(),
                    )

        self.assertEqual(first.disposition, "T0_SNAPSHOT_MISSING")
        self.assertFalse(first.primary_analysis_eligible)
        self.assertIn("immutable_t0_snapshot_missing_at_first_registration", first.reason_codes)

    def test_missing_activity_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-activity.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                result = register_market_activity_discovery_member_v0(
                    cohort_key="DISCOVERY-A",
                    episode=self._episode(),
                    considered_at=111,
                    snapshot_record=self._snapshot(activity=False),
                )

        self.assertEqual(result.disposition, "ACTIVITY_DYNAMICS_MISSING")
        self.assertFalse(result.primary_analysis_eligible)
        self.assertIsNone(result.activity_dynamics_method_version)

    def test_unfrozen_episode_is_explicit_not_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unfrozen.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                result = register_market_activity_discovery_member_v0(
                    cohort_key="DISCOVERY-A",
                    episode=self._episode(decision_as_of=None),
                    considered_at=101,
                    snapshot_record=None,
                )

        self.assertEqual(result.disposition, "T0_NOT_FROZEN")
        self.assertFalse(result.primary_analysis_eligible)
        self.assertIsNone(result.decision_as_of)

    def test_tampered_snapshot_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    register_market_activity_discovery_member_v0(
                        cohort_key="DISCOVERY-A",
                        episode=self._episode(),
                        considered_at=111,
                        snapshot_record=self._snapshot(tamper_hash=True),
                    )

    def test_member_schema_contains_no_outcome_or_score_fields(self):
        forbidden = {
            "outcome",
            "return_pct",
            "mfe",
            "mae",
            "score",
            "confidence",
            "recommendation",
            "take",
            "skip",
            "social",
            "launch",
        }
        self.assertTrue(forbidden.isdisjoint(MarketActivityDiscoveryCohortMemberV0.__dataclass_fields__))


if __name__ == "__main__":
    unittest.main()
