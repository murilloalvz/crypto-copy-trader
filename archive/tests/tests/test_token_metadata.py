import unittest
from unittest.mock import Mock

from src.solana import SolanaRPCError
from src.token_metadata import TokenDecimalsCache, fetch_token_decimals


class TokenMetadataTests(unittest.TestCase):
    def test_fetch_token_decimals_uses_confirmed_supply(self):
        client = Mock()
        client.call.return_value = {"value": {"decimals": 9}}

        result = fetch_token_decimals(client, "TokenMint")

        self.assertEqual(result, 9)
        client.call.assert_called_once_with(
            "getTokenSupply", ["TokenMint", {"commitment": "confirmed"}]
        )

    def test_cache_only_queries_rpc_once_per_token(self):
        client = Mock()
        client.call.return_value = {"value": {"decimals": 6}}
        cache = TokenDecimalsCache(client)

        self.assertEqual(cache.get("TokenMint"), 6)
        self.assertEqual(cache.get("TokenMint"), 6)
        self.assertEqual(client.call.call_count, 1)

    def test_invalid_rpc_shape_is_rejected(self):
        client = Mock()
        client.call.return_value = {"value": {}}

        with self.assertRaises(SolanaRPCError):
            fetch_token_decimals(client, "TokenMint")

    def test_unsupported_decimals_are_rejected(self):
        client = Mock()
        client.call.return_value = {"value": {"decimals": 30}}

        with self.assertRaises(SolanaRPCError):
            fetch_token_decimals(client, "TokenMint")


if __name__ == "__main__":
    unittest.main()
