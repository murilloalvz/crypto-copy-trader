import unittest
from unittest.mock import patch

from src.wallet_forward_rpc import WalletForwardSolanaClient


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


if __name__ == "__main__":
    unittest.main()
