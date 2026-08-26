import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluate import format_evaluation_report, main
from src import database
from src.wave_metrics import WaveEvaluationReport
from src.wave_paper import WAVE_STRATEGY_VERSION


class WaveEvaluationCLITests(unittest.TestCase):
    def test_empty_report_is_explicitly_inconclusive(self):
        report = WaveEvaluationReport(
            strategy_version=WAVE_STRATEGY_VERSION,
            signal_count=1,
            completed_check_count=0,
            pending_check_count=3,
            failed_check_count=0,
            horizons=(),
        )

        output = format_evaluation_report(report)

        self.assertIn("INCONCLUSIVO", output)
        self.assertIn("3 pendentes", output)

    def test_main_reads_empty_local_database_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with (
                patch.object(
                    database,
                    "settings",
                    SimpleNamespace(database_path=Path(directory) / "empty.db"),
                ),
                redirect_stdout(output),
            ):
                exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("PAPER/READ ONLY", output.getvalue())
        self.assertIn("menos de 30 observações", output.getvalue())


if __name__ == "__main__":
    unittest.main()
