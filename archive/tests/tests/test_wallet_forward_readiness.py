import unittest

from src.wallet_forward_readiness import summarize_wallet_forward_replay_readiness


class WalletForwardReplayReadinessTests(unittest.TestCase):
    def test_complete_structural_path_is_ready_only_for_descriptive_replay(self):
        summary = summarize_wallet_forward_replay_readiness(
            run_status="COMPLETED",
            runtime_version="wallet_forward_runtime_v2_causal_boundary",
            quote_mode="proxy",
            with_jupiter_quotes=True,
            integrity_label="CAUSAL_BOUNDARY_CLEAN",
            action_count=4,
            buy_event_count=2,
            successful_quote_event_count=2,
            expected_attempt_count=10,
            attempted_expected_count=10,
            successful_attempt_count=10,
            failed_attempt_count=0,
            missing_attempt_count=0,
            unexpected_attempt_count=0,
        )

        self.assertEqual(summary.label, "CAUSAL_REPLAY_SAMPLE_READY")
        self.assertTrue(summary.descriptive_replay_allowed)
        self.assertFalse(summary.economic_promotion_allowed)
        self.assertIn("quote_only_proxy_not_execution", summary.cautions)
        self.assertEqual(summary.attempt_coverage_pct, 100.0)
        self.assertEqual(summary.successful_quote_event_share_pct, 100.0)

    def test_missing_probe_keeps_sample_partial_without_hiding_replayable_quotes(self):
        summary = summarize_wallet_forward_replay_readiness(
            run_status="COMPLETED",
            runtime_version="wallet_forward_runtime_v2_causal_boundary",
            quote_mode="proxy",
            with_jupiter_quotes=True,
            integrity_label="CAUSAL_BOUNDARY_CLEAN",
            action_count=3,
            buy_event_count=2,
            successful_quote_event_count=2,
            expected_attempt_count=10,
            attempted_expected_count=9,
            successful_attempt_count=8,
            failed_attempt_count=1,
            missing_attempt_count=1,
            unexpected_attempt_count=0,
        )

        self.assertEqual(summary.label, "PARTIAL_CAUSAL_REPLAY_SAMPLE")
        self.assertTrue(summary.descriptive_replay_allowed)
        self.assertIn("missing_quote_probes", summary.cautions)
        self.assertIn("quote_provider_failures", summary.cautions)
        self.assertFalse(summary.economic_promotion_allowed)

    def test_causality_failure_blocks_replay_even_when_quotes_exist(self):
        summary = summarize_wallet_forward_replay_readiness(
            run_status="COMPLETED",
            runtime_version="wallet_forward_runtime_v1_unversioned",
            quote_mode="proxy",
            with_jupiter_quotes=True,
            integrity_label="CAUSAL_BOUNDARY_FAILED",
            action_count=2,
            buy_event_count=1,
            successful_quote_event_count=1,
            expected_attempt_count=5,
            attempted_expected_count=5,
            successful_attempt_count=5,
            failed_attempt_count=0,
            missing_attempt_count=0,
            unexpected_attempt_count=0,
        )

        self.assertEqual(summary.label, "DATA_QUALITY_BLOCKED")
        self.assertFalse(summary.descriptive_replay_allowed)
        self.assertIn("integrity:causal_boundary_failed", summary.blockers)
        self.assertIn("legacy_runtime_requires_integrity_audit", summary.cautions)

    def test_no_buy_sample_requests_more_collection(self):
        summary = summarize_wallet_forward_replay_readiness(
            run_status="COMPLETED",
            runtime_version="wallet_forward_runtime_v2_causal_boundary",
            quote_mode="proxy",
            with_jupiter_quotes=True,
            integrity_label="CAUSAL_BOUNDARY_CLEAN",
            action_count=2,
            buy_event_count=0,
            successful_quote_event_count=0,
            expected_attempt_count=0,
            attempted_expected_count=0,
            successful_attempt_count=0,
            failed_attempt_count=0,
            missing_attempt_count=0,
            unexpected_attempt_count=0,
        )

        self.assertEqual(summary.label, "NO_CAUSAL_SAMPLE")
        self.assertFalse(summary.descriptive_replay_allowed)
        self.assertIn("no_forward_buys", summary.blockers)

    def test_unexpected_probe_cannot_upgrade_readiness(self):
        summary = summarize_wallet_forward_replay_readiness(
            run_status="COMPLETED",
            runtime_version="wallet_forward_runtime_v2_causal_boundary",
            quote_mode="proxy",
            with_jupiter_quotes=True,
            integrity_label="CAUSAL_BOUNDARY_CLEAN",
            action_count=1,
            buy_event_count=1,
            successful_quote_event_count=1,
            expected_attempt_count=5,
            attempted_expected_count=5,
            successful_attempt_count=5,
            failed_attempt_count=0,
            missing_attempt_count=0,
            unexpected_attempt_count=1,
        )

        self.assertEqual(summary.label, "PARTIAL_CAUSAL_REPLAY_SAMPLE")
        self.assertIn("unexpected_quote_attempts", summary.cautions)

    def test_invalid_reconciliation_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize_wallet_forward_replay_readiness(
                run_status="COMPLETED",
                runtime_version="runtime",
                quote_mode="proxy",
                with_jupiter_quotes=True,
                integrity_label="CAUSAL_BOUNDARY_CLEAN",
                action_count=1,
                buy_event_count=1,
                successful_quote_event_count=1,
                expected_attempt_count=5,
                attempted_expected_count=4,
                successful_attempt_count=4,
                failed_attempt_count=0,
                missing_attempt_count=0,
                unexpected_attempt_count=0,
            )


if __name__ == "__main__":
    unittest.main()
