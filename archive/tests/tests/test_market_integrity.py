import unittest
from dataclasses import replace

from src.discovery.models import WaveTokenSnapshot
from src.market_integrity import build_market_integrity_features


def token(**changes) -> WaveTokenSnapshot:
    item = WaveTokenSnapshot(
        token="TOKEN",
        name="Token",
        symbol="TKN",
        price_usd=1.0,
        liquidity_usd=100_000,
        market_cap_usd=500_000,
        created_at_ms=1,
        holders=100,
        buys=60,
        sells=40,
        total_transactions=100,
        volume_5m_usd=12_000,
        volume_1h_usd=60_000,
        volume_24h_usd=600_000,
        top10_pct=20,
        dev_pct=2,
        insiders_pct=3,
        snipers_pct=4,
        risk_score=2,
        lp_burn_pct=100,
        mint_authority=None,
        freeze_authority=None,
        market="test",
        pool_address="pool",
    )
    return replace(item, **changes)


class MarketIntegrityTests(unittest.TestCase):
    def test_builds_raw_descriptive_ratios_without_manipulation_score(self):
        features = build_market_integrity_features(token())

        self.assertAlmostEqual(features.buy_pressure_pct, 60.0)
        self.assertAlmostEqual(features.trade_imbalance_pct, 20.0)
        self.assertAlmostEqual(features.volume_acceleration, 2.4)
        self.assertAlmostEqual(features.volume_5m_share_of_1h_pct, 20.0)
        self.assertAlmostEqual(features.volume_1h_share_of_24h_pct, 10.0)
        self.assertAlmostEqual(features.transactions_per_holder, 1.0)
        self.assertEqual(features.existing_gate_flags, ())
        self.assertFalse(hasattr(features, "score"))
        self.assertFalse(hasattr(features, "wash_trading_detected"))

    def test_reuses_existing_wave_thresholds_only_as_labeled_flags(self):
        features = build_market_integrity_features(
            token(
                buys=99,
                sells=1,
                top10_pct=41,
                dev_pct=11,
                insiders_pct=21,
                snipers_pct=21,
                lp_burn_pct=0,
            )
        )

        self.assertEqual(
            features.existing_gate_flags,
            (
                "trade_imbalance_extreme",
                "top10_concentration_high",
                "developer_concentration_high",
                "insider_concentration_high",
                "sniper_concentration_high",
                "lp_burn_unconfirmed",
            ),
        )

    def test_inconsistent_volume_windows_disable_acceleration_but_remain_visible(self):
        features = build_market_integrity_features(
            token(volume_5m_usd=70_000, volume_1h_usd=60_000)
        )

        self.assertIsNone(features.volume_acceleration)
        self.assertIn("volume_windows_inconsistent", features.data_quality_flags)
        self.assertGreater(features.volume_5m_share_of_1h_pct, 100)

    def test_missing_aggregate_fields_are_explicit_not_silently_imputed(self):
        features = build_market_integrity_features(
            token(
                holders=None,
                buys=0,
                sells=0,
                top10_pct=None,
                dev_pct=None,
                insiders_pct=None,
                snipers_pct=None,
                risk_score=None,
            )
        )

        self.assertIsNone(features.buy_pressure_pct)
        self.assertIsNone(features.transactions_per_holder)
        self.assertIn("trade_counts_unavailable", features.data_quality_flags)
        self.assertIn("holders_unavailable", features.data_quality_flags)
        self.assertIn("risk_unavailable", features.data_quality_flags)
        self.assertIn("counterparty_graph_unavailable", features.detection_limits)

    def test_rejects_negative_provider_counts_and_volumes(self):
        with self.assertRaises(ValueError):
            build_market_integrity_features(token(buys=-1))
        with self.assertRaises(ValueError):
            build_market_integrity_features(token(volume_5m_usd=-1))


if __name__ == "__main__":
    unittest.main()
