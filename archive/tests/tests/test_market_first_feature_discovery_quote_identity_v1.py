from __future__ import annotations

from dataclasses import dataclass
import unittest

from benchmarks.market_first_feature_discovery_v1.run import _causal_quote_asset_summary
from src.market_first_bonding_curve_geometry_v1 import SOL_QUOTE_MINT


@dataclass(frozen=True)
class Row:
    quote_asset_key: str | None


class MarketFirstFeatureDiscoveryQuoteIdentityV1Tests(unittest.TestCase):
    def test_single_causal_quote_identity_marks_default_sol(self):
        summary = _causal_quote_asset_summary(
            [Row(SOL_QUOTE_MINT), Row(SOL_QUOTE_MINT)]
        )
        self.assertEqual(summary["quote_asset_key"], SOL_QUOTE_MINT)
        self.assertEqual(summary["quote_asset_identity_count"], 1)
        self.assertTrue(summary["is_default_sol_quote"])

    def test_conflicting_causal_quote_identity_fails_closed(self):
        summary = _causal_quote_asset_summary(
            [Row(SOL_QUOTE_MINT), Row("other-quote")]
        )
        self.assertIsNone(summary["quote_asset_key"])
        self.assertEqual(summary["quote_asset_identity_count"], 2)
        self.assertFalse(summary["is_default_sol_quote"])


if __name__ == "__main__":
    unittest.main()
