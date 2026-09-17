from __future__ import annotations

import struct
import unittest

from src.market_first_bonding_curve_geometry_v1 import (
    FEATURE_IDS,
    SOL_QUOTE_MINT,
    decode_create_geometry_payload_v1,
    decode_trade_geometry_payload_v1,
    geometry_features_v1,
)
from src.pump_bonding_stream import (
    PUMP_CREATE_EVENT_DISCRIMINATOR,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
)


def _borsh_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _create_payload(*, vt: int, vs: int, rt: int, supply: int, timestamp: int = 1000) -> bytes:
    return b"".join(
        [
            PUMP_CREATE_EVENT_DISCRIMINATOR,
            _borsh_string("name"),
            _borsh_string("SYM"),
            _borsh_string("uri"),
            bytes([1]) * 32,  # mint
            bytes([2]) * 32,  # bonding curve
            bytes([3]) * 32,  # user
            bytes([4]) * 32,  # creator
            struct.pack("<q", timestamp),
            struct.pack("<Q", vt),
            struct.pack("<Q", vs),
            struct.pack("<Q", rt),
            struct.pack("<Q", supply),
        ]
    )


def _trade_payload(
    *,
    vt: int,
    vs: int,
    rt: int,
    rs: int,
    timestamp: int = 1002,
    is_buy: bool = True,
) -> bytes:
    return b"".join(
        [
            PUMP_TRADE_EVENT_DISCRIMINATOR,
            bytes([1]) * 32,  # same mint
            struct.pack("<Q", 100_000_000),
            struct.pack("<Q", 1_000_000),
            bytes([1 if is_buy else 0]),
            bytes([5]) * 32,
            struct.pack("<q", timestamp),
            struct.pack("<Q", vs),
            struct.pack("<Q", vt),
            struct.pack("<Q", rs),
            struct.pack("<Q", rt),
        ]
    )


class MarketFirstBondingCurveGeometryV1Tests(unittest.TestCase):
    def test_create_and_trade_geometry_offsets_are_exact(self):
        create = decode_create_geometry_payload_v1(
            _create_payload(vt=1_073_000, vs=30_000, rt=793_100, supply=1_000_000)
        )
        trade = decode_trade_geometry_payload_v1(
            _trade_payload(vt=900_000, vs=36_000, rt=620_000, rs=6_000)
        )
        self.assertIsNotNone(create)
        self.assertIsNotNone(trade)
        assert create is not None and trade is not None
        self.assertEqual(create["virtual_token_reserves_raw"], 1_073_000)
        self.assertEqual(create["virtual_sol_reserves_raw"], 30_000)
        self.assertEqual(create["real_token_reserves_raw"], 793_100)
        self.assertEqual(create["token_total_supply_raw"], 1_000_000)
        self.assertEqual(trade["virtual_token_reserves_raw"], 900_000)
        self.assertEqual(trade["virtual_sol_reserves_raw"], 36_000)
        self.assertEqual(trade["real_token_reserves_raw"], 620_000)
        self.assertEqual(trade["real_sol_reserves_raw"], 6_000)
        self.assertEqual(create["mint"], trade["mint"])

    def test_sol_geometry_features_are_mechanical_and_exact(self):
        initial = {
            "virtual_token_reserves_raw": 1_073_000_000_000_000,
            "virtual_sol_reserves_raw": 30_000_000_000,
            "real_token_reserves_raw": 793_100_000_000_000,
        }
        cutoff = {
            "virtual_token_reserves_raw": 900_000_000_000_000,
            "virtual_sol_reserves_raw": 36_000_000_000,
            "real_token_reserves_raw": 620_000_000_000_000,
            "real_sol_reserves_raw": 6_000_000_000,
        }
        result = geometry_features_v1(
            initial_state=initial,
            cutoff_state=cutoff,
            quote_mint=SOL_QUOTE_MINT,
        )
        self.assertEqual(result["status"], "AVAILABLE_CAUSAL_SOL_BONDING_CURVE_GEOMETRY")
        features = result["features"]
        self.assertEqual(set(features), set(FEATURE_IDS))
        self.assertAlmostEqual(
            features["mf_curve_progress_pct"],
            100.0 * (1.0 - 620_000_000_000_000 / 793_100_000_000_000),
        )
        self.assertAlmostEqual(features["mf_curve_virtual_sol_reserves_sol_at_cutoff"], 36.0)
        self.assertAlmostEqual(features["mf_curve_real_sol_reserves_sol_at_cutoff"], 6.0)
        self.assertAlmostEqual(
            features["mf_curve_spot_price_multiplier_vs_initial"],
            (36_000_000_000 * 1_073_000_000_000_000)
            / (900_000_000_000_000 * 30_000_000_000),
        )
        self.assertIsNotNone(features["mf_curve_buy_impact_0_10_sol_pct_curve_only"])
        self.assertGreater(features["mf_curve_real_token_capacity_ratio_0_10_sol"], 1.0)
        self.assertFalse(result["probe_capacity_bound"]["0_10_sol"])

    def test_non_sol_quote_fails_closed_for_geometry_v1(self):
        result = geometry_features_v1(
            initial_state={},
            cutoff_state={},
            quote_mint="USDC",
        )
        self.assertEqual(result["status"], "OUT_OF_SCOPE_NON_SOL_QUOTE")
        self.assertTrue(all(value is None for value in result["features"].values()))

    def test_real_token_reserve_regression_fails_closed(self):
        result = geometry_features_v1(
            initial_state={
                "virtual_token_reserves_raw": 1000,
                "virtual_sol_reserves_raw": 1000,
                "real_token_reserves_raw": 500,
            },
            cutoff_state={
                "virtual_token_reserves_raw": 1000,
                "virtual_sol_reserves_raw": 1000,
                "real_token_reserves_raw": 501,
                "real_sol_reserves_raw": 0,
            },
            quote_mint=SOL_QUOTE_MINT,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE_REAL_TOKEN_RESERVE_REGRESSION")
        self.assertTrue(all(value is None for value in result["features"].values()))

    def test_capacity_bound_probe_is_missing_instead_of_inventing_capped_fill(self):
        result = geometry_features_v1(
            initial_state={
                "virtual_token_reserves_raw": 1_000_000,
                "virtual_sol_reserves_raw": 30_000_000_000,
                "real_token_reserves_raw": 1000,
            },
            cutoff_state={
                "virtual_token_reserves_raw": 1_000_000,
                "virtual_sol_reserves_raw": 30_000_000_000,
                "real_token_reserves_raw": 1,
                "real_sol_reserves_raw": 0,
            },
            quote_mint=SOL_QUOTE_MINT,
        )
        self.assertTrue(result["probe_capacity_bound"]["0_10_sol"])
        self.assertIsNone(result["features"]["mf_curve_buy_impact_0_10_sol_pct_curve_only"])
        self.assertLess(result["features"]["mf_curve_real_token_capacity_ratio_0_10_sol"], 1.0)


if __name__ == "__main__":
    unittest.main()
