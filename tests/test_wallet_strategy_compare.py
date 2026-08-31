import unittest

from src.wallet_strategy_compare import (
    build_pairwise_strategy_comparisons,
    compare_wallet_strategy_fingerprints,
    fingerprint_evidence_ready,
    summarize_recurring_strategy_patterns,
)
from src.wallet_strategy_lab import build_wallet_strategy_fingerprint


def _swap(token: str, at: int, change: float, dex: str = "Jupiter v6") -> dict:
    return {
        "kind": "swap",
        "status": "success",
        "token_mint": token,
        "token_change": change,
        "block_time": at,
        "dex": dex,
    }


def _swing_single(address: str, *, offset: int = 0):
    swaps = []
    for index in range(12):
        buy_at = offset + index * 3 * 86_400
        swaps.extend(
            [
                _swap(f"{address}-{index}", buy_at, 100, "PumpSwap"),
                _swap(f"{address}-{index}", buy_at + 2 * 86_400, -100, "PumpSwap"),
            ]
        )
    return build_wallet_strategy_fingerprint(address, swaps)


class WalletStrategyCompareTests(unittest.TestCase):
    def test_identical_descriptive_patterns_match_all_dimensions(self):
        left = _swing_single("left")
        right = _swing_single("right", offset=123)

        comparison = compare_wallet_strategy_fingerprints(left, right)

        self.assertEqual(comparison.comparable_dimensions, 4)
        self.assertEqual(comparison.matching_dimensions, 4)
        self.assertEqual(comparison.similarity_pct, 100.0)
        self.assertTrue(comparison.shared_signature)
        self.assertFalse(comparison.differing)

    def test_empty_sample_is_not_treated_as_real_strategy_similarity(self):
        real = _swing_single("real")
        empty = build_wallet_strategy_fingerprint("empty", [])

        comparison = compare_wallet_strategy_fingerprints(real, empty)

        self.assertEqual(comparison.comparable_dimensions, 0)
        self.assertIsNone(comparison.similarity_pct)
        self.assertIn("right_evidence_not_ready", comparison.warnings)
        self.assertIn("few_comparable_dimensions", comparison.warnings)

    def test_evidence_ready_is_coverage_not_profitability(self):
        fingerprint = _swing_single("ready")

        self.assertTrue(fingerprint_evidence_ready(fingerprint))

    def test_short_burst_with_small_exit_sample_is_not_promoted_to_ready(self):
        swaps = []
        for token_index in range(4):
            base = token_index * 1_000
            token = f"T{token_index}"
            swaps.extend(
                [
                    _swap(token, base, 20),
                    _swap(token, base + 60, 20),
                    _swap(token, base + 120, 20),
                    _swap(token, base + 180, -30),
                    _swap(token, base + 240, -30),
                ]
            )

        fingerprint = build_wallet_strategy_fingerprint("burst", swaps)

        self.assertNotEqual(fingerprint.sample_grade, "INSUFFICIENT")
        self.assertGreaterEqual(fingerprint.roundtrip_share_pct, 50.0)
        self.assertGreaterEqual(fingerprint.complete_like_sizing_count, 3)
        self.assertIn("short_observation_window", fingerprint.flags)
        self.assertIn("exit_sizing_sample_too_small", fingerprint.flags)
        self.assertFalse(fingerprint_evidence_ready(fingerprint))

    def test_recurring_signature_requires_multiple_ready_wallets_for_preliminary_support(self):
        first = _swing_single("first")
        second = _swing_single("second", offset=777)
        empty = build_wallet_strategy_fingerprint("empty", [])

        patterns = summarize_recurring_strategy_patterns([first, second, empty])
        repeated = next(item for item in patterns if item.signature == first.signature)

        self.assertEqual(repeated.wallet_count, 2)
        self.assertEqual(repeated.evidence_ready_count, 2)
        self.assertEqual(repeated.support_grade, "MULTI_WALLET_PRELIMINARY")

    def test_pairwise_results_sort_most_similar_first(self):
        first = _swing_single("first")
        second = _swing_single("second", offset=777)
        empty = build_wallet_strategy_fingerprint("empty", [])

        comparisons = build_pairwise_strategy_comparisons([first, empty, second])

        self.assertEqual(comparisons[0].similarity_pct, 100.0)
        self.assertIsNone(comparisons[-1].similarity_pct)


if __name__ == "__main__":
    unittest.main()
