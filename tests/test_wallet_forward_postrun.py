import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import wallet_forward_postrun
from src import database
from src.wallet_forward_runs import create_wallet_forward_run, finish_wallet_forward_run


class WalletForwardPostRunTests(unittest.TestCase):
    def test_zero_sample_completed_run_is_a_valid_audit_not_a_pipeline_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "postrun.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run-zero",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["A", "B"],
                    interval_seconds=30,
                    quote_delays_seconds=[0, 15, 30, 60, 120],
                    with_jupiter_quotes=True,
                    copy_size_usd=25.0,
                    quote_mode="proxy",
                )
                finish_wallet_forward_run(
                    "run-zero",
                    status="COMPLETED",
                    ended_at=200,
                    end_observation_id=0,
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    code = wallet_forward_postrun.main(["--run-key", "run-zero"])

        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("CAUSAL REPLAY READINESS", text)
        self.assertIn("NO_CAUSAL_SAMPLE", text)
        self.assertIn("PER-WALLET TECHNICAL PROFILES", text)
        self.assertIn("non-zero: 0", text)
        self.assertIn("AUDIT PIPELINE COMPLETED", text)


if __name__ == "__main__":
    unittest.main()
