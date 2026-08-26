import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from radar import format_paper_report, format_report, main
from src import database
from src.database import rows
from src.wave_radar import build_wave_radar_report
from tests.test_wave_radar import token


class WaveRadarCLITests(unittest.TestCase):
    def test_report_is_explicitly_read_only_and_explainable(self):
        report = build_wave_radar_report([token()])

        output = format_report(report, top_n=10, now_ms=1_800_000_600_000)

        self.assertIn("Wave Radar", output)
        self.assertIn("Tokens analisados: 1", output)
        self.assertIn("Aptos para paper signal: 1", output)
        self.assertIn("APTA PARA PAPER SIGNAL", output)
        self.assertIn("Wave Score inicial:", output)
        self.assertIn("Motivos:", output)
        self.assertIn("READ ONLY", output)
        self.assertIn("não prevê valorização futura", output)

    def test_paper_report_explains_pending_and_completed_horizons(self):
        update = type(
            "Update",
            (),
            {
                "created_signals": 1,
                "completed_checks": 1,
                "failed_checks": 0,
                "pending_checks": 2,
            },
        )()
        signals = [
            {
                "symbol": "WAVE",
                "name": "Wave Test",
                "token_mint": "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump",
                "status": "tracking",
                "entry_market_price_usd": 0.001,
                "entry_execution_price_usd": 0.00101,
                "copy_size_usd": 25,
                "slippage_bps": 100,
                "checks": [
                    {
                        "horizon_minutes": 5,
                        "status": "completed",
                        "return_pct": 7.82,
                        "pnl_usd": 1.96,
                        "target_at": 1_300,
                    },
                    {
                        "horizon_minutes": 15,
                        "status": "pending",
                        "return_pct": None,
                        "pnl_usd": None,
                        "target_at": 1_900,
                    },
                ],
            }
        ]

        output = format_paper_report(update, signals, now=1_000)

        self.assertIn("LABORATÓRIO PAPER", output)
        self.assertIn("retorno líquido +7.82%", output)
        self.assertIn("pendente", output)
        self.assertIn("Nenhuma ordem", output)

    def test_main_persists_approved_signal_without_network_trading(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = SimpleNamespace(database_path=Path(directory) / "radar.db")
            output = io.StringIO()
            with (
                patch.object(database, "settings", test_settings),
                patch(
                    "radar.SolanaTrackerClient.wave_tokens",
                    return_value=[token()],
                ),
                redirect_stdout(output),
            ):
                exit_code = main(["--tokens", "1", "--top", "1"])
                signal_count = rows("SELECT COUNT(*) AS total FROM wave_signals")[0][
                    "total"
                ]
                check_count = rows(
                    "SELECT COUNT(*) AS total FROM wave_signal_checks"
                )[0]["total"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(signal_count, 1)
        self.assertEqual(check_count, 3)
        self.assertIn("Novos sinais salvos: 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
