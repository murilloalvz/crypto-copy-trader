import unittest

from src.solana_tracker_structural_risk_v0 import (
    SOLANA_TRACKER_SOURCE,
    adapt_solana_tracker_token_info_v0,
)


class SolanaTrackerStructuralRiskV0Tests(unittest.TestCase):
    def test_maps_only_documented_token_info_fields(self):
        payload = {
            "token": {
                "mint": "MINT",
                "creation": {"creator": "CREATOR"},
            },
            "risk": {
                "top10": 41.5,
                "dev": {"percentage": 7.0},
                "snipers": {"totalPercentage": 3.25},
                "insiders": {"totalPercentage": 5.5},
                "bundlers": {"totalPercentage": 2.0},
                "rugged": False,
                "score": 1,
            },
            "holders": 321,
        }
        row = adapt_solana_tracker_token_info_v0(
            payload,
            token_mint="MINT",
            observed_at=100,
            evidence_key="st:token:MINT:100",
        )
        self.assertEqual(row.source, SOLANA_TRACKER_SOURCE)
        self.assertEqual(row.holder_count, 321)
        self.assertEqual(row.top10_holder_pct, 41.5)
        self.assertEqual(row.dev_holder_pct, 7.0)
        self.assertEqual(row.sniper_holder_pct, 3.25)
        self.assertEqual(row.insider_holder_pct, 5.5)
        self.assertEqual(row.bundler_holder_pct, 2.0)
        self.assertEqual(row.creator_wallet, "CREATOR")
        self.assertIsNone(row.provider_honeypot_flag)

    def test_omitted_bundlers_remains_unknown_not_zero(self):
        payload = {
            "token": {"mint": "MINT"},
            "risk": {
                "top10": 20.0,
                "snipers": {"totalPercentage": 1.0},
                "insiders": {"totalPercentage": 2.0},
            },
            "holders": 20,
        }
        row = adapt_solana_tracker_token_info_v0(
            payload,
            token_mint="MINT",
            observed_at=10,
            evidence_key="e",
        )
        self.assertIsNone(row.bundler_holder_pct)

    def test_payload_mint_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            adapt_solana_tracker_token_info_v0(
                {"token": {"mint": "OTHER"}},
                token_mint="MINT",
                observed_at=1,
                evidence_key="e",
            )

    def test_non_numeric_fields_remain_unknown_and_validation_stays_downstream(self):
        row = adapt_solana_tracker_token_info_v0(
            {
                "token": {"mint": "MINT"},
                "risk": {
                    "top10": "unknown",
                    "dev": {"percentage": None},
                },
                "holders": "123",
            },
            token_mint="MINT",
            observed_at=1,
            evidence_key="e",
        )
        self.assertIsNone(row.holder_count)
        self.assertIsNone(row.top10_holder_pct)
        self.assertIsNone(row.dev_holder_pct)


if __name__ == "__main__":
    unittest.main()
