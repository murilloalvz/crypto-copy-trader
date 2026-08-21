import unittest

from src.solana import CURRENT_MAINNET_RPC_URL, SolanaClient, normalize_rpc_url


class RPCEndpointTests(unittest.TestCase):
    def test_legacy_mainnet_endpoint_is_migrated(self):
        client = SolanaClient("https://api.mainnet-beta.solana.com/")

        self.assertEqual(client.rpc_url, CURRENT_MAINNET_RPC_URL)

    def test_custom_rpc_endpoint_is_preserved(self):
        rpc_url = "https://example-rpc.invalid/path?api-key=test"

        self.assertEqual(normalize_rpc_url(rpc_url), rpc_url)

