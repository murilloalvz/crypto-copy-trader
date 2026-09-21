from __future__ import annotations

import unittest

from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    route_quality_quote,
)
from src.causal_quotes import CausalQuoteObservation


class PriceImpactSemanticsFixV0Tests(unittest.TestCase):
    def _quote(self, impact):
        return CausalQuoteObservation(
            token_mint="Token1111111111111111111111111111111111",
            side="buy",
            market_time=1,
            observed_at=1,
            price_usd=1.0,
            source="test",
            executable=True,
            provider_price_impact_pct_points=impact,
        )

    def test_negative_finite_price_impact_is_available_and_passes_upper_bound(self):
        ok, reason = route_quality_quote(
            self._quote(-17.42446229973143),
            {"route_quality": {"max_provider_price_impact_pct_points": 2.0}},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "OK")

    def test_missing_price_impact_remains_unavailable(self):
        ok, reason = route_quality_quote(
            self._quote(None),
            {"route_quality": {"max_provider_price_impact_pct_points": 2.0}},
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "PRICE_IMPACT_UNAVAILABLE")

    def test_positive_price_impact_above_upper_bound_is_rejected(self):
        ok, reason = route_quality_quote(
            self._quote(2.8576528163004125),
            {"route_quality": {"max_provider_price_impact_pct_points": 2.0}},
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "PRICE_IMPACT_EXCEEDS_LIMIT")


if __name__ == "__main__":
    unittest.main()
