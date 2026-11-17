import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import wallet_watch_forward
from src.solana import SolanaRPCError


class WalletWatchForwardNetworkResilienceTests(unittest.TestCase):
    def test_poll_transport_failure_is_recorded_and_later_recovery_continues(self):
        successful_sync = {
            "found": 0,
            "inserted": 0,
            "failed": 0,
            "rpc_endpoint": "fallback.invalid",
        }
        sync_calls = 0

        def sync_side_effect(*_args, **_kwargs):
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls == 1:  # bootstrap
                return successful_sync
            if sync_calls == 2:  # first forward poll
                raise SolanaRPCError("Todos os RPCs falharam")
            return successful_sync  # later poll recovers

        capture = SimpleNamespace(
            known_signatures=set(),
            recorded_action_count=0,
            ignored_new_transaction_count=0,
            prestart_new_transaction_count=0,
            new_transaction_count=0,
        )

        monotonic_value = 0.0

        def monotonic_side_effect():
            nonlocal monotonic_value
            monotonic_value += 0.25
            return monotonic_value

        client = Mock()
        failure_recorder = Mock()
        recovery_recorder = Mock()

        with (
            patch.object(wallet_watch_forward, "initialize_database"),
            patch.object(wallet_watch_forward, "ensure_wallet_forward_observation_schema"),
            patch.object(wallet_watch_forward, "ensure_wallet_forward_rpc_health_schema"),
            patch.object(wallet_watch_forward, "add_wallet"),
            patch.object(wallet_watch_forward, "WalletForwardSolanaClient", return_value=client),
            patch.object(wallet_watch_forward, "sync_wallet", side_effect=sync_side_effect),
            patch.object(wallet_watch_forward, "load_known_wallet_signatures", return_value=set()),
            patch.object(wallet_watch_forward, "capture_new_wallet_actions", return_value=capture),
            patch.object(
                wallet_watch_forward,
                "record_wallet_forward_rpc_failure",
                failure_recorder,
            ),
            patch.object(
                wallet_watch_forward,
                "record_wallet_forward_rpc_recovery",
                recovery_recorder,
            ),
            patch.object(wallet_watch_forward.time, "monotonic", side_effect=monotonic_side_effect),
            patch.object(
                wallet_watch_forward.time,
                "time",
                side_effect=[1000, 1010, 1020, 1030],
            ),
            patch.object(wallet_watch_forward.time, "sleep"),
        ):
            result = wallet_watch_forward.main(
                [
                    "wallet-A",
                    "--hours",
                    "0.0005",
                    "--interval-seconds",
                    "10",
                    "--rpc-commitment",
                    "confirmed",
                    "--run-key",
                    "run-network-test",
                ]
            )

        self.assertEqual(result, 0)
        self.assertGreaterEqual(sync_calls, 3)
        failure_recorder.assert_called_once()
        recovery_recorder.assert_called_once()
        self.assertEqual(failure_recorder.call_args.kwargs["run_key"], "run-network-test")
        self.assertEqual(failure_recorder.call_args.kwargs["phase"], "poll")
        self.assertEqual(recovery_recorder.call_args.kwargs["run_key"], "run-network-test")
        self.assertEqual(recovery_recorder.call_args.kwargs["phase"], "poll")


if __name__ == "__main__":
    unittest.main()
