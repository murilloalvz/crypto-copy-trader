from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_forward_due import load_due_opportunity_forward_outcomes
from src.opportunity_forward_outcome_store import (
    complete_opportunity_forward_outcome,
    schedule_opportunity_forward_outcomes,
)


def _episode(*, run_key: str = "run", episode_key: str = "episode") -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key=episode_key,
        acquisition_run_key=run_key,
        token_mint="TokenMint111111111111111111111111111111111",
        first_trigger_key=f"trigger-{episode_key}",
        first_trigger_kind="activity_acceleration",
        first_trigger_direction="upward_pressure",
        first_trigger_chain_time=990,
        first_trigger_observed_at=991,
        episode_closes_at=1051,
        decision_as_of=1000,
    )


class OpportunityForwardDueTests(unittest.TestCase):
    def test_returns_only_due_pending_rows_in_target_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "due.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                scheduled = schedule_opportunity_forward_outcomes(_episode())
                complete_opportunity_forward_outcome(
                    outcome_key=scheduled[0].outcome_key,
                    status="UNAVAILABLE",
                    observed_at=1300,
                    error_type="none",
                )
                due = load_due_opportunity_forward_outcomes(as_of=2000)

        self.assertEqual([item.horizon_seconds for item in due], [900])
        self.assertTrue(all(item.status == "PENDING" for item in due))

    def test_can_scope_to_one_run_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "due.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                schedule_opportunity_forward_outcomes(_episode(run_key="run-a", episode_key="a"))
                schedule_opportunity_forward_outcomes(_episode(run_key="run-b", episode_key="b"))
                due = load_due_opportunity_forward_outcomes(
                    as_of=5000,
                    acquisition_run_key="run-b",
                    limit=2,
                )

        self.assertEqual(len(due), 2)
        self.assertTrue(all(item.acquisition_run_key == "run-b" for item in due))
        self.assertEqual([item.horizon_seconds for item in due], [300, 900])


if __name__ == "__main__":
    unittest.main()
