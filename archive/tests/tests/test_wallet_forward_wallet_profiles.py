import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import wallet_forward_wallet_profiles as profiles
from src import database
from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_forward_runs import create_wallet_forward_run, finish_wallet_forward_run
from src.wallet_quote_watch import (
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletForwardWalletProfilesTests(unittest.TestCase):
    def test_profile_keeps_latency_quote_coverage_and_drift_event_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_wallet_forward_run(
                    run_key="run",
                    started_at=90,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[0, 15],
                    with_jupiter_quotes=True,
                    copy_size_usd=25.0,
                    quote_mode="proxy",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 110),
                    observation_key="buy-a",
                )
                run = finish_wallet_forward_run(
                    "run",
                    status="COMPLETED",
                    ended_at=200,
                    end_observation_id=1,
                )
                event = load_forward_buys_after(0, through_id=1)[0]
                probes = schedule_buy_quotes([event], delays_seconds=[0, 15])
                prices = [1.0, 1.1]
                for probe, price in zip(probes, prices):
                    record_causal_quote(
                        CausalQuoteObservation(
                            token_mint="T",
                            side="buy",
                            market_time=probe.target_at,
                            observed_at=probe.target_at,
                            price_usd=price,
                            source="jupiter-test",
                            executable=False,
                        ),
                        quote_key=probe.quote_key,
                    )
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at,
                        status="success",
                        quote_key=probe.quote_key,
                    )

                result = profiles._profile_wallet(
                    run,
                    "A",
                    baseline_delay_seconds=0,
                )

        self.assertEqual(result["latency"]["observation_count"], 1)
        self.assertEqual(result["latency"]["median_lag_seconds"], 10.0)
        self.assertEqual(result["readiness"]["label"], "CAUSAL_REPLAY_SAMPLE_READY")
        self.assertEqual(result["quote_completeness"]["attempted_expected_count"], 2)
        self.assertEqual(result["quote_completeness"]["successful_expected_count"], 2)
        drift = result["quote_drift"]
        self.assertEqual(drift["baseline_event_count"], 1)
        self.assertEqual(len(drift["delays"]), 1)
        self.assertEqual(drift["delays"][0]["delay_seconds"], 15)
        self.assertAlmostEqual(drift["delays"][0]["median_adverse_drift_pct"], 10.0)


if __name__ == "__main__":
    unittest.main()
