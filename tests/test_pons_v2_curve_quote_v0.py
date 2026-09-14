import unittest

from src.pons_v2_curve_quote_v0 import (
    PonsCurveQuoteStateV0,
    SNIPE_MODE_LIVE_VIEW,
    SNIPE_MODE_PROVEN_ABSENT,
    STATUS_CURVE_CLOSED,
    STATUS_OK,
    STATUS_QUOTE_TOO_SMALL,
    STATUS_SELL_CLOSED_READY_TO_GRADUATE,
    amount_in_v0,
    amount_out_v0,
    quote_buy_v0,
    quote_sell_v0,
)


def state(**overrides):
    values = {
        "quote_reserve_raw": 1_000_000,
        "token_reserve_raw": 2_000_000,
        "sellable_tokens_raw": 1_000_000,
        "fee_bps": 100,
        "creator_tax_bps": 50,
        "snipe_mode": SNIPE_MODE_PROVEN_ABSENT,
        "current_snipe_tax_bps": 0,
        "ready_to_graduate": False,
        "graduated": False,
        "observed_at_ns": 123,
        "protocol_generation_key": "pons_v2:test:base_curve_no_snipe_view",
        "provenance": ("unit-test",),
    }
    values.update(overrides)
    return PonsCurveQuoteStateV0(**values)


class PonsV2CurveQuoteMathV0Tests(unittest.TestCase):
    def test_constant_product_integer_rounding_matches_reference_formula(self):
        self.assertEqual(amount_out_v0(100, 1000, 1000), 90)
        self.assertEqual(amount_in_v0(90, 1000, 1000), 99)

    def test_live_snipe_buy_applies_fee_tax_and_recipient_specific_snipe(self):
        quote = quote_buy_v0(
            state=state(
                snipe_mode=SNIPE_MODE_LIVE_VIEW,
                current_snipe_tax_bps=5_000,
                protocol_generation_key="pons_v2:test:snipe_view",
            ),
            quote_in_raw=10_000,
        )
        self.assertEqual(quote.status, STATUS_OK)
        self.assertEqual(quote.fee_raw, 100)
        self.assertEqual(quote.creator_tax_raw, 50)
        self.assertEqual(quote.snipe_tax_raw, 5_000)
        self.assertEqual(quote.net_curve_input_raw, 4_850)
        self.assertEqual(quote.tokens_out_raw, 9_653)
        self.assertEqual(quote.refund_quote_raw, 0)
        self.assertFalse(quote.partial_fill)
        self.assertTrue(quote.mathematically_quotable)
        self.assertFalse(quote.fill_claimed)

    def test_snipe_tax_is_capped_to_leave_documented_one_percent_net_floor(self):
        guarded = state(
            fee_bps=1_000,
            creator_tax_bps=1_000,
            snipe_mode=SNIPE_MODE_LIVE_VIEW,
            current_snipe_tax_bps=9_900,
            protocol_generation_key="pons_v2:test:snipe_view",
        )
        self.assertEqual(guarded.applied_snipe_tax_bps, 7_900)
        quote = quote_buy_v0(state=guarded, quote_in_raw=10_000)
        self.assertEqual(quote.fee_raw, 1_000)
        self.assertEqual(quote.creator_tax_raw, 1_000)
        self.assertEqual(quote.snipe_tax_raw, 7_900)
        self.assertEqual(quote.net_curve_input_raw, 100)

    def test_live_snipe_generation_refuses_missing_recipient_state(self):
        with self.assertRaises(ValueError):
            state(
                snipe_mode=SNIPE_MODE_LIVE_VIEW,
                current_snipe_tax_bps=None,
                protocol_generation_key="pons_v2:test:snipe_view",
            )

    def test_proven_no_snipe_generation_refuses_hidden_nonzero_snipe(self):
        with self.assertRaises(ValueError):
            state(
                snipe_mode=SNIPE_MODE_PROVEN_ABSENT,
                current_snipe_tax_bps=1,
            )

    def test_partial_buy_reprices_from_token_side_and_refunds_remainder(self):
        quote = quote_buy_v0(
            state=state(
                quote_reserve_raw=1_000,
                token_reserve_raw=1_000,
                sellable_tokens_raw=100,
                fee_bps=100,
                creator_tax_bps=100,
            ),
            quote_in_raw=1_000,
        )
        self.assertEqual(quote.status, STATUS_OK)
        self.assertTrue(quote.partial_fill)
        self.assertEqual(quote.tokens_out_raw, 100)
        self.assertEqual(quote.spent_quote_raw, 115)
        self.assertEqual(quote.refund_quote_raw, 885)
        self.assertEqual(quote.fee_raw, 1)
        self.assertEqual(quote.creator_tax_raw, 1)
        self.assertEqual(quote.net_curve_input_raw, 113)
        self.assertTrue(quote.mathematically_quotable)
        self.assertFalse(quote.fill_claimed)

    def test_sell_matches_quote_leg_fee_order_and_has_no_snipe(self):
        quote = quote_sell_v0(
            state=state(
                token_reserve_raw=1_000_000,
                quote_reserve_raw=1_000_000,
                sellable_tokens_raw=500_000,
                fee_bps=100,
                creator_tax_bps=50,
                snipe_mode=SNIPE_MODE_LIVE_VIEW,
                current_snipe_tax_bps=7_000,
                protocol_generation_key="pons_v2:test:snipe_view",
            ),
            tokens_in_raw=100_000,
        )
        self.assertEqual(quote.status, STATUS_OK)
        self.assertEqual(quote.gross_quote_out_raw, 90_909)
        self.assertEqual(quote.fee_raw, 909)
        self.assertEqual(quote.creator_tax_raw, 454)
        self.assertEqual(quote.quote_out_raw, 89_546)
        self.assertTrue(quote.mathematically_quotable)
        self.assertFalse(quote.fill_claimed)

    def test_sell_is_closed_before_graduated_flag_when_ready_to_graduate(self):
        quote = quote_sell_v0(
            state=state(ready_to_graduate=True, graduated=False),
            tokens_in_raw=100,
        )
        self.assertEqual(quote.status, STATUS_SELL_CLOSED_READY_TO_GRADUATE)
        self.assertFalse(quote.mathematically_quotable)

    def test_graduated_curve_closes_buy_and_sell(self):
        closed = state(graduated=True, ready_to_graduate=False)
        buy = quote_buy_v0(state=closed, quote_in_raw=100)
        sell = quote_sell_v0(state=closed, tokens_in_raw=100)
        self.assertEqual(buy.status, STATUS_CURVE_CLOSED)
        self.assertEqual(sell.status, STATUS_CURVE_CLOSED)
        self.assertFalse(buy.fill_claimed)
        self.assertFalse(sell.fill_claimed)

    def test_integer_zero_output_is_not_claimed_quotable(self):
        tiny = state(
            quote_reserve_raw=1_000_000,
            token_reserve_raw=1,
            sellable_tokens_raw=1,
            fee_bps=0,
            creator_tax_bps=0,
        )
        quote = quote_buy_v0(state=tiny, quote_in_raw=1)
        self.assertEqual(quote.status, STATUS_QUOTE_TOO_SMALL)
        self.assertEqual(quote.tokens_out_raw, 0)
        self.assertFalse(quote.mathematically_quotable)
        self.assertFalse(quote.fill_claimed)


if __name__ == "__main__":
    unittest.main()
