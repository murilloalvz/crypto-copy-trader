import unittest
from dataclasses import replace

from src.discovery.copyability import calculate_copyability
from src.discovery.models import WalletTier
from src.discovery.watchlist import classify_wallet
from tests.test_copyability import position, quality_candidate, wallet_positions


class WatchlistTests(unittest.TestCase):
    def test_passed_wallet_is_approved(self):
        result = calculate_copyability(
            quality_candidate(), wallet_positions([position(i) for i in range(10)])
        )

        entry = classify_wallet(result)

        self.assertEqual(entry.tier, WalletTier.APPROVED)

    def test_quality_wallet_with_only_liquidity_barrier_is_observed(self):
        positions = [position(i, liquidity=100_000, invested=100) for i in range(6)]
        positions.extend(
            position(i + 6, liquidity=10_000, invested=250) for i in range(4)
        )
        result = calculate_copyability(quality_candidate(), wallet_positions(positions))

        entry = classify_wallet(result)

        self.assertFalse(result.passed)
        self.assertEqual(entry.tier, WalletTier.OBSERVE)
        self.assertIn("liquid_capital_share_low", result.rejection_reasons)

    def test_hft_wallet_is_rejected_even_with_high_scores(self):
        result = calculate_copyability(
            quality_candidate(trades=900),
            wallet_positions([position(i) for i in range(10)]),
        )
        result = replace(result, copyability_score=90)

        entry = classify_wallet(result)

        self.assertEqual(entry.tier, WalletTier.REJECTED)
        self.assertIn("trade_frequency_too_high", result.rejection_reasons)

    def test_low_quality_wallet_is_not_promoted_for_observation(self):
        positions = [position(i, liquidity=100_000, invested=100) for i in range(6)]
        positions.extend(
            position(i + 6, liquidity=10_000, invested=250) for i in range(4)
        )
        result = calculate_copyability(quality_candidate(), wallet_positions(positions))
        result = replace(
            result,
            candidate=replace(result.candidate, candidate_score=60),
        )

        self.assertEqual(classify_wallet(result).tier, WalletTier.REJECTED)


if __name__ == "__main__":
    unittest.main()
