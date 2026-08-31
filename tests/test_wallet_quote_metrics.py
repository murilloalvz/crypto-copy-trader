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


if __name__ == "__main__":
    unittest.main()
