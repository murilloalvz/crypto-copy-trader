import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_quote_watch import (
    latest_forward_observation_id,
    load_forward_buys_after,
    load_successful_quote_keys_by_event,
    quote_attempt_exists,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletQuoteWatchTests(unittest.TestCase):
    def test_only_new_forward_buys_are_scheduled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes-watch.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T1", "sell", 90, 100),
                    observation_key="sell-1",
                )
                baseline = latest_forward_observation_id()
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T2", "buy", 110, 120),
                    observation_key="buy-1",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("B", "T3", "sell", 115, 125),
                    observation_key="sell-2",
                )

                buys = load_forward_buys_after(baseline)
                probes = schedule_buy_quotes(buys, delays_seconds=[0, 15, 30])

        self.assertEqual(len(buys), 1)
        self.assertEqual(buys[0].token_mint, "T2")
        self.assertEqual([item.target_at for item in probes], [120, 135, 150])
        self.assertEqual(
            [item.attempt_key for item in probes],
            [
                f"wallet-forward:{buys[0].id}:buy:+0s:jupiter-v2",
                f"wallet-forward:{buys[0].id}:buy:+15s:jupiter-v2",
                f"wallet-forward:{buys[0].id}:buy:+30s:jupiter-v2",
            ],
        )

    def test_attempt_audit_is_idempotent_and_records_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 120),
                    observation_key="buy-1",
                )
                probe = schedule_buy_quotes(
                    load_forward_buys_after(0), delays_seconds=[0]
                )[0]
                error = RuntimeError("provider unavailable")

                self.assertTrue(
                    record_quote_attempt(
                        probe,
                        requested_at=121,
                        completed_at=122,
                        status="error",
                        error=error,
                    )
                )
                self.assertTrue(quote_attempt_exists(probe.attempt_key))
                self.assertFalse(
                    record_quote_attempt(
                        probe,
                        requested_at=121,
                        completed_at=122,
                        status="error",
                        error=error,
                    )
                )

                with database.connection() as conn:
                    row = conn.execute(
                        "SELECT status, error_class, error_message FROM causal_quote_attempts"
                    ).fetchone()

        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error_class"], "RuntimeError")
        self.assertEqual(row["error_message"], "provider unavailable")

    def test_success_attempt_requires_quote_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 120),
                    observation_key="buy-1",
                )
                probe = schedule_buy_quotes(
                    load_forward_buys_after(0), delays_seconds=[0]
                )[0]
                with self.assertRaises(ValueError):
                    record_quote_attempt(
                        probe,
                        requested_at=121,
                        completed_at=122,
                        status="success",
                    )

    def test_successful_quote_keys_are_grouped_by_exact_source_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 120),
                    observation_key="buy-a",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("B", "T", "buy", 101, 121),
                    observation_key="buy-b",
                )
                probes = schedule_buy_quotes(
                    load_forward_buys_after(0), delays_seconds=[0, 15]
                )
                for probe in probes:
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at + 1,
                        status="success",
                        quote_key=probe.quote_key,
                    )

                grouped = load_successful_quote_keys_by_event(["buy-a"])
                both = load_successful_quote_keys_by_event(["buy-a", "buy-b"])
                empty = load_successful_quote_keys_by_event([])

        self.assertEqual(set(grouped), {"buy-a"})
        self.assertEqual(len(grouped["buy-a"]), 2)
        self.assertEqual(set(both), {"buy-a", "buy-b"})
        self.assertEqual(len(both["buy-b"]), 2)
        self.assertEqual(empty, {})

    def test_negative_delay_is_rejected(self):
        with self.assertRaises(ValueError):
            schedule_buy_quotes([], delays_seconds=[0, -1])


if __name__ == "__main__":
    unittest.main()
