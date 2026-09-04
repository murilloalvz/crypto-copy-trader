from __future__ import annotations

import unittest

from src.jupiter_episode_execution import JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_decision_readiness import assess_opportunity_decision_readiness
from src.opportunity_provider_attempt_store import OpportunityProviderAttempt
from src.opportunity_token_hazard import (
    SOLANA_TRACKER_HAZARD_PROVIDER,
    SOLANA_TRACKER_HAZARD_PURPOSE,
)


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode-1",
        acquisition_run_key="run-1",
        token_mint="TokenMint111111111111111111111111111111111",
        first_trigger_key="trigger-1",
        first_trigger_kind="established_acceleration",
        first_trigger_direction="buy_pressure",
        first_trigger_chain_time=99,
        first_trigger_observed_at=100,
        episode_closes_at=160,
        decision_as_of=None,
    )


def _attempt(*, provider, purpose, status, completed_at=110, details=None):
    return OpportunityProviderAttempt(
        attempt_key=f"{provider}:{purpose}",
        acquisition_run_key="run-1",
        episode_key="episode-1",
        provider=provider,
        purpose=purpose,
        started_at=101,
        status=status,
        completed_at=completed_at,
        artifact_key=None,
        error_type=None,
        error_message=None,
        details=details or {},
    )


class OpportunityDecisionReadinessTests(unittest.TestCase):
    def test_insufficient_funds_is_external_blocker_not_strategy_failure(self):
        executable = _attempt(
            provider=JUPITER_ENTRY_PROVIDER,
            purpose=JUPITER_ENTRY_PURPOSE,
            status="UNAVAILABLE",
            details={"provider_error_message": "Insufficient funds"},
        )
        hazard = _attempt(
            provider=SOLANA_TRACKER_HAZARD_PROVIDER,
            purpose=SOLANA_TRACKER_HAZARD_PURPOSE,
            status="AVAILABLE",
        )
        result = assess_opportunity_decision_readiness(
            episode=_episode(), executable_attempt=executable, hazard_attempt=hazard
        )
        self.assertEqual(result.classification, "BLOCKED_BY_FUNDING")
        self.assertIn("funded_taker_required", result.blockers)
        self.assertIsNone(result.candidate_decision_as_of)

    def test_ready_uses_latest_causal_provider_completion_clock(self):
        executable = _attempt(
            provider=JUPITER_ENTRY_PROVIDER,
            purpose=JUPITER_ENTRY_PURPOSE,
            status="AVAILABLE",
            completed_at=108,
            details={"assembled_transaction_present": True},
        )
        hazard = _attempt(
            provider=SOLANA_TRACKER_HAZARD_PROVIDER,
            purpose=SOLANA_TRACKER_HAZARD_PURPOSE,
            status="AVAILABLE",
            completed_at=115,
        )
        result = assess_opportunity_decision_readiness(
            episode=_episode(), executable_attempt=executable, hazard_attempt=hazard
        )
        self.assertEqual(result.classification, "READY_TO_BUILD_DECISION_BUNDLE")
        self.assertEqual(result.candidate_decision_as_of, 115)
        self.assertEqual(result.blockers, ())

    def test_explicit_hazard_failure_does_not_silently_drop_episode(self):
        executable = _attempt(
            provider=JUPITER_ENTRY_PROVIDER,
            purpose=JUPITER_ENTRY_PURPOSE,
            status="AVAILABLE",
            completed_at=108,
            details={"assembled_transaction_present": True},
        )
        hazard = _attempt(
            provider=SOLANA_TRACKER_HAZARD_PROVIDER,
            purpose=SOLANA_TRACKER_HAZARD_PURPOSE,
            status="PROVIDER_ERROR",
            completed_at=116,
        )
        result = assess_opportunity_decision_readiness(
            episode=_episode(), executable_attempt=executable, hazard_attempt=hazard
        )
        self.assertEqual(result.classification, "READY_TO_BUILD_DECISION_BUNDLE")
        self.assertTrue(result.hazard_missingness_explicit)
        self.assertEqual(result.candidate_decision_as_of, 116)

    def test_available_without_assembled_transaction_fails_closed(self):
        executable = _attempt(
            provider=JUPITER_ENTRY_PROVIDER,
            purpose=JUPITER_ENTRY_PURPOSE,
            status="AVAILABLE",
            details={"assembled_transaction_present": False},
        )
        hazard = _attempt(
            provider=SOLANA_TRACKER_HAZARD_PROVIDER,
            purpose=SOLANA_TRACKER_HAZARD_PURPOSE,
            status="AVAILABLE",
        )
        result = assess_opportunity_decision_readiness(
            episode=_episode(), executable_attempt=executable, hazard_attempt=hazard
        )
        self.assertEqual(result.classification, "BLOCKED")
        self.assertIn("executable_available_without_assembled_transaction", result.blockers)


if __name__ == "__main__":
    unittest.main()
