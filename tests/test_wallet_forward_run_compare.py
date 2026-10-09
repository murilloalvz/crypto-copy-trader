import unittest

from src.wallet_forward_run_compare import compare_wallet_forward_run_regimes
from src.wallet_forward_runs import WalletForwardRun


def _run(
    key: str,
    *,
    runtime: str = "wallet_forward_runtime_v2_causal_boundary",
    cohort: tuple[str, ...] = ("A", "B"),
    interval: int = 30,
    delays: tuple[int, ...] = (0, 15, 30, 60, 120),
    mode: str = "proxy",
    grace: int = 35,
) -> WalletForwardRun:
    return WalletForwardRun(
        run_key=key,
        started_at=100,
        ended_at=200,
        baseline_observation_id=0,
        end_observation_id=1,
        cohort=cohort,
        interval_seconds=interval,
        quote_delays_seconds=delays,
        with_jupiter_quotes=mode != "none",
        copy_size_usd=25.0,
        quote_mode=mode,
        status="COMPLETED",
        runtime_version=runtime,
        quote_intake_grace_seconds=grace,
        enrollment_ends_at=None,
        follow_up_ends_at=None,
        enrollment_cutoff_observation_id=None,
    )


class WalletForwardRunCompareTests(unittest.TestCase):
    def test_same_regime_still_does_not_auto_pool(self):
        summary = compare_wallet_forward_run_regimes([_run("a"), _run("b")])

        self.assertEqual(summary.label, "SAME_TECHNICAL_REGIME_COMPARE_SEPARATELY")
        self.assertEqual(summary.differing_fields, ())
        self.assertFalse(summary.pooling_allowed_automatically)

    def test_runtime_version_difference_blocks_regime_equivalence(self):
        summary = compare_wallet_forward_run_regimes(
            [
                _run("legacy", runtime="wallet_forward_runtime_v1_unversioned", grace=0),
                _run("v2"),
            ]
        )

        self.assertEqual(summary.label, "MIXED_TECHNICAL_REGIME_DO_NOT_POOL")
        self.assertIn("runtime_version", summary.differing_fields)
        self.assertIn("quote_intake_grace_seconds", summary.differing_fields)
        self.assertFalse(summary.pooling_allowed_automatically)

    def test_cohort_order_is_part_of_sequential_polling_regime(self):
        summary = compare_wallet_forward_run_regimes(
            [_run("a", cohort=("A", "B")), _run("b", cohort=("B", "A"))]
        )

        self.assertEqual(summary.label, "MIXED_TECHNICAL_REGIME_DO_NOT_POOL")
        self.assertIn("cohort", summary.differing_fields)

    def test_single_and_empty_inputs_are_explicit(self):
        single = compare_wallet_forward_run_regimes([_run("a")])
        empty = compare_wallet_forward_run_regimes([])

        self.assertEqual(single.label, "SINGLE_RUN")
        self.assertEqual(empty.label, "NO_RUNS")
        self.assertIsNone(empty.reference_run_key)

    def test_duplicate_manifest_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_wallet_forward_run_regimes([_run("same"), _run("same")])


if __name__ == "__main__":
    unittest.main()
