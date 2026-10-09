import unittest

from src.wallet_forward_run_compare import compare_wallet_forward_run_regimes
from src.wallet_forward_runs import WalletForwardRun
from wallet_forward_experiment import _runtime_version


def _run(
    key: str,
    *,
    started_at: int = 100,
    enrollment_seconds: int | None = 900,
    follow_up_seconds: int | None = 900,
) -> WalletForwardRun:
    enrollment_aware = enrollment_seconds is not None
    if enrollment_aware != (follow_up_seconds is not None):
        raise ValueError("test helper requires both protocol durations or neither")
    enrollment_ends_at = (
        started_at + int(enrollment_seconds)
        if enrollment_seconds is not None
        else None
    )
    follow_up_ends_at = (
        enrollment_ends_at + int(follow_up_seconds)
        if enrollment_ends_at is not None and follow_up_seconds is not None
        else None
    )
    return WalletForwardRun(
        run_key=key,
        started_at=started_at,
        ended_at=follow_up_ends_at if follow_up_ends_at is not None else started_at + 1800,
        baseline_observation_id=0,
        end_observation_id=1,
        cohort=("A", "B"),
        interval_seconds=10,
        quote_delays_seconds=(0, 15, 30, 60, 120),
        with_jupiter_quotes=True,
        copy_size_usd=25.0,
        quote_mode="proxy",
        status="COMPLETED",
        runtime_version=_runtime_version("confirmed", enrollment_aware=enrollment_aware),
        quote_intake_grace_seconds=15,
        enrollment_ends_at=enrollment_ends_at,
        follow_up_ends_at=follow_up_ends_at,
        enrollment_cutoff_observation_id=1 if enrollment_aware else None,
    )


class WalletForwardRuntimeProtocolTests(unittest.TestCase):
    def test_legacy_duration_mode_keeps_v4_runtime(self):
        self.assertEqual(
            _runtime_version("confirmed", enrollment_aware=False),
            "wallet_forward_runtime_v4_rotating_poll_confirmed_commitment",
        )

    def test_enrollment_protocol_gets_distinct_v5_runtime(self):
        self.assertEqual(
            _runtime_version("confirmed", enrollment_aware=True),
            "wallet_forward_runtime_v5_enrollment_followup_rotating_poll_confirmed_commitment",
        )

    def test_protocol_duration_difference_blocks_regime_equivalence(self):
        summary = compare_wallet_forward_run_regimes(
            [
                _run("a", enrollment_seconds=900, follow_up_seconds=900),
                _run("b", enrollment_seconds=1200, follow_up_seconds=600),
            ]
        )

        self.assertEqual(summary.label, "MIXED_TECHNICAL_REGIME_DO_NOT_POOL")
        self.assertIn("enrollment_duration_seconds", summary.differing_fields)
        self.assertIn("follow_up_duration_seconds", summary.differing_fields)

    def test_same_protocol_different_calendar_time_is_comparable(self):
        summary = compare_wallet_forward_run_regimes(
            [
                _run("a", started_at=100),
                _run("b", started_at=10_000),
            ]
        )

        self.assertEqual(summary.label, "SAME_TECHNICAL_REGIME_COMPARE_SEPARATELY")
        self.assertEqual(summary.differing_fields, ())
        self.assertFalse(summary.pooling_allowed_automatically)


if __name__ == "__main__":
    unittest.main()
