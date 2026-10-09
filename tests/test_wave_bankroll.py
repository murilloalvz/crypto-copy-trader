import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database
from src.wave_bankroll import (
    WaveTradeReturn,
    completed_wave_returns,
    simulate_bankroll,
)
from src.wave_paper import WAVE_STRATEGY_VERSION


class WaveBankrollTests(unittest.TestCase):
    def test_reinvests_fraction_of_current_balance_and_tracks_risk(self):
        simulation = simulate_bankroll(
            [
                WaveTradeReturn(1000, "WIN", 10),
                WaveTradeReturn(1001, "LOSS-1", -20),
                WaveTradeReturn(1002, "LOSS-2", -5),
                WaveTradeReturn(1003, "WIN-2", 10),
            ],
            starting_balance_usd=100,
            allocation_pct=30,
        )

        self.assertAlmostEqual(simulation.points[0].stake_usd, 30)
        self.assertAlmostEqual(simulation.points[0].balance_usd, 103)
        self.assertAlmostEqual(simulation.points[1].stake_usd, 30.9)
        self.assertAlmostEqual(simulation.final_balance_usd, 98.228731)
        self.assertAlmostEqual(simulation.total_profit_usd, -1.771269)
        self.assertAlmostEqual(simulation.max_drawdown_usd, 7.6323)
        self.assertAlmostEqual(simulation.max_drawdown_pct, 7.409999, places=5)
        self.assertEqual(simulation.max_losing_streak, 2)

    def test_reads_only_completed_strategy_horizon_in_chronological_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bankroll.db"
            with patch.object(
                database, "settings", SimpleNamespace(database_path=path)
            ):
                initialize_database()
                with database.connection() as conn:
                    signal_ids = []
                    for mint, detected_at, strategy in (
                        ("later", 2000, WAVE_STRATEGY_VERSION),
                        ("earlier", 1000, WAVE_STRATEGY_VERSION),
                        ("legacy", 500, "wave_v1_baseline"),
                    ):
                        signal_ids.append(
                            conn.execute(
                                """INSERT INTO wave_signals
                                (token_mint, symbol, detected_at, wave_score,
                                entry_market_price_usd, entry_execution_price_usd,
                                copy_size_usd, slippage_bps, strategy_version,
                                snapshot_json)
                                VALUES (?, ?, ?, 60, 1, 1.01, 25, 100, ?, '{}')""",
                                (mint, mint, detected_at, strategy),
                            ).lastrowid
                        )
                    conn.executemany(
                        """INSERT INTO wave_signal_checks
                        (signal_id, horizon_minutes, target_at, return_pct, status)
                        VALUES (?, ?, 3000, ?, ?)""",
                        [
                            (signal_ids[0], 5, 2, "completed"),
                            (signal_ids[1], 5, 1, "completed"),
                            (signal_ids[1], 15, 99, "completed"),
                            (signal_ids[2], 5, 88, "completed"),
                        ],
                    )

                observations = completed_wave_returns(WAVE_STRATEGY_VERSION, 5)

        self.assertEqual([item.symbol for item in observations], ["earlier", "later"])
        self.assertEqual([item.return_pct for item in observations], [1, 2])

    def test_rejects_invalid_capital_parameters(self):
        with self.assertRaises(ValueError):
            simulate_bankroll([], starting_balance_usd=0, allocation_pct=30)
        with self.assertRaises(ValueError):
            simulate_bankroll([], starting_balance_usd=100, allocation_pct=101)


if __name__ == "__main__":
    unittest.main()
