import unittest
from dataclasses import replace

from src.discovery.models import WaveTokenSnapshot
from src.wave_radar import build_wave_radar_report, evaluate_wave_token


def token(symbol="WAVE", **changes):
    item = WaveTokenSnapshot(
        token="38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump",
        name="Wave Test",
        symbol=symbol,
        price_usd=0.001,
        liquidity_usd=200_000,
        market_cap_usd=1_000_000,
        created_at_ms=1_800_000_000_000,
        holders=1_000,
        buys=700,
        sells=300,
        total_transactions=1_000,
        volume_5m_usd=30_000,
        volume_1h_usd=100_000,
        volume_24h_usd=1_000_000,
        top10_pct=20,
        dev_pct=2,
        insiders_pct=3,
        snipers_pct=4,
        risk_score=2,
        lp_burn_pct=100,
        mint_authority=None,
        freeze_authority=None,
        market="pumpfun-amm",
        pool_address="pool-address",
    )
    return replace(item, **changes)


class WaveRadarTests(unittest.TestCase):
    def test_liquid_active_distributed_token_passes(self):
        result = evaluate_wave_token(token())

        self.assertTrue(result.passed)
        self.assertGreater(result.wave_score, 50)
        self.assertGreater(result.volume_acceleration, 1)
        self.assertEqual(result.buy_pressure_pct, 70)

    def test_authorities_and_high_risk_are_hard_barriers(self):
        result = evaluate_wave_token(
            token(risk_score=9, mint_authority="mint-owner", freeze_authority="freeze-owner")
        )

        self.assertFalse(result.passed)
        self.assertIn("risk_high", result.barriers)
        self.assertIn("mint_authority_enabled", result.barriers)
        self.assertIn("freeze_authority_enabled", result.barriers)

    def test_lp_burn_zero_is_contextual_caution_when_risk_score_is_available(self):
        result = evaluate_wave_token(token(lp_burn_pct=0, risk_score=3))

        self.assertTrue(result.passed)
        self.assertIn("lp_burn_unconfirmed", result.cautions)
        self.assertNotIn("lp_burn_low", result.barriers)

    def test_missing_holders_and_extreme_buy_pressure_are_rejected(self):
        result = evaluate_wave_token(token(holders=None, buys=99, sells=1))

        self.assertFalse(result.passed)
        self.assertIn("holders_unavailable", result.barriers)
        self.assertIn("trade_imbalance_extreme", result.barriers)
        self.assertEqual(result.score_components["buy_pressure"], 0)

    def test_safe_token_without_current_acceleration_is_not_a_wave(self):
        result = evaluate_wave_token(
            token(volume_5m_usd=7_000, volume_1h_usd=120_000)
        )

        self.assertFalse(result.passed)
        self.assertIn("volume_not_accelerating", result.barriers)

    def test_minimum_wave_score_is_a_hard_gate(self):
        result = evaluate_wave_token(
            token(
                liquidity_usd=55_000,
                volume_5m_usd=6_000,
                volume_1h_usd=48_000,
                buys=55,
                sells=45,
                risk_score=6,
                top10_pct=39,
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("wave_score_low", result.barriers)

    def test_concentration_and_weak_market_are_rejected(self):
        result = evaluate_wave_token(
            token(
                liquidity_usd=10_000,
                volume_5m_usd=100,
                holders=10,
                total_transactions=12,
                top10_pct=70,
                dev_pct=30,
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("liquidity_low", result.barriers)
        self.assertIn("volume_5m_low", result.barriers)
        self.assertIn("top10_concentration_high", result.barriers)

    def test_report_lists_passing_tokens_before_near_misses(self):
        rejected = token(
            symbol="RISK",
            token="HkFGQsW8mr8DTC2AE2WcC7MzwSnynfEryGMQSht271nf",
            risk_score=9,
            volume_5m_usd=200_000,
        )

        report = build_wave_radar_report([rejected, token()])

        self.assertEqual(report.analyzed_count, 2)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.results[0].token.symbol, "WAVE")
        self.assertEqual(report.rejected_by_reason["risk_high"], 1)


if __name__ == "__main__":
    unittest.main()
