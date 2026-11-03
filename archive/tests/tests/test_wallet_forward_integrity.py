import unittest

from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_integrity import summarize_forward_run_integrity


class WalletForwardIntegrityTests(unittest.TestCase):
    def test_clean_forward_actions_pass_boundary_audit(self):
        summary = summarize_forward_run_integrity(
            [
                WalletActionObservation("A", "T", "buy", 110, 120),
                WalletActionObservation("B", "T", "buy", 130, 150),
            ],
            run_started_at=100,
        )

        self.assertEqual(summary.integrity_label, "CAUSAL_BOUNDARY_CLEAN")
        self.assertEqual(summary.chain_before_run_count, 0)
        self.assertEqual(summary.source_lag_over_300s_count, 0)

    def test_small_prestart_chain_timestamp_is_visible_but_not_silently_failed(self):
        summary = summarize_forward_run_integrity(
            [WalletActionObservation("A", "T", "buy", 99, 105)],
            run_started_at=100,
        )

        self.assertEqual(summary.chain_before_run_count, 1)
        self.assertEqual(summary.integrity_label, "PRESTART_CHAIN_CAUTION")

    def test_stale_historical_backfill_is_flagged_critical(self):
        summary = summarize_forward_run_integrity(
            [WalletActionObservation("A", "T", "buy", 100, 5000)],
            run_started_at=4000,
        )

        self.assertEqual(summary.chain_before_run_count, 1)
        self.assertEqual(summary.source_lag_over_3600s_count, 1)
        self.assertEqual(summary.integrity_label, "STALE_SOURCE_CRITICAL")

    def test_observation_before_manifest_start_fails_boundary(self):
        summary = summarize_forward_run_integrity(
            [WalletActionObservation("A", "T", "buy", 90, 95)],
            run_started_at=100,
        )

        self.assertEqual(summary.observed_before_run_count, 1)
        self.assertEqual(summary.integrity_label, "CAUSAL_BOUNDARY_FAILED")

    def test_negative_source_lag_fails_even_if_input_dataclass_allows_construction(self):
        summary = summarize_forward_run_integrity(
            [WalletActionObservation("A", "T", "buy", 110, 109)],
            run_started_at=100,
        )

        self.assertEqual(summary.negative_source_lag_count, 1)
        self.assertEqual(summary.integrity_label, "CAUSAL_BOUNDARY_FAILED")


if __name__ == "__main__":
    unittest.main()
