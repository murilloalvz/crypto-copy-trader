from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.commodity_signal_plane_v0.benchmark import TraceRecord
from src import database
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketTradeObservation,
)
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.route_research_early_opportunity_v55 import derived_features_from_bundle_v55
from src.route_research_prospective_flow60_buy_share_v68 import (
    V68_FEATURE_NAME,
    V68_LOW_MAX,
    frozen_flow60_buy_share_group_v68,
)
from src.signal_plane_research_persistence_v0 import (
    persist_signal_plane_research_record,
)


def _trigger_snapshot(*, token_mint: str, as_of: int, chain_as_of: int) -> dict:
    return {
        "token_mint": token_mint,
        "as_of": as_of,
        "method_version": MARKET_OPPORTUNITY_RADAR_VERSION,
        "trigger_kind": "fresh_market_burst",
        "direction": "upward_pressure",
        "features": {
            "token_mint": token_mint,
            "as_of": as_of,
            "chain_as_of": chain_as_of,
            "fast_window_seconds": 30,
            "baseline_horizon_seconds": 300,
            "fast_event_count": 6,
            "baseline_event_count": 3,
            "fast_buy_count": 4,
            "fast_sell_count": 2,
            "fast_unique_wallet_count": 6,
            "fast_unique_transaction_count": 6,
            "wallet_identity_coverage_pct": 100.0,
            "transaction_identity_coverage_pct": 100.0,
            "notional_coverage_pct": 100.0,
            "price_coverage_pct": 100.0,
            "fast_event_rate_per_second": 0.2,
            "baseline_event_rate_per_second": 3 / 270,
            "activity_acceleration_ratio": 18.0,
            "signed_notional_imbalance_pct": 33.3333333333,
            "count_imbalance_pct": 33.3333333333,
            "direction": "upward_pressure",
            "first_price_usd": 1.0,
            "last_price_usd": 1.06,
            "fast_return_pct": 6.0,
            "median_observation_lag_seconds": None,
            "max_observation_lag_seconds": None,
            "venues": ["pumpswap"],
            "market_age_seconds": None,
            "data_quality_flags": ["lifecycle_missing"],
        },
    }


class SignalPlaneV68FeatureBridgeV0Tests(unittest.TestCase):
    def test_research_plane_reconstructs_frozen_flow60_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "signal-plane-v68-feature.db"
            fake_settings = SimpleNamespace(database_path=db_path)

            run_key = "systems-feature-bridge-v0"
            token = "TOKEN"
            sides = ("buy", "buy", "sell", "buy", "sell", "buy", "sell")
            final_result = None

            with patch.object(database, "settings", fake_settings):
                for sequence, side in enumerate(sides):
                    chain_time = 1000 + sequence
                    observation = MarketTradeObservation(
                        token_mint=token,
                        side=side,
                        chain_time=chain_time,
                        observed_at=chain_time,
                        wallet_address=f"wallet-{sequence}",
                        notional_usd=10.0 + sequence,
                        price_usd=1.0 + sequence * 0.01,
                        venue="pumpswap",
                        transaction_key=f"tx-{sequence}",
                    )
                    record = TraceRecord(
                        sequence=sequence,
                        arrival_offset_ns=sequence * 1_000_000,
                        kind="trade",
                        event_key=f"event-{sequence}",
                        source_provider="systems-feature-bridge",
                        trade=observation,
                    )
                    snapshot = (
                        _trigger_snapshot(
                            token_mint=token,
                            as_of=chain_time,
                            chain_as_of=chain_time,
                        )
                        if sequence == len(sides) - 1
                        else None
                    )
                    result = persist_signal_plane_research_record(
                        acquisition_run_key=run_key,
                        record=record,
                        trigger_snapshot=snapshot,
                    )
                    if snapshot is not None:
                        final_result = result

                self.assertIsNotNone(final_result)
                self.assertIsNotNone(final_result.episode)
                self.assertTrue(final_result.episode.admitted)

                episode = get_market_opportunity_episode(
                    final_result.episode.episode_key
                )
                self.assertIsNotNone(episode)

                bundle = build_episode_enrichment_bundle(
                    episode=episode,
                    as_of=1006,
                )
                flow60 = next(
                    item
                    for item in bundle.core.flow_windows
                    if item.window_seconds == 60
                )
                derived = derived_features_from_bundle_v55(bundle)
                flow60_buy_share = derived[V68_FEATURE_NAME]

        self.assertEqual(flow60.event_count, 7)
        self.assertEqual(flow60.buy_count, 4)
        self.assertEqual(flow60.sell_count, 3)
        self.assertAlmostEqual(
            flow60_buy_share,
            100.0 * 4 / 7,
            places=10,
        )
        self.assertLess(flow60_buy_share, V68_LOW_MAX)
        self.assertEqual(
            frozen_flow60_buy_share_group_v68(flow60_buy_share),
            "LOW",
        )


if __name__ == "__main__":
    unittest.main()
