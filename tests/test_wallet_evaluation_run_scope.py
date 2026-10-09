import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import evaluate_wallet_forward
import evaluate_wallet_quotes
from src import database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_forward_runs import create_wallet_forward_run, finish_wallet_forward_run
from src.wallet_quote_watch import (
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletEvaluationRunScopeTests(unittest.TestCase):
    def test_forward_latency_loader_respects_run_ids_and_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scope.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "OLD", "buy", 80, 90),
                    observation_key="old",
                )
                created = create_wallet_forward_run(
                    run_key="run",
                    started_at=100,
                    baseline_observation_id=1,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("A", "IN", "buy", 105, 110),
                    observation_key="in",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("B", "OTHER", "buy", 106, 111),
                    observation_key="other-wallet",
                )
                finish_wallet_forward_run(
                    "run", status="COMPLETED", ended_at=120, end_observation_id=3
                )
                record_wallet_forward_observation(
                    WalletActionObservation("A", "AFTER", "buy", 125, 130),
                    observation_key="after",
                )

                scoped = evaluate_wallet_forward._load_observations(run=created)
                finished = evaluate_wallet_forward.get_wallet_forward_run("run")
                scoped_finished = evaluate_wallet_forward._load_observations(run=finished)

        # ACTIVE manifest has no end cursor yet, so the finished manifest is the meaningful
        # post-run audit scope. Once frozen, only id=2 / wallet A remains.
        self.assertGreaterEqual(len(scoped), 1)
        self.assertEqual(len(scoped_finished), 1)
        self.assertEqual(scoped_finished[0].token_mint, "IN")
        self.assertEqual(scoped_finished[0].address, "A")

    def test_quote_evaluation_uses_exact_run_buy_event_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[0],
                    with_jupiter_quotes=True,
                    copy_size_usd=25.0,
                    quote_mode="proxy",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("A", "IN", "buy", 105, 110),
                    observation_key="in",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("B", "OUT", "buy", 106, 111),
                    observation_key="out",
                )
                finish_wallet_forward_run(
                    "run", status="COMPLETED", ended_at=120, end_observation_id=2
                )
                for event in load_forward_buys_after(0):
                    probe = schedule_buy_quotes([event], delays_seconds=[0])[0]
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at + 1,
                        status="error",
                        error=RuntimeError("provider"),
                    )

                output = io.StringIO()
                with redirect_stdout(output):
                    code = evaluate_wallet_quotes.main(["--run-key", "run", "--json"])
                payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["scope"]["mode"], "RUN_MANIFEST")
        self.assertEqual(payload["metrics"]["attempt_count"], 1)
        self.assertEqual(payload["metrics"]["wallet_count"], 1)
        self.assertEqual(payload["metrics"]["token_count"], 1)


if __name__ == "__main__":
    unittest.main()
