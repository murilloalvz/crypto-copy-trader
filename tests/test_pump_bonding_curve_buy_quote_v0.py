import unittest

from src.pump_bonding_curve_buy_quote_v0 import (
    PumpBondingCurveStateV0,
    PumpFeeBpsV0,
    STATUS_CURVE_COMPLETE,
    STATUS_OK,
    STATUS_REAL_TOKEN_RESERVE_LIMIT,
    quote_buy_desired_tokens_v0,
    quote_buy_exact_quote_in_v0,
)


class PumpBondingCurveBuyQuoteV0Tests(unittest.TestCase):
    def setUp(self):
        # Reserve fixture from Pump public docs PUMP_PROGRAM_README.md.
        self.state = PumpBondingCurveStateV0(
            virtual_token_reserves_raw=1_072_999_999_992_855,
            virtual_quote_reserves_raw=30_000_000_013,
            real_token_reserves_raw=793_099_999_992_855,
            complete=False,
        )
        # Fee rates are explicit quote inputs; this fixture tests integer math rather
        # than assuming the current live tier for the documented reserve snapshot.
        self.fees = PumpFeeBpsV0(protocol_fee_bps=100, creator_fee_bps=25)

    def test_exact_quote_in_matches_documented_integer_sequence(self):
        quote = quote_buy_exact_quote_in_v0(
            state=self.state,
            fee_bps=self.fees,
            spendable_quote_raw=1_000_000_000,
        )
        self.assertEqual(quote.status, STATUS_OK)
        self.assertEqual(quote.net_quote_raw, 987_654_320)
        self.assertEqual(quote.protocol_fee_raw, 9_876_544)
        self.assertEqual(quote.creator_fee_raw, 2_469_136)
        self.assertEqual(quote.total_fee_raw, 12_345_680)
        self.assertEqual(quote.curve_tokens_out_raw, 34_199_203_106_043)
        self.assertTrue(quote.fits_real_token_reserves)
        self.assertTrue(quote.executable_amount_claimed)
        self.assertLessEqual(
            quote.net_quote_raw + quote.total_fee_raw,
            quote.spendable_quote_raw,
        )

    def test_reverse_quote_matches_documented_ceil_formula(self):
        quote = quote_buy_desired_tokens_v0(
            state=self.state,
            fee_bps=self.fees,
            desired_tokens_raw=10_000_000_000,
        )
        self.assertEqual(quote.status, STATUS_OK)
        self.assertEqual(quote.net_quote_raw, 279_594)
        self.assertEqual(quote.documented_spendable_quote_raw, 283_089)
        self.assertEqual(quote.protocol_fee_raw, 2_796)
        self.assertEqual(quote.creator_fee_raw, 699)
        self.assertEqual(quote.computed_total_quote_raw, 283_089)
        self.assertTrue(quote.executable_amount_claimed)

    def test_reverse_quote_exposes_split_fee_rounding_gap_and_safe_total_roundtrips(self):
        desired = 123_456_789_000
        reverse = quote_buy_desired_tokens_v0(
            state=self.state,
            fee_bps=self.fees,
            desired_tokens_raw=desired,
        )
        self.assertEqual(reverse.status, STATUS_OK)

        # Pump's documented reverse formula applies total_fee_bps in one ceil. The
        # forward path separately ceils protocol and creator fees, so their sum can be
        # one raw quote unit larger. Preserve both numbers instead of hiding the gap.
        self.assertEqual(
            reverse.computed_total_quote_raw - reverse.documented_spendable_quote_raw,
            1,
        )

        documented_forward = quote_buy_exact_quote_in_v0(
            state=self.state,
            fee_bps=self.fees,
            spendable_quote_raw=reverse.documented_spendable_quote_raw,
        )
        self.assertLess(documented_forward.curve_tokens_out_raw, desired)

        fee_exact_forward = quote_buy_exact_quote_in_v0(
            state=self.state,
            fee_bps=self.fees,
            spendable_quote_raw=reverse.computed_total_quote_raw,
        )
        self.assertEqual(fee_exact_forward.status, STATUS_OK)
        self.assertGreaterEqual(fee_exact_forward.curve_tokens_out_raw, desired)

    def test_curve_complete_refuses_buy_quote(self):
        complete = PumpBondingCurveStateV0(
            virtual_token_reserves_raw=100,
            virtual_quote_reserves_raw=100,
            real_token_reserves_raw=0,
            complete=True,
        )
        quote = quote_buy_exact_quote_in_v0(
            state=complete,
            fee_bps=self.fees,
            spendable_quote_raw=1_000,
        )
        self.assertEqual(quote.status, STATUS_CURVE_COMPLETE)
        self.assertFalse(quote.executable_amount_claimed)

    def test_curve_output_beyond_real_reserves_is_not_claimed_executable(self):
        low_real = PumpBondingCurveStateV0(
            virtual_token_reserves_raw=1_000_000,
            virtual_quote_reserves_raw=1_000_000,
            real_token_reserves_raw=10,
            complete=False,
        )
        quote = quote_buy_exact_quote_in_v0(
            state=low_real,
            fee_bps=PumpFeeBpsV0(0, 0),
            spendable_quote_raw=100_000,
        )
        self.assertEqual(quote.status, STATUS_REAL_TOKEN_RESERVE_LIMIT)
        self.assertFalse(quote.fits_real_token_reserves)
        self.assertFalse(quote.executable_amount_claimed)

    def test_fee_rounding_correction_never_exceeds_budget(self):
        quote = quote_buy_exact_quote_in_v0(
            state=self.state,
            fee_bps=PumpFeeBpsV0(protocol_fee_bps=1, creator_fee_bps=1),
            spendable_quote_raw=10_001,
        )
        self.assertLessEqual(
            quote.net_quote_raw + quote.total_fee_raw,
            quote.spendable_quote_raw,
        )

    def test_invalid_fee_or_reserve_state_is_rejected(self):
        with self.assertRaises(ValueError):
            PumpFeeBpsV0(protocol_fee_bps=9_000, creator_fee_bps=2_000)
        with self.assertRaises(ValueError):
            PumpBondingCurveStateV0(
                virtual_token_reserves_raw=0,
                virtual_quote_reserves_raw=1,
                real_token_reserves_raw=0,
                complete=False,
            )


if __name__ == "__main__":
    unittest.main()
