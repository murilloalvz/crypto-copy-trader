import unittest

from src.pumpswap_asset_role import (
    USDC_MINT,
    WSOL_MINT,
    classify_pumpswap_opportunity_asset,
)


class PumpSwapAssetRoleTests(unittest.TestCase):
    def test_standard_token_base_preserves_side(self):
        role = classify_pumpswap_opportunity_asset(base_mint="TOKEN", quote_mint=WSOL_MINT)
        self.assertIsNotNone(role)
        assert role is not None
        self.assertEqual(role.opportunity_mint, "TOKEN")
        self.assertTrue(role.opportunity_is_base)
        self.assertEqual(role.normalize_event_side("buy"), "buy")
        self.assertEqual(role.normalize_event_side("sell"), "sell")

    def test_reversed_wsol_base_uses_quote_token_and_inverts_side(self):
        role = classify_pumpswap_opportunity_asset(base_mint=WSOL_MINT, quote_mint="TOKEN")
        self.assertIsNotNone(role)
        assert role is not None
        self.assertEqual(role.opportunity_mint, "TOKEN")
        self.assertFalse(role.opportunity_is_base)
        self.assertEqual(role.normalize_event_side("buy"), "sell")
        self.assertEqual(role.normalize_event_side("sell"), "buy")

    def test_usdc_is_reference_asset(self):
        role = classify_pumpswap_opportunity_asset(base_mint="TOKEN", quote_mint=USDC_MINT)
        self.assertIsNotNone(role)
        assert role is not None
        self.assertEqual(role.opportunity_mint, "TOKEN")

    def test_ambiguous_pairs_are_not_guessed(self):
        self.assertIsNone(
            classify_pumpswap_opportunity_asset(base_mint="TOKEN-A", quote_mint="TOKEN-B")
        )
        self.assertIsNone(
            classify_pumpswap_opportunity_asset(base_mint=WSOL_MINT, quote_mint=USDC_MINT)
        )


if __name__ == "__main__":
    unittest.main()
