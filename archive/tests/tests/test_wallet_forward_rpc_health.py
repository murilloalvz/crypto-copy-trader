import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.wallet_forward_rpc_health import (
    list_wallet_forward_rpc_health_events,
    record_wallet_forward_rpc_failure,
    record_wallet_forward_rpc_recovery,
)


class WalletForwardRpcHealthTests(unittest.TestCase):
    def test_failure_and_recovery_are_persisted_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rpc-health.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_rpc_failure(
                    run_key="run-1",
                    observed_at=100,
                    wallet_address="wallet-A",
                    phase="poll",
                    error=ConnectionError("network down"),
                )
                record_wallet_forward_rpc_recovery(
                    run_key="run-1",
                    observed_at=140,
                    wallet_address="wallet-A",
                    phase="poll",
                    rpc_endpoint="fallback.invalid",
                )
                events = list_wallet_forward_rpc_health_events("run-1")

        self.assertEqual([event.status for event in events], ["FAILURE", "RECOVERED"])
        self.assertEqual(events[0].error_type, "ConnectionError")
        self.assertEqual(events[0].error_message, "network down")
        self.assertIsNone(events[0].rpc_endpoint)
        self.assertEqual(events[1].rpc_endpoint, "fallback.invalid")
        self.assertIsNone(events[1].error_type)

    def test_events_are_isolated_by_run_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rpc-health-isolation.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_rpc_failure(
                    run_key="run-a",
                    observed_at=100,
                    wallet_address="wallet-A",
                    phase="bootstrap",
                    error=ConnectionError("down-a"),
                )
                record_wallet_forward_rpc_failure(
                    run_key="run-b",
                    observed_at=110,
                    wallet_address="wallet-B",
                    phase="poll",
                    error=ConnectionError("down-b"),
                )
                events = list_wallet_forward_rpc_health_events("run-a")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].run_key, "run-a")
        self.assertEqual(events[0].phase, "bootstrap")

    def test_failure_requires_error_and_invalid_phase_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rpc-health-validation.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    record_wallet_forward_rpc_failure(
                        run_key="run-1",
                        observed_at=100,
                        wallet_address="wallet-A",
                        phase="invalid",
                        error=ConnectionError("down"),
                    )


if __name__ == "__main__":
    unittest.main()
