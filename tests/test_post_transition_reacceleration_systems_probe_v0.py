from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from benchmarks.post_transition_reacceleration_v0.systems_probe import (
    _http_to_ws,
    candidate_wss_urls,
)


class PostTransitionSystemsProbeV0Tests(unittest.TestCase):
    def test_http_rpc_urls_convert_to_websocket_without_changing_path_or_query(self):
        self.assertEqual(
            _http_to_ws("https://example.invalid/v2/key?x=1"),
            "wss://example.invalid/v2/key?x=1",
        )
        self.assertEqual(
            _http_to_ws("http://localhost:8899"),
            "ws://localhost:8899",
        )
        self.assertEqual(
            _http_to_ws("wss://example.invalid/feed"),
            "wss://example.invalid/feed",
        )

    def test_legacy_mainnet_beta_rpc_is_normalized_before_wss_conversion(self):
        self.assertEqual(
            _http_to_ws("https://api.mainnet-beta.solana.com"),
            "wss://api.mainnet.solana.com",
        )

    def test_candidate_order_is_explicit_primary_then_fallbacks_and_deduped(self):
        env = {
            "SOLANA_LOGS_WSS_URL": "wss://explicit.invalid/path",
            "SOLANA_RPC_URL": "https://primary.invalid/rpc",
            "SOLANA_RPC_FALLBACK_URLS": (
                "https://fallback.invalid/a,"
                "https://primary.invalid/rpc"
            ),
        }
        with patch.dict(os.environ, env, clear=True):
            rows = candidate_wss_urls()

        self.assertEqual(
            rows,
            [
                ("explicit_logs_wss", "wss://explicit.invalid/path"),
                ("solana_rpc_primary", "wss://primary.invalid/rpc"),
                ("solana_rpc_fallback_1", "wss://fallback.invalid/a"),
            ],
        )

    def test_invalid_or_missing_urls_are_not_invented(self):
        env = {
            "SOLANA_LOGS_WSS_URL": "",
            "SOLANA_RPC_URL": "not-a-url",
            "SOLANA_RPC_FALLBACK_URLS": "",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(candidate_wss_urls(), [])


if __name__ == "__main__":
    unittest.main()
