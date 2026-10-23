from __future__ import annotations

import unittest

from src.market_first_liquidity_discovery_v0 import FEATURE_IDS, liquidity_features_v0
from src.opportunity_feature_matrix_v0 import (
    TRACK_MARKET_FIRST,
    assert_selector_feature_eligible_v0,
    feature_spec_v0,
)


T0 = 1_000_000_000_000
CUTOFF = T0 + 5_000_000_000


def _row(
    *,
    offset_ns: int,
    event_key: str,
    real: int | None,
    virtual: int | None,
    quote_mint: str | None = "WSOL",
):
    return {
        "event_key": event_key,
        "observed_wall_ns": T0 + offset_ns,
        "quote_mint": quote_mint,
        "real_quote_reserves_raw": real,
        "virtual_quote_reserves_raw": virtual,
    }


class MarketFirstLiquidityDiscoveryV0Tests(unittest.TestCase):
    def test_exact_reserve_features(self):
        result = liquidity_features_v0(
            [
                _row(offset_ns=1_000_000_000, event_key="a", real=10, virtual=100),
                _row(offset_ns=4_000_000_000, event_key="b", real=25, virtual=125),
            ],
            anchor_wall_ns=T0,
            cutoff_wall_ns=CUTOFF,
        )
        self.assertEqual(result["status"], "AVAILABLE_CAUSAL_MARKET_RESERVE_STATE")
        self.assertEqual(result["quote_mint"], "WSOL")
        self.assertEqual(result["features"]["mf_pump_real_quote_reserve_raw_at_cutoff"], 25)
        self.assertAlmostEqual(result["features"]["mf_pump_real_to_virtual_quote_reserve_ratio_at_cutoff"], 0.2)
        self.assertAlmostEqual(result["features"]["mf_pump_real_quote_reserve_change_over_virtual_start"], 0.15)

    def test_future_row_after_cutoff_cannot_change_features(self):
        inside = [_row(offset_ns=4_000_000_000, event_key="inside", real=20, virtual=100)]
        future = _row(offset_ns=6_000_000_000, event_key="future", real=99_999, virtual=100)
        first = liquidity_features_v0(inside, anchor_wall_ns=T0, cutoff_wall_ns=CUTOFF)
        second = liquidity_features_v0([*inside, future], anchor_wall_ns=T0, cutoff_wall_ns=CUTOFF)
        self.assertEqual(first, second)

    def test_quote_mint_conflict_fails_closed(self):
        result = liquidity_features_v0(
            [
                _row(offset_ns=1, event_key="a", real=10, virtual=100, quote_mint="WSOL"),
                _row(offset_ns=2, event_key="b", real=11, virtual=101, quote_mint="USDC"),
            ],
            anchor_wall_ns=T0,
            cutoff_wall_ns=CUTOFF,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE_QUOTE_MINT_CONFLICT_OR_MISSING")
        self.assertTrue(all(result["features"][feature_id] is None for feature_id in FEATURE_IDS))

    def test_missing_reserve_state_fails_closed(self):
        result = liquidity_features_v0(
            [_row(offset_ns=1, event_key="a", real=None, virtual=100)],
            anchor_wall_ns=T0,
            cutoff_wall_ns=CUTOFF,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE_RESERVE_STATE_MISSING")
        self.assertTrue(all(result["features"][feature_id] is None for feature_id in FEATURE_IDS))

    def test_non_five_second_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "frozen 5s"):
            liquidity_features_v0([], anchor_wall_ns=T0, cutoff_wall_ns=T0 + 4_000_000_000)

    def test_liquidity_features_are_registered_but_forbidden_in_selectors(self):
        for feature_id in FEATURE_IDS:
            spec = feature_spec_v0(feature_id)
            self.assertEqual(spec.track, TRACK_MARKET_FIRST)
            self.assertTrue(spec.diagnostic_only)
            self.assertFalse(spec.selector_eligible)
            self.assertFalse(spec.execution_only)
            self.assertFalse(spec.future_dependent)
            with self.assertRaisesRegex(ValueError, "diagnostic-only"):
                assert_selector_feature_eligible_v0(feature_id, selector_track=TRACK_MARKET_FIRST)


if __name__ == "__main__":
    unittest.main()
