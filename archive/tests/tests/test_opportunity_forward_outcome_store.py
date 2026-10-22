from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_forward_outcome_store import (
    complete_opportunity_forward_outcome,
    schedule_opportunity_forward_outcomes,
)


def _episode(*, decision_as_of=1000) -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode-forward-1",
        acquisition_run_key="run-forward-1",
        token_mint="TokenMint111111111111111111111111111111111",
        first_trigger_key="trigger-1",
        first_trigger_kind="established_acceleration",
        first_trigger_direction="buy_pressure",
        first_trigger_chain_time=990,
        first_trigger_observed_at=991,
        episode_closes_at=1051,
        decision_as_of=decision_as_of,
    )


class OpportunityForwardOutcomeStoreTests(unittest.TestCase):
    def test_requires_frozen_decision_before_scheduling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    schedule_opportunity_forward_outcomes(_episode(decision_as_of=None))

    def test_default_targets_are_exactly_5_15_60_minutes_after_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = schedule_opportunity_forward_outcomes(_episode())
                replay = schedule_opportunity_forward_outcomes(_episode())

        self.assertEqual([item.horizon_seconds for item in first], [300, 900, 3600])
        self.assertEqual([item.target_at for item in first], [1300, 1900, 4600])
        self.assertEqual(first, replay)
        self.assertTrue(all(item.status == "PENDING" for item in first))

    def test_available_requires_quote_and_cannot_precede_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                outcome = schedule_opportunity_forward_outcomes(_episode())[0]
                with self.assertRaises(ValueError):
                    complete_opportunity_forward_outcome(
                        outcome_key=outcome.outcome_key,
                        status="AVAILABLE",
                        observed_at=outcome.target_at,
                    )
                with self.assertRaises(ValueError):
                    complete_opportunity_forward_outcome(
                        outcome_key=outcome.outcome_key,
                        status="AVAILABLE",
                        observed_at=outcome.target_at - 1,
                        quote_key="quote-1",
                    )
                completed = complete_opportunity_forward_outcome(
                    outcome_key=outcome.outcome_key,
                    status="AVAILABLE",
                    observed_at=outcome.target_at,
                    quote_key="quote-1",
                )

        self.assertEqual(completed.status, "AVAILABLE")
        self.assertEqual(completed.quote_key, "quote-1")

    def test_terminal_result_is_immutable_and_missing_stays_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                outcome = schedule_opportunity_forward_outcomes(_episode())[1]
                completed = complete_opportunity_forward_outcome(
                    outcome_key=outcome.outcome_key,
                    status="UNAVAILABLE",
                    observed_at=outcome.target_at + 2,
                    error_type="QuoteUnavailable",
                    error_message="no executable route at target",
                )
                with self.assertRaises(ValueError):
                    complete_opportunity_forward_outcome(
                        outcome_key=outcome.outcome_key,
                        status="AVAILABLE",
                        observed_at=outcome.target_at + 2,
                        quote_key="later-quote",
                    )

        self.assertEqual(completed.status, "UNAVAILABLE")
        self.assertIsNone(completed.quote_key)
        self.assertEqual(completed.observed_at, outcome.target_at + 2)


if __name__ == "__main__":
    unittest.main()
