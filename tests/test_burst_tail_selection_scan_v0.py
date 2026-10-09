from __future__ import annotations

import unittest

from benchmarks.burst_tail_selection_scan_v0.run import (
    CATASTROPHIC_RETURN_PCT,
    _numeric_feature_names,
    _tail_rate,
)


class BurstTailSelectionScanV0Tests(unittest.TestCase):
    def test_closed_flow60_is_excluded(self):
        names = _numeric_feature_names()
        self.assertNotIn("flow60_buy_share_pct", names)

    def test_price_impact_closeness_is_included(self):
        self.assertIn(
            "entry_price_impact_closeness_to_zero",
            _numeric_feature_names(),
        )

    def test_tail_rate_uses_fixed_minus_80_threshold(self):
        self.assertEqual(CATASTROPHIC_RETURN_PCT, -80.0)
        self.assertAlmostEqual(
            _tail_rate([-90.0, -80.0, -79.0, 10.0]),
            50.0,
        )


if __name__ == "__main__":
    unittest.main()
