import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.market_activity_discovery_v0.cli import main
from src import database


class MarketActivityDiscoveryCliV0Tests(unittest.TestCase):
    def _call(self, argv):
        stream = io.StringIO()
        with redirect_stdout(stream):
            rc = main(argv)
        self.assertEqual(rc, 0)
        return json.loads(stream.getvalue())

    def test_open_inspect_and_close_use_frozen_six_hour_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cli.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                opened = self._call(
                    [
                        "open",
                        "--run-key",
                        "CLI_RUN",
                        "--cohort-key",
                        "CLI_COHORT",
                        "--started-at",
                        "1000",
                    ]
                )
                inspected = self._call(["inspect", "--run-key", "CLI_RUN"])
                closed = self._call(
                    ["close", "--run-key", "CLI_RUN", "--observed-at", "22600"]
                )

        self.assertEqual(opened["run"]["started_at"], 1000)
        self.assertEqual(opened["run"]["admission_closes_at"], 22600)
        self.assertEqual(inspected["cohort_denominator"], 0)
        self.assertEqual(inspected["forward_outcome_count"], 0)
        self.assertFalse(inspected["economic_edge_evaluated"])
        self.assertEqual(closed["run"]["status"], "CLOSED")
        self.assertEqual(closed["run"]["closed_at"], 22600)

    def test_interrupt_is_distinct_from_normal_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupt.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._call(
                    [
                        "open",
                        "--run-key",
                        "CLI_RUN_2",
                        "--cohort-key",
                        "CLI_COHORT_2",
                        "--started-at",
                        "1000",
                    ]
                )
                interrupted = self._call(
                    [
                        "interrupt",
                        "--run-key",
                        "CLI_RUN_2",
                        "--observed-at",
                        "1200",
                        "--reason",
                        "simulated operational failure",
                    ]
                )

        self.assertEqual(interrupted["run"]["status"], "INTERRUPTED")
        self.assertEqual(interrupted["run"]["closed_at"], 1200)
        self.assertEqual(
            interrupted["run"]["interruption_reason"],
            "simulated operational failure",
        )


if __name__ == "__main__":
    unittest.main()
