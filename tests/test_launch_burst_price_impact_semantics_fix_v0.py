from __future__ import annotations

import math
import unittest

from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    route_quality_mapping,
    route_quality_quote,
)
from src.causal_quotes import CausalQuoteObservation


class LaunchBurstPriceImpactSemanticsFixV0Tests(unittest.TestCase):
    def contract(self):
        return {"route_quality": {"max_provider_price_impact_pct_points": 2.0}}

    def quote(self, impact):
        return CausalQuoteObservation(
            token_mint="MINT",
            side="buy",
            market_time=1,
            observed_at=1,
            price_usd=1.0,
            source="test",
            executable=True,
            resolution_seconds=1,
            provider_price_impact_pct_points=impact,
        )

    def test_negative_price_impact_is_valid_and_below_upper_bound(self):
        self.assertEqual(route_quality_quote(self.quote(-0.1), self.contract()), (True, "OK"))
        self.assertTrue(route_quality_mapping({"provider_price_impact_pct_points": -29.9}, self.contract()))

    def test_none_and_nonfinite_are_unavailable(self):
        self.assertEqual(
            route_quality_quote(self.quote(None), self.contract()),
            (False, "PRICE_IMPACT_UNAVAILABLE"),
        )
        self.assertEqual(
            route_quality_quote(self.quote(float("nan")), self.contract()),
            (False, "PRICE_IMPACT_UNAVAILABLE"),
        )
        self.assertFalse(route_quality_mapping({"provider_price_impact_pct_points": math.inf}, self.contract()))

    def test_positive_value_above_frozen_cap_is_rejected(self):
        self.assertEqual(
            route_quality_quote(self.quote(2.0001), self.contract()),
            (False, "PRICE_IMPACT_EXCEEDS_LIMIT"),
        )
        self.assertFalse(route_quality_mapping({"provider_price_impact_pct_points": 50.0}, self.contract()))

    def test_positive_value_at_cap_is_valid(self):
        self.assertEqual(route_quality_quote(self.quote(2.0), self.contract()), (True, "OK"))
        self.assertTrue(route_quality_mapping({"provider_price_impact_pct_points": 2.0}, self.contract()))


if __name__ == "__main__":
    unittest.main()
