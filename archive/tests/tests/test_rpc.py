import json
import ssl
import unittest
from unittest.mock import patch
from urllib.error import URLError

from src.solana import CURRENT_MAINNET_RPC_URL, SolanaClient, normalize_rpc_url


class FakeResponse:
    def __init__(self, result):
        self.body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class RPCEndpointTests(unittest.TestCase):
    def test_legacy_mainnet_endpoint_is_migrated(self):
        client = SolanaClient("https://api.mainnet-beta.solana.com/")

        self.assertEqual(client.rpc_url, CURRENT_MAINNET_RPC_URL)

    def test_custom_rpc_endpoint_is_preserved(self):
        rpc_url = "https://example-rpc.invalid/path?api-key=test"

        self.assertEqual(normalize_rpc_url(rpc_url), rpc_url)

    @patch("src.solana.urlopen")
    def test_transport_failure_uses_fallback_and_keeps_it_active(self, mocked_urlopen):
        mocked_urlopen.side_effect = [URLError("primary down"), FakeResponse("ok")]
        client = SolanaClient(
            "https://primary.invalid",
            fallback_urls=["https://fallback.invalid"],
        )

        result = client.call("getHealth", [], max_attempts=1)

        self.assertEqual(result, "ok")
        self.assertEqual(client.rpc_host, "fallback.invalid")
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("src.solana.urlopen")
    def test_ssl_failure_retries_with_verified_tls12(self, mocked_urlopen):
        ssl_error = URLError(ssl.SSLError("handshake failure"))
        mocked_urlopen.side_effect = [ssl_error, FakeResponse("ok")]
        client = SolanaClient("https://primary.invalid", fallback_urls=[])

        result = client.call("getHealth", [], max_attempts=1)

        self.assertEqual(result, "ok")
        context = mocked_urlopen.call_args_list[1].kwargs["context"]
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.maximum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
