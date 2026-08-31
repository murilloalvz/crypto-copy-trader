import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import (
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletQuoteMetricsTests(unittest.TestCase):
    def test_metrics_group_by_delay_and_separate_proxy_from_candidate_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "buy", 100, 120),
                    observation_key="buy-1",
                )
                probes = schedule_buy_quotes(
                    load_forward_buys_after(0), delays_seconds=[0, 15, 30]
                )

                candidate = CausalQuoteObservation(
                    token_mint="T",
                    side="buy",
                    market_time=121,
                    observed_at=121,
                    price_usd=1.0,
                    source="jupiter",
                    executable=True,
                    input_mint="USDC",
                    output_mint="T",
                )
                proxy = CausalQuoteObservation(
                    token_mint="T",
                    side="buy",
                    market_time=137,
                    observed_at=137,
                    price_usd=1.1,
                    source="jupiter",
                    executable=False,
                )
                record_causal_quote(candidate, quote_key=probes[0].quote_key)
                record_quote_attempt(
                    probes[0],
                    requested_at=120,
                    completed_at=121,
                    status="success",
                    quote_key=probes[0].quote_key,
                )
                record_causal_quote(proxy, quote_key=probes[1].quote_key)
                record_quote_attempt(
                    probes[1],
                    requested_at=136,
                    completed_at=137,
                    status="success",
                    quote_key=probes[1].quote_key,
                )
                record_quote_attempt(
                    probes[2],
                    requested_at=151,
                    completed_at=152,
                    status="error",
                    error=RuntimeError("route unavailable"),
                )

                metrics = summarize_wallet_quote_metrics(wallet_addresses=["W"])

        self.assertEqual(metrics.attempt_count, 3)
        self.assertEqual(metrics.success_count, 2)
        self.assertEqual(metrics.failure_count, 1)
        self.assertAlmostEqual(metrics.success_pct, 66.6666666, places=4)
        self.assertEqual(metrics.executable_count, 1)
        self.assertEqual(metrics.proxy_count, 1)
        self.assertEqual([item.delay_seconds for item in metrics.delays], [0, 15, 30])
        self.assertEqual(metrics.delays[0].median_request_lag_seconds, 0.0)
        self.assertEqual(metrics.delays[1].median_request_lag_seconds, 1.0)
        self.assertEqual(metrics.delays[2].errors, (("RuntimeError", 1),))

    def test_source_event_scope_excludes_other_same_wallet_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "buy", 100, 120),
                    observation_key="run-a-buy",
                )
                first = schedule_buy_quotes(
                    load_forward_buys_after(0), delays_seconds=[0]
                )[0]
                record_quote_attempt(
                    first,
                    requested_at=120,
                    completed_at=121,
                    status="error",
                    error=RuntimeError("first run error"),
                )

                baseline = first.event_id
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "buy", 200, 220),
                    observation_key="run-b-buy",
                )
                second = schedule_buy_quotes(
                    load_forward_buys_after(baseline), delays_seconds=[0]
                )[0]
                record_quote_attempt(
                    second,
                    requested_at=220,
                    completed_at=221,
                    status="error",
                    error=RuntimeError("second run error"),
                )

                run_b = summarize_wallet_quote_metrics(
                    wallet_addresses=["W"],
                    source_event_keys=["run-b-buy"],
                )
                empty = summarize_wallet_quote_metrics(
                    wallet_addresses=["W"],
                    source_event_keys=[],
                )

        self.assertEqual(run_b.attempt_count, 1)
        self.assertEqual(run_b.failure_count, 1)
        self.assertEqual(run_b.delays[0].errors, (("RuntimeError", 1),))
        self.assertEqual(empty.attempt_count, 0)
        self.assertEqual(empty.delays, ())


if __name__ == "__main__":
    unittest.main()
