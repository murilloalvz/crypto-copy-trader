from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketTradeObservation,
)
from src.signal_plane_episode_admission_v0 import (
    SIGNAL_PLANE_EPISODE_ADMISSION_VERSION,
    admit_signal_plane_trigger_snapshot,
)


def _snapshot():
    return {
        "token_mint": "TOKEN",
        "as_of": 120,
        "method_version": MARKET_OPPORTUNITY_RADAR_VERSION,
        "trigger_kind": "fresh_market_burst",
        "direction": "upward_pressure",
        "features": {
            "token_mint": "TOKEN",
            "as_of": 120,
            "chain_as_of": 119,
            "fast_window_seconds": 30,
            "baseline_horizon_seconds": 300,
            "fast_event_count": 6,
            "baseline_event_count": 3,
            "fast_buy_count": 5,
            "fast_sell_count": 1,
            "fast_unique_wallet_count": 5,
            "fast_unique_transaction_count": 6,
            "wallet_identity_coverage_pct": 100.0,
            "transaction_identity_coverage_pct": 100.0,
            "notional_coverage_pct": 100.0,
            "price_coverage_pct": 100.0,
            "fast_event_rate_per_second": 0.2,
            "baseline_event_rate_per_second": 3 / 270,
            "activity_acceleration_ratio": 18.0,
            "signed_notional_imbalance_pct": 50.0,
            "count_imbalance_pct": 66.6666666667,
            "direction": "upward_pressure",
            "first_price_usd": 1.0,
            "last_price_usd": 1.1,
            "fast_return_pct": 10.0,
            "median_observation_lag_seconds": None,
            "max_observation_lag_seconds": None,
            "venues": ["pump"],
            "market_age_seconds": 20,
            "data_quality_flags": [],
        },
    }


class SignalPlaneEpisodeAdmissionV0Tests(unittest.TestCase):
    def test_version_is_frozen(self):
        self.assertEqual(
            SIGNAL_PLANE_EPISODE_ADMISSION_VERSION,
            "signal_plane_episode_admission_v0",
        )

    def test_none_trigger_is_not_admitted(self):
        observation = MarketTradeObservation(
            token_mint="TOKEN",
            side="buy",
            chain_time=119,
            observed_at=120,
            venue="pump",
            transaction_key="tx",
        )
        with patch(
            "src.signal_plane_episode_admission_v0.assign_signal_plane_trigger_episode"
        ) as assign, patch(
            "src.signal_plane_episode_admission_v0.admit_opportunity_episode"
        ) as admit:
            result = admit_signal_plane_trigger_snapshot(
                acquisition_run_key="run",
                trigger_snapshot=None,
                observation=observation,
            )
        self.assertIsNone(result)
        assign.assert_not_called()
        admit.assert_not_called()

    def test_trigger_uses_episode_first_observation_for_admission(self):
        observation = MarketTradeObservation(
            token_mint="TOKEN",
            side="buy",
            chain_time=119,
            observed_at=120,
            venue="pump",
            transaction_key="tx",
        )
        episode = SimpleNamespace(
            episode_key="episode-key",
            token_mint="TOKEN",
            first_trigger_observed_at=120,
        )
        with patch(
            "src.signal_plane_episode_admission_v0.assign_signal_plane_trigger_episode",
            return_value=episode,
        ) as assign, patch(
            "src.signal_plane_episode_admission_v0.admit_opportunity_episode",
            return_value=True,
        ) as admit:
            result = admit_signal_plane_trigger_snapshot(
                acquisition_run_key="run",
                trigger_snapshot=_snapshot(),
                observation=observation,
            )

        self.assertIsNotNone(result)
        self.assertTrue(result.admitted)
        self.assertEqual(result.episode_key, "episode-key")
        assign.assert_called_once()
        admit.assert_called_once_with(
            acquisition_run_key="run",
            episode_key="episode-key",
            admitted_at=120,
        )


if __name__ == "__main__":
    unittest.main()
