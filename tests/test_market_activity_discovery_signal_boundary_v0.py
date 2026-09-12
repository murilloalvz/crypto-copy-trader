from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_signal_boundary_v0 import (
    seal_market_activity_discovery_signal_boundary_v0,
)
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
    freeze_market_opportunity_decision_as_of,
)


class MarketActivityDiscoverySignalBoundaryV0Tests(unittest.TestCase):
    @staticmethod
    def _persist_episode() -> MarketOpportunityEpisode:
        return assign_market_opportunity_trigger(
            acquisition_run_key="RUN-SIGNAL-BOUNDARY",
            trigger_key="TRIGGER-1",
            token_mint="TokenMint111111111111111111111111111111111",
            trigger_kind="established_acceleration",
            direction="buy_pressure",
            chain_time=990,
            observed_at=1000,
            method_version="test-trigger-v1",
            venue="pump",
        )

    def test_boundary_freezes_first_trigger_t0_and_schedules_exact_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signal-boundary.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._persist_episode()
                self.assertIsNone(episode.decision_as_of)
                boundary = seal_market_activity_discovery_signal_boundary_v0(episode)

        self.assertEqual(boundary.episode.decision_as_of, 1000)
        self.assertEqual(
            [(item.horizon_seconds, item.target_at, item.status) for item in boundary.forward_outcomes],
            [(300, 1300, "PENDING"), (900, 1900, "PENDING"), (3600, 4600, "PENDING")],
        )

    def test_replay_is_idempotent_and_repairs_freeze_without_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signal-boundary.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._persist_episode()
                frozen_only = freeze_market_opportunity_decision_as_of(
                    episode.episode_key,
                    decision_as_of=episode.first_trigger_observed_at,
                )
                first = seal_market_activity_discovery_signal_boundary_v0(frozen_only)
                replay = seal_market_activity_discovery_signal_boundary_v0(first.episode)

        self.assertEqual(first, replay)
        self.assertEqual(len(first.forward_outcomes), 3)

    def test_divergent_pre_frozen_clock_fails_closed(self) -> None:
        divergent = MarketOpportunityEpisode(
            episode_key="EP-DIVERGENT",
            acquisition_run_key="RUN-DIVERGENT",
            token_mint="TokenMint111111111111111111111111111111111",
            first_trigger_key="TRIGGER-DIVERGENT",
            first_trigger_kind="established_acceleration",
            first_trigger_direction="buy_pressure",
            first_trigger_chain_time=990,
            first_trigger_observed_at=1000,
            episode_closes_at=1060,
            decision_as_of=1001,
        )
        with self.assertRaisesRegex(ValueError, "conflicts with canonical"):
            seal_market_activity_discovery_signal_boundary_v0(divergent)


if __name__ == "__main__":
    unittest.main()
