import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database
from src.exit_engine import ensure_exit_experiment
from src.exit_metrics import exit_policy_metrics, paired_closed_signal_count


class ExitMetricsTests(unittest.TestCase):
    def test_reports_policy_metrics_and_paired_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                database,
                "settings",
                SimpleNamespace(database_path=Path(directory) / "metrics.db"),
            ):
                initialize_database()
                experiment = ensure_exit_experiment(activated_at=100)
                with database.connection() as conn:
                    signal_id = conn.execute(
                        """INSERT INTO wave_signals
                        (token_mint, detected_at, wave_score, entry_market_price_usd,
                         entry_execution_price_usd, copy_size_usd, slippage_bps,
                         strategy_version, snapshot_json)
                        VALUES ('x', 101, 70, 1, 1.01, 25, 100,
                                'wave_v3_volume_integrity', '{}')"""
                    ).lastrowid
                    policies = conn.execute(
                        "SELECT id FROM exit_policies WHERE experiment_id=?",
                        (experiment["id"],),
                    ).fetchall()
                    conn.executemany(
                        """INSERT INTO exit_positions
                        (experiment_id, policy_id, signal_id, entry_strategy_version,
                         entry_at, entry_market_price_usd, entry_execution_price_usd,
                         copy_size_usd, slippage_bps, highest_market_price_usd,
                         lowest_market_price_usd, mfe_pct, mae_pct, exit_at,
                         exit_market_price_usd, exit_execution_price_usd,
                         gross_return_pct, net_return_pct, pnl_usd, exit_reason,
                         duration_seconds, status)
                        VALUES (?, ?, ?, 'wave_v3_volume_integrity', 101, 1, 1.01,
                                25, 100, 1.2, .9, 18, -8, 1001, 1.1, 1.089,
                                10, 7.82, 1.955, 'test', 900, 'closed')""",
                        [(experiment["id"], policy["id"], signal_id) for policy in policies],
                    )

                metrics = exit_policy_metrics(experiment["id"])
                paired = paired_closed_signal_count(experiment["id"])

        self.assertEqual(len(metrics), 5)
        self.assertEqual(paired, 1)
        self.assertEqual(metrics[0].closed, 1)
        self.assertAlmostEqual(metrics[0].mean_return_pct, 7.82)


if __name__ == "__main__":
    unittest.main()
