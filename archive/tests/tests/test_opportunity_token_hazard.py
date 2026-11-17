from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_token_hazard import SolanaTrackerTokenHazardProbe


TOKEN = "TokenMint111111111111111111111111111111111"


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode-hazard-1",
        acquisition_run_key="run-hazard-1",
        token_mint=TOKEN,
        first_trigger_key="trigger-1",
        first_trigger_kind="established_acceleration",
        first_trigger_direction="buy_pressure",
        first_trigger_chain_time=99,
        first_trigger_observed_at=100,
        episode_closes_at=160,
        decision_as_of=None,
    )


def _payload(*, include_risk=True, mint=TOKEN):
    payload = {
        "token": {"mint": mint},
        "pools": [
            {
                "poolId": "pool-a",
                "security": {"freezeAuthority": None, "mintAuthority": None},
            }
        ],
    }
    if include_risk:
        payload["risk"] = {
            "score": 4.2,
            "rugged": False,
            "jupiterVerified": True,
            "top10": 21.5,
            "dev": {"percentage": 2.5},
            "snipers": {"totalPercentage": 3.0},
            "bundlers": {"totalPercentage": 1.25},
            "insiders": {"totalPercentage": 4.0},
            "risks": [
                {"name": "Top 10 Holders", "level": "warning", "score": 500},
            ],
        }
    return payload


class OpportunityTokenHazardTests(unittest.TestCase):
    def test_available_risk_is_persisted_and_replay_does_not_recall_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client._request.return_value = _payload()
                with patch(
                    "src.opportunity_token_hazard.SolanaTrackerClient",
                    return_value=client,
                ), patch("src.opportunity_token_hazard.time.time", return_value=110):
                    probe = SolanaTrackerTokenHazardProbe(api_key="key")
                    first = probe.capture(_episode())
                    second = probe.capture(_episode())

        self.assertEqual(first.attempt.status, "AVAILABLE")
        self.assertFalse(first.reused_attempt)
        self.assertTrue(second.reused_attempt)
        self.assertEqual(client._request.call_count, 1)
        self.assertEqual(first.evidence.observed_at, 110)
        self.assertAlmostEqual(first.evidence.risk_score, 4.2)
        self.assertFalse(first.evidence.rugged)
        self.assertFalse(first.evidence.freeze_authority_present)
        self.assertFalse(first.evidence.mint_authority_present)
        self.assertEqual(first.evidence.risk_factors[0][0], "Top 10 Holders")

    def test_missing_risk_object_is_explicit_unavailable_not_synthetic_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client._request.return_value = _payload(include_risk=False)
                with patch(
                    "src.opportunity_token_hazard.SolanaTrackerClient",
                    return_value=client,
                ), patch("src.opportunity_token_hazard.time.time", return_value=110):
                    result = SolanaTrackerTokenHazardProbe(api_key="key").capture(_episode())

        self.assertEqual(result.attempt.status, "UNAVAILABLE")
        self.assertIsNone(result.evidence.risk_score)
        self.assertIn("risk_object_missing", result.evidence.data_quality_flags)

    def test_missing_api_key_is_terminal_config_missing_without_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with patch("src.opportunity_token_hazard.SolanaTrackerClient") as client_cls, patch(
                    "src.opportunity_token_hazard.time.time", return_value=110
                ):
                    result = SolanaTrackerTokenHazardProbe(api_key="").capture(_episode())

        self.assertEqual(result.attempt.status, "CONFIG_MISSING")
        self.assertEqual(result.attempt.details["missing"], ["SOLANA_TRACKER_API_KEY"])
        client_cls.assert_not_called()

    def test_wrong_returned_mint_is_normalization_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client._request.return_value = _payload(mint="DifferentMint111111111111111111111111111111")
                with patch(
                    "src.opportunity_token_hazard.SolanaTrackerClient",
                    return_value=client,
                ), patch("src.opportunity_token_hazard.time.time", return_value=110):
                    result = SolanaTrackerTokenHazardProbe(api_key="key").capture(_episode())

        self.assertEqual(result.attempt.status, "NORMALIZATION_ERROR")
        self.assertIn("does not match", result.attempt.error_message)
        self.assertIsNone(result.evidence.risk_score)


if __name__ == "__main__":
    unittest.main()
