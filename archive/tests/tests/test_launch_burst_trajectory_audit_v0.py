import unittest
from unittest.mock import patch

from benchmarks.launch_burst_trajectory_audit_v0.run import run_trajectory_audit


def _snap(key, events, buys, sells, wallets, txs):
    return {
        "anchor_event_key": key,
        "stratum": "pump_launch",
        "event_count": events,
        "buy_count": buys,
        "sell_count": sells,
        "count_buy_share_pct": (100.0 * buys / events) if events else None,
        "unique_wallet_count": wallets,
        "unique_transaction_count": txs,
    }


class LaunchBurstTrajectoryAuditV0Tests(unittest.TestCase):
    def test_pairs_same_anchor_and_keeps_outcomes_blind(self):
        data = {
            ("A", 5): [_snap("a", 2, 2, 0, 1, 2)],
            ("A", 10): [_snap("a", 4, 3, 1, 2, 4)],
            ("A", 30): [_snap("a", 5, 4, 1, 3, 5)],
            ("B", 5): [_snap("b", 1, 1, 0, 1, 1)],
            ("B", 10): [_snap("b", 3, 2, 1, 2, 3)],
            ("B", 30): [_snap("b", 6, 4, 2, 3, 6)],
        }

        def replay(*, acquisition_run_key, window_seconds):
            label = "A" if acquisition_run_key == "run-a" else "B"
            return {"snapshots": data[(label, window_seconds)]}

        with patch(
            "benchmarks.launch_burst_trajectory_audit_v0.run.run_replay",
            side_effect=replay,
        ):
            report = run_trajectory_audit(
                run_a="run-a", run_b="run-b", windows_seconds=(5, 10, 30)
            )

        self.assertEqual(report["monotonicity_violation_count"], 0)
        a = report["cohorts"]["A"]["transitions"]["5->10"]["pump_launch"]
        self.assertEqual(a["paired_launch_count"], 1)
        self.assertEqual(a["features"]["new_events"]["p50"], 2.0)
        self.assertTrue(report["scientific_lock"]["outcome_blind"])
        self.assertFalse(report["scientific_lock"]["future_outcomes_loaded"])

    def test_detects_non_monotonic_cumulative_counts(self):
        data = {
            ("A", 5): [_snap("a", 3, 2, 1, 2, 3)],
            ("A", 10): [_snap("a", 2, 2, 0, 1, 2)],
            ("B", 5): [_snap("b", 1, 1, 0, 1, 1)],
            ("B", 10): [_snap("b", 2, 2, 0, 1, 2)],
        }

        def replay(*, acquisition_run_key, window_seconds):
            label = "A" if acquisition_run_key == "run-a" else "B"
            return {"snapshots": data[(label, window_seconds)]}

        with patch(
            "benchmarks.launch_burst_trajectory_audit_v0.run.run_replay",
            side_effect=replay,
        ):
            report = run_trajectory_audit(
                run_a="run-a", run_b="run-b", windows_seconds=(5, 10)
            )

        self.assertGreater(report["monotonicity_violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
