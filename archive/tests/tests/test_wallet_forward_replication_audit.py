import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.wallet_forward_enrollments import freeze_wallet_forward_enrollment
from src.wallet_forward_replication_audit import (
    _load_quotes_by_exact_key,
    build_wallet_forward_replication_audit,
)
from src.wallet_forward_runs import create_wallet_forward_run, finish_wallet_forward_run


class WalletForwardReplicationAuditTests(unittest.TestCase):
    def test_exact_quote_key_loader_does_not_depend_on_timestamp_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=190,
                        observed_at=200,
                        price_usd=2.0,
                        source="test",
                        executable=False,
                    ),
                    quote_key="late-key",
                )
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=90,
                        observed_at=100,
                        price_usd=1.0,
                        source="test",
                        executable=False,
                    ),
                    quote_key="early-key",
                )

                keyed = _load_quotes_by_exact_key(("late-key", "early-key"))

        self.assertEqual(keyed["late-key"].price_usd, 2.0)
        self.assertEqual(keyed["early-key"].price_usd, 1.0)

    def test_two_empty_completed_runs_remain_separate_and_narrow(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                for key, started_at in (("run-1", 100), ("run-2", 1_000)):
                    create_wallet_forward_run(
                        run_key=key,
                        started_at=started_at,
                        baseline_observation_id=0,
                        cohort=["A"],
                        interval_seconds=10,
                        quote_delays_seconds=[0, 15],
                        with_jupiter_quotes=True,
                        copy_size_usd=25,
                        quote_mode="proxy",
                        runtime_version="runtime-v5",
                        quote_intake_grace_seconds=15,
                        enrollment_ends_at=started_at + 40,
                        follow_up_ends_at=started_at + 100,
                    )
                    freeze_wallet_forward_enrollment(key, cutoff_observation_id=0)
                    finish_wallet_forward_run(
                        key,
                        status="COMPLETED",
                        ended_at=started_at + 100,
                        end_observation_id=0,
                    )

                audit = build_wallet_forward_replication_audit(
                    ["run-1", "run-2"], allow_proxy_quotes=True
                )

        self.assertEqual(
            audit.compatibility.label,
            "SAME_TECHNICAL_REGIME_COMPARE_SEPARATELY",
        )
        self.assertFalse(audit.automatic_pooling_allowed)
        self.assertEqual(len(audit.runs), 2)
        self.assertEqual(audit.runs[0].enrolled_buy_count, 0)
        self.assertEqual(audit.runs[1].enrolled_buy_count, 0)
        self.assertEqual(
            audit.interpretation,
            "DESCRIPTIVE_REPLICATION_SAMPLE_STILL_NARROW",
        )
        self.assertIn(
            "one_or_more_runs_have_zero_enrolled_buys",
            audit.interpretation_flags,
        )
        self.assertIn("proxy_quotes_not_executable_fills", audit.interpretation_flags)


if __name__ == "__main__":
    unittest.main()
