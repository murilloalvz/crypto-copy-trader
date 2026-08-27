import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backtest_concurrent import format_report
from src import database
from src.database import initialize_database
from src.wave_bankroll import (
    WaveTradeObservation,
    completed_wave_observations,
    simulate_concurrent_bankroll,
)
from src.wave_paper import WAVE_STRATEGY_VERSION


def observation(
    signal_id: int,
    detected_at: int,
    close_at: int,
    score: float,
    return_pct: float,
    *,
    symbol: str | None = None,
    liquidity: float | None = 100_000,
) -> WaveTradeObservation:
    return WaveTradeObservation(
        signal_id=signal_id,
        detected_at=detected_at,
        close_at=close_at,
        observed_at=close_at + 10,
        token_mint=f"mint-{signal_id}",
        symbol=symbol or f"T{signal_id}",
        wave_score=score,
        return_pct=return_pct,
        entry_market_price_usd=1,
        entry_execution_price_usd=1.01,
        exit_market_price_usd=1,
        exit_execution_price_usd=0.99,
        slippage_bps=100,
        liquidity_usd=liquidity,
    )


class ConcurrentWaveBankrollTests(unittest.TestCase):
    def test_prioritizes_wave_score_and_skips_unfunded_signal(self):
        simulation = simulate_concurrent_bankroll(
            [
                observation(1, 1000, 1300, 70, 100),
                observation(2, 1000, 1300, 90, 10),
                observation(3, 1000, 1300, 80, -10),
            ],
            scenario_name="AGRESSIVO",
            starting_balance_usd=100,
            position_pct=30,
            max_exposure_pct=60,
        )

        results = {item.signal_id: item for item in simulation.trades}
        self.assertTrue(results[2].executed)
        self.assertTrue(results[3].executed)
        self.assertFalse(results[1].executed)
        self.assertEqual(results[1].skipped_reason, "capital_exposure_limit")
        self.assertAlmostEqual(simulation.final_balance_usd, 100)
        self.assertEqual(simulation.executed_trade_count, 2)
        self.assertEqual(simulation.skipped_trade_count, 1)
        self.assertEqual(simulation.max_concurrent_positions, 2)
        self.assertAlmostEqual(simulation.max_exposure_reached_pct, 60)

    def test_uses_partial_third_position_when_exposure_has_ten_percent_left(self):
        simulation = simulate_concurrent_bankroll(
            [
                observation(1, 1000, 1300, 90, 0),
                observation(2, 1000, 1300, 80, 0),
                observation(3, 1000, 1300, 70, 100),
                observation(4, 1000, 1300, 60, 100),
            ],
            scenario_name="MUITO AGRESSIVO",
            starting_balance_usd=100,
            position_pct=30,
            max_exposure_pct=70,
        )

        results = {item.signal_id: item for item in simulation.trades}
        self.assertEqual(results[1].stake_usd, 30)
        self.assertEqual(results[2].stake_usd, 30)
        self.assertEqual(results[3].stake_usd, 10)
        self.assertFalse(results[4].executed)
        self.assertEqual(simulation.max_concurrent_positions, 3)
        self.assertAlmostEqual(simulation.final_balance_usd, 110)

    def test_capital_is_reused_only_after_position_target_close(self):
        simulation = simulate_concurrent_bankroll(
            [
                observation(1, 1000, 1600, 90, 10),
                observation(2, 1300, 1500, 80, 100),
                observation(3, 1600, 1900, 70, 10),
            ],
            scenario_name="BLOQUEIO",
            starting_balance_usd=100,
            position_pct=60,
            max_exposure_pct=60,
        )

        results = {item.signal_id: item for item in simulation.trades}
        self.assertTrue(results[1].executed)
        self.assertFalse(results[2].executed)
        self.assertTrue(results[3].executed)
        self.assertAlmostEqual(results[3].stake_usd, 63.6)
        self.assertAlmostEqual(simulation.final_balance_usd, 112.36)

    def test_scaling_is_linear_when_no_extra_impact_model_exists(self):
        trades = [
            observation(1, 1000, 1300, 90, 10),
            observation(2, 1000, 1300, 80, -5),
        ]
        small = simulate_concurrent_bankroll(
            trades,
            scenario_name="SCALE",
            starting_balance_usd=100,
            position_pct=30,
            max_exposure_pct=60,
        )
        large = simulate_concurrent_bankroll(
            trades,
            scenario_name="SCALE",
            starting_balance_usd=1_000,
            position_pct=30,
            max_exposure_pct=60,
        )

        self.assertAlmostEqual(large.final_balance_usd, small.final_balance_usd * 10)
        self.assertAlmostEqual(large.total_return_pct, small.total_return_pct)
        self.assertAlmostEqual(large.max_drawdown_pct, small.max_drawdown_pct)

    def test_reads_full_observations_and_orders_simultaneous_signals_by_score(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "concurrent.db"
            with patch.object(
                database, "settings", SimpleNamespace(database_path=path)
            ):
                initialize_database()
                with database.connection() as conn:
                    ids = []
                    for mint, score in (("low", 60), ("high", 80)):
                        ids.append(
                            conn.execute(
                                """INSERT INTO wave_signals
                                (token_mint, symbol, detected_at, wave_score,
                                entry_market_price_usd, entry_execution_price_usd,
                                copy_size_usd, slippage_bps, strategy_version,
                                snapshot_json)
                                VALUES (?, ?, 1000, ?, 1, 1.01, 25, 100, ?, ?)""",
                                (
                                    mint,
                                    mint,
                                    score,
                                    WAVE_STRATEGY_VERSION,
                                    '{"token":{"liquidity_usd":50000}}',
                                ),
                            ).lastrowid
                        )
                    conn.executemany(
                        """INSERT INTO wave_signal_checks
                        (signal_id, horizon_minutes, target_at, observed_at,
                        market_price_usd, execution_price_usd, return_pct, status)
                        VALUES (?, 5, 1300, 1310, 1.1, 1.09, 5, 'completed')""",
                        [(ids[0],), (ids[1],)],
                    )

                observations = completed_wave_observations(WAVE_STRATEGY_VERSION, 5)

        self.assertEqual([item.symbol for item in observations], ["high", "low"])
        self.assertEqual(observations[0].close_at, 1300)
        self.assertEqual(observations[0].observed_at, 1310)
        self.assertEqual(observations[0].liquidity_usd, 50_000)

    def test_rejects_impossible_configuration_and_invalid_timestamps(self):
        with self.assertRaises(ValueError):
            simulate_concurrent_bankroll(
                [],
                scenario_name="INVALID",
                starting_balance_usd=100,
                position_pct=70,
                max_exposure_pct=60,
            )
        with self.assertRaises(ValueError):
            simulate_concurrent_bankroll(
                [observation(1, 1300, 1000, 90, 1)],
                scenario_name="INVALID",
                starting_balance_usd=100,
                position_pct=30,
                max_exposure_pct=60,
            )

    def test_report_explains_costs_skips_and_capital_evolution(self):
        simulation = simulate_concurrent_bankroll(
            [
                observation(1, 1000, 1300, 90, 10),
                observation(2, 1000, 1300, 80, -5),
                observation(3, 1000, 1300, 70, 100),
            ],
            scenario_name="AGRESSIVO",
            starting_balance_usd=100,
            position_pct=30,
            max_exposure_pct=60,
        )

        output = format_report((simulation,), (simulation,))

        self.assertIn("Executados: 2 | ignorados: 1", output)
        self.assertIn("T3 | Wave 70.0", output)
        self.assertIn("Evolução da banca", output)
        self.assertIn("Slippage observado", output)
        self.assertIn("Fees adicionais não são descontados", output)
        self.assertIn("capital fica bloqueado até target_at", output)
        self.assertIn("posições abertas não são marcadas a mercado", output)


if __name__ == "__main__":
    unittest.main()
