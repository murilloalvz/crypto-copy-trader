import unittest

from src.wallet_forward_finality import summarize_wallet_forward_finality


class WalletForwardFinalityTests(unittest.TestCase):
    def test_summary_keeps_non_finalized_and_missing_visible(self):
        summary = summarize_wallet_forward_finality(
            [
                {"confirmationStatus": "finalized", "err": None},
                {"confirmationStatus": "finalized", "err": {"InstructionError": [0, "x"]}},
                {"confirmationStatus": "confirmed", "err": None},
                {"confirmationStatus": "processed", "err": None},
                None,
                {"confirmationStatus": None, "err": None},
            ]
        )

        self.assertEqual(summary.signature_count, 6)
        self.assertEqual(summary.finalized_success_count, 1)
        self.assertEqual(summary.finalized_error_count, 1)
        self.assertEqual(summary.confirmed_count, 1)
        self.assertEqual(summary.processed_count, 1)
        self.assertEqual(summary.missing_count, 1)
        self.assertEqual(summary.unknown_status_count, 1)
        self.assertAlmostEqual(summary.finalized_share_pct, 100.0 * 2 / 6)

    def test_empty_summary_is_valid(self):
        summary = summarize_wallet_forward_finality([])
        self.assertEqual(summary.signature_count, 0)
        self.assertEqual(summary.finalized_share_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
