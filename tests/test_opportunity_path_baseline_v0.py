import unittest

from src.opportunity_path_baseline_v0 import (
    TokenCandidate,
    build_paired_baseline,
    compute_baseline_token_path_metrics,
    eligible_candidates,
    sample_baseline_tokens,
)
from src.opportunity_path_metrics_v0 import CostModel, PathTrade

FREE_COST_MODEL = CostModel(venue_fee_pct=0.0, terminal_fee_pct=0.0)


def pool_candidate(mint: str, *, venue="pump_bonding_curve", age=100, activity=10) -> TokenCandidate:
    return TokenCandidate(
        token_mint=mint, venue=venue, age_seconds_at_signal=age, recent_activity_count=activity
    )


def trade(chain_time: int, price_sol: float, *, venue: str = "pump_bonding_curve") -> PathTrade:
    base_decimals, quote_decimals, liquidity = 6, 9, 1_000_000_000.0
    return PathTrade(
        chain_time=chain_time,
        venue=venue,
        base_amount_raw=10**base_decimals,
        quote_amount_raw=int(price_sol * 10**quote_decimals),
        base_reserves_raw=int(liquidity * 10**base_decimals),
        quote_reserves_raw=int(price_sol * liquidity * 10**quote_decimals),
    )


class EligibleCandidatesTests(unittest.TestCase):
    def test_filters_by_venue_age_and_activity_and_excludes_signal_token(self):
        pool = [
            pool_candidate("A", venue="pump_bonding_curve", age=100, activity=10),
            pool_candidate("B", venue="pumpswap", age=100, activity=10),  # wrong venue
            pool_candidate("C", venue="pump_bonding_curve", age=500, activity=10),  # too old
            pool_candidate("D", venue="pump_bonding_curve", age=100, activity=1),  # too inactive
            pool_candidate("SIGNAL", venue="pump_bonding_curve", age=100, activity=10),  # is the signal
            pool_candidate("E", venue="pump_bonding_curve", age=110, activity=10),  # within tolerance
        ]
        result = eligible_candidates(
            pool,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_age_seconds=100,
            age_tolerance_seconds=30,
            min_activity_count=5,
        )
        self.assertEqual({c.token_mint for c in result}, {"A", "E"})


class SampleBaselineTokensTests(unittest.TestCase):
    def _pool(self, n: int) -> list[TokenCandidate]:
        return [pool_candidate(f"TOKEN_{i}") for i in range(n)]

    def test_same_seed_is_deterministic_regardless_of_pool_order(self):
        pool = self._pool(20)
        first = sample_baseline_tokens(
            pool,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_age_seconds=100,
            age_tolerance_seconds=30,
            min_activity_count=5,
            k=5,
            seed=42,
        )
        shuffled_pool = list(reversed(pool))
        second = sample_baseline_tokens(
            shuffled_pool,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_age_seconds=100,
            age_tolerance_seconds=30,
            min_activity_count=5,
            k=5,
            seed=42,
        )
        self.assertEqual(first.baseline_token_mints, second.baseline_token_mints)
        self.assertEqual(first.k_sampled, 5)
        self.assertFalse(first.insufficient_pool)

    def test_different_seed_can_change_the_sample(self):
        pool = self._pool(20)
        first = sample_baseline_tokens(
            pool,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_age_seconds=100,
            age_tolerance_seconds=30,
            min_activity_count=5,
            k=5,
            seed=1,
        )
        second = sample_baseline_tokens(
            pool,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_age_seconds=100,
            age_tolerance_seconds=30,
            min_activity_count=5,
            k=5,
            seed=2,
        )
        self.assertNotEqual(first.baseline_token_mints, second.baseline_token_mints)

    def test_insufficient_pool_is_flagged_not_padded(self):
        pool = self._pool(3)
        result = sample_baseline_tokens(
            pool,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_age_seconds=100,
            age_tolerance_seconds=30,
            min_activity_count=5,
            k=5,
            seed=42,
        )
        self.assertTrue(result.insufficient_pool)
        self.assertEqual(result.k_sampled, 3)
        self.assertEqual(result.eligible_size, 3)


class BaselineTokenPathMetricsTests(unittest.TestCase):
    def test_uses_the_same_f2_primitives_as_the_signal_side(self):
        trades = [trade(900, 0.0001), trade(1_010, 0.00011), trade(1_030, 0.00016)]
        metrics = compute_baseline_token_path_metrics(
            "BASELINE_TOKEN",
            trades,
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
            window_seconds_grid=(60,),
        )
        self.assertEqual(metrics.entry.trade_chain_time, 1_010)
        self.assertIn(60, metrics.window_metrics)
        self.assertGreater(metrics.window_metrics[60].mfe_pct, 0)

    def test_missing_entry_yields_empty_window_metrics_not_invented_ones(self):
        metrics = compute_baseline_token_path_metrics(
            "DEAD_TOKEN",
            [trade(500, 0.0001)],
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )
        self.assertIsNone(metrics.entry.trade_chain_time)
        self.assertEqual(metrics.window_metrics, {})


class BuildPairedBaselineTests(unittest.TestCase):
    def test_end_to_end_pairs_sample_with_metrics(self):
        pool = [pool_candidate(f"TOKEN_{i}") for i in range(10)]
        trades_by_mint = {
            candidate.token_mint: [trade(1_005, 0.0001), trade(1_050, 0.00012)]
            for candidate in pool
        }
        result = build_paired_baseline(
            pool,
            trades_by_mint,
            signal_token_mint="SIGNAL",
            signal_venue="pump_bonding_curve",
            signal_time=1_000,
            signal_age_seconds=100,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
            age_tolerance_seconds=30,
            min_activity_count=5,
            k=3,
            seed=7,
        )
        self.assertEqual(result.sample.k_sampled, 3)
        self.assertEqual(len(result.token_metrics), 3)
        self.assertEqual(
            {m.token_mint for m in result.token_metrics}, set(result.sample.baseline_token_mints)
        )
        for token_metrics in result.token_metrics:
            self.assertIsNotNone(token_metrics.entry.trade_chain_time)


if __name__ == "__main__":
    unittest.main()
