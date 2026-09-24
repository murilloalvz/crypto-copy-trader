from __future__ import annotations

from types import SimpleNamespace
import unittest

from benchmarks.burst_selection_diagnostic_v0.run import (
    median_of_wallet_medians,
    spearman_rank_correlation,
    tercile_cutpoints,
    tercile_group,
)


class BurstSelectionDiagnosticV0Tests(unittest.TestCase):
    def test_tercile_cutpoints_are_outcome_blind_feature_quantiles(self):
        low, high = tercile_cutpoints([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        self.assertAlmostEqual(low, 2.6666666667)
        self.assertAlmostEqual(high, 4.3333333333)
        self.assertEqual(tercile_group(2.0, low, high), "LOW")
        self.assertEqual(tercile_group(3.0, low, high), "MID")
        self.assertEqual(tercile_group(6.0, low, high), "HIGH")

    def test_spearman_detects_monotonic_direction(self):
        self.assertAlmostEqual(
            spearman_rank_correlation(
                [1.0, 2.0, 3.0, 4.0],
                [10.0, 20.0, 30.0, 40.0],
            ),
            1.0,
        )
        self.assertAlmostEqual(
            spearman_rank_correlation(
                [1.0, 2.0, 3.0, 4.0],
                [40.0, 30.0, 20.0, 10.0],
            ),
            -1.0,
        )

    def test_spearman_returns_none_for_constant_feature(self):
        self.assertIsNone(
            spearman_rank_correlation(
                [1.0, 1.0, 1.0],
                [1.0, 2.0, 3.0],
            )
        )

    def test_participant_feature_is_median_of_wallet_medians(self):
        rows = [
            SimpleNamespace(
                wallet_address="A",
                executable_quote_return_pct=10.0,
            ),
            SimpleNamespace(
                wallet_address="A",
                executable_quote_return_pct=20.0,
            ),
            SimpleNamespace(
                wallet_address="B",
                executable_quote_return_pct=-20.0,
            ),
            SimpleNamespace(
                wallet_address="B",
                executable_quote_return_pct=-10.0,
            ),
        ]
        value, wallets, associations = median_of_wallet_medians(rows)
        self.assertEqual(wallets, 2)
        self.assertEqual(associations, 4)
        self.assertEqual(value, 0.0)


if __name__ == "__main__":
    unittest.main()
