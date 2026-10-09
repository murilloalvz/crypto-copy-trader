import json
import unittest
from http.client import RemoteDisconnected
from unittest.mock import patch

from src.solana import SolanaRPCError
from src.wallet_forward_rpc import WalletForwardSolanaClient


class FakeResponse:
    def __init__(self, result):
        self.body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class WalletForwardRpcTests(unittest.TestCase):
    def test_commitment_is_explicit_on_signatures_and_transaction(self):
        client = WalletForwardSolanaClient(
            commitment="confirmed",
            rpc_url="https://example.invalid",
            fallback_urls=[],
        )
        with patch.object(client, "call", side_effect=[[], None]) as mocked:
            client.signatures("wallet", 30)
            client.transaction("sig")

        signatures_call = mocked.call_args_list[0]
        self.assertEqual(signatures_call.args[0], "getSignaturesForAddress")
        self.assertEqual(signatures_call.args[1][1]["commitment"], "confirmed")
        transaction_call = mocked.call_args_list[1]
        self.assertEqual(transaction_call.args[0], "getTransaction")
        self.assertEqual(transaction_call.args[1][1]["commitment"], "confirmed")

    def test_finalized_is_supported_and_invalid_commitment_rejected(self):
        client = WalletForwardSolanaClient(
            commitment="finalized",
            rpc_url="https://example.invalid",
            fallback_urls=[],
        )
        self.assertEqual(client.commitment, "finalized")
        with self.assertRaises(ValueError):
            WalletForwardSolanaClient(commitment="processed")

    def test_signature_statuses_preserve_one_result_per_signature(self):
        client = WalletForwardSolanaClient(
            commitment="confirmed",
            rpc_url="https://example.invalid",
            fallback_urls=[],
        )
        payload = {
            "value": [
                {"confirmationStatus": "finalized", "err": None},
                {"confirmationStatus": "confirmed", "err": None},
            ]
        }
        with patch.object(client, "call", return_value=payload) as mocked:
            statuses = client.signature_statuses(["a", "b"])

        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[0]["confirmationStatus"], "finalized")
        self.assertEqual(mocked.call_args.args[0], "getSignatureStatuses")
        self.assertTrue(mocked.call_args.args[1][1]["searchTransactionHistory"])

    def test_signature_statuses_rejects_more_than_rpc_batch_limit(self):
        client = WalletForwardSolanaClient(commitment="confirmed")
        with self.assertRaises(ValueError):
            client.signature_statuses([str(index) for index in range(257)])

    @patch("src.solana.urlopen")
    def test_remote_disconnected_retries_same_endpoint(self, mocked_urlopen):
        mocked_urlopen.side_effect = [
            RemoteDisconnected("remote closed without response"),
            FakeResponse("ok"),
        ]
        client = WalletForwardSolanaClient(
            commitment="confirmed",
            rpc_url="https://primary.invalid",
            fallback_urls=[],
        )

        result = client.call("getHealth", [], max_attempts=2)

        self.assertEqual(result, "ok")
        self.assertEqual(client.rpc_host, "primary.invalid")
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("src.solana.urlopen")
    def test_remote_disconnected_uses_fallback(self, mocked_urlopen):
        mocked_urlopen.side_effect = [
            RemoteDisconnected("primary disconnected"),
            FakeResponse("ok"),
        ]
        client = WalletForwardSolanaClient(
            commitment="confirmed",
            rpc_url="https://primary.invalid",
            fallback_urls=["https://fallback.invalid"],
        )

        result = client.call("getHealth", [], max_attempts=1)

        self.assertEqual(result, "ok")
        self.assertEqual(client.rpc_host, "fallback.invalid")
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("src.solana.urlopen")
    def test_all_endpoints_disconnected_raise_solana_rpc_error(self, mocked_urlopen):
        mocked_urlopen.side_effect = [
            RemoteDisconnected("primary disconnected"),
            RemoteDisconnected("fallback disconnected"),
        ]
        client = WalletForwardSolanaClient(
            commitment="confirmed",
            rpc_url="https://primary.invalid",
            fallback_urls=["https://fallback.invalid"],
        )

        with self.assertRaises(SolanaRPCError) as raised:
            client.call("getHealth", [], max_attempts=1)

        message = str(raised.exception)
        self.assertIn("Todos os RPCs falharam", message)
        self.assertIn("primary.invalid", message)
        self.assertIn("fallback.invalid", message)
        self.assertEqual(mocked_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
