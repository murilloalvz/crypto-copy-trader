from __future__ import annotations

import unittest
from unittest.mock import patch

import src.route_research_wallet_market_history_v0 as history


class RouteResearchWalletMarketHistoryV0Tests(unittest.TestCase):
    def test_version_is_native_route_research(self):
        self.assertEqual(
            history.VERSION,
            "route_research_wallet_market_history_v0",
        )

    @patch.object(history, "_prior_decision_keys_before")
    def test_invalid_run_is_excluded_before_history_loading(self, prior):
        prior.return_value = [
            ("bad-run", "ep-bad"),
            ("good-run", "ep-good"),
        ]
        with patch.object(
            history,
            "load_route_research_decision",
            return_value=None,
        ):
            result = history.load_route_research_wallet_history_v0(
                current_episode_key="current",
                current_token_mint="token",
                current_participant_wallets=("wallet",),
                history_cutoff=1000,
                excluded_acquisition_run_keys=("bad-run",),
            )
        self.assertEqual(
            result.candidate_prior_episode_count,
            1,
        )
        self.assertEqual(
            result.exclusion_counts.get(
                "excluded_invalid_acquisition_run"
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
