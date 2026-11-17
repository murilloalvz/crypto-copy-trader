import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_quote_watch import (
    load_forward_events_after,
    record_quote_attempt,
    schedule_buy_quotes,
)
from src.wallet_sell_quote_lineage import load_same_run_successful_buy_quote_lineage


class WalletSellQuoteLineageTests(unittest.TestCase):
    def test_sell_only_reuses_buy_quotes_from_same_forward_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lineage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "TOKEN", "buy", 100, 110),
                    observation_key="run1-buy",
                    run_key="run-1",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("W", "TOKEN", "buy", 200, 210),
                    observation_key="run2-buy",
                    run_key="run-2",
                )
                buys = load_forward_events_after(0, side="buy")
                for probe in schedule_buy_quotes(buys, delays_seconds=[0]):
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at + 1,
                        status="success",
                        quote_key=probe.quote_key,
                    )

                record_wallet_forward_observation(
                    WalletActionObservation("W", "TOKEN", "sell", 300, 310),
                    observation_key="run2-sell",
                    run_key="run-2",
                )
                lineage = load_same_run_successful_buy_quote_lineage("run2-sell")

        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0].source_event_key, "run2-buy")
        self.assertNotEqual(lineage[0].source_event_key, "run1-buy")

    def test_unscoped_sell_never_guesses_historical_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "TOKEN", "sell", 100, 110),
                    observation_key="legacy-sell",
                )
                lineage = load_same_run_successful_buy_quote_lineage("legacy-sell")

        self.assertEqual(lineage, ())

    def test_missing_sell_observation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    load_same_run_successful_buy_quote_lineage("missing-sell")


if __name__ == "__main__":
    unittest.main()
