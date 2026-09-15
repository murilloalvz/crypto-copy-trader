import unittest

from benchmarks.robinhood_sequencer_shadow_v0.provider_access_preflight import (
    USER_AGENT,
    build_feed_handshake_request_v0,
    classify_provider_access_v0,
    run_provider_access_preflight_v0,
)


class RobinhoodProviderAccessPreflightV0Tests(unittest.TestCase):
    def test_classifies_pass_only_when_rpc_and_feed_are_both_accessible(self):
        self.assertEqual(
            classify_provider_access_v0(
                {"ok": True, "http_status": 200},
                {"ok": True, "http_status": 101},
            ),
            "PASS_ROBINHOOD_PROVIDER_ACCESS_PREFLIGHT_V0",
        )

    def test_401_or_403_is_provider_access_denied(self):
        self.assertEqual(
            classify_provider_access_v0(
                {"ok": False, "http_status": 403},
                {"ok": False, "http_status": 403},
            ),
            "FAIL_ROBINHOOD_PROVIDER_ACCESS_DENIED_V0",
        )

    def test_429_is_inconclusive_rate_limit_not_protocol_failure(self):
        self.assertEqual(
            classify_provider_access_v0(
                {"ok": False, "http_status": 429},
                {"ok": True, "http_status": 101},
            ),
            "INCONCLUSIVE_ROBINHOOD_PROVIDER_RATE_LIMITED_V0",
        )

    def test_feed_handshake_is_identified_and_keeps_nitro_headers(self):
        request = build_feed_handshake_request_v0(
            "wss://feed.mainnet.chain.robinhood.com",
            requested_sequence_number=0,
            websocket_key="dGVzdGtleXRlc3RrZXk=",
        ).decode("ascii")
        self.assertIn(f"User-Agent: {USER_AGENT}\r\n", request)
        self.assertIn("Arbitrum-Feed-Client-Version: 2\r\n", request)
        self.assertIn("Arbitrum-Requested-Sequence-Number: 0\r\n", request)
        self.assertNotIn("Sec-WebSocket-Extensions", request)

    def test_report_redacts_provider_path_and_query(self):
        def rpc_probe(url, *, timeout_seconds):
            return {"ok": True, "http_status": 200, "chain_id": 4663}

        def feed_probe(url, *, timeout_seconds):
            return {"ok": True, "http_status": 101, "chain_id": 4663}

        report = run_provider_access_preflight_v0(
            rpc_url="https://provider.example/v2/SECRET_KEY?x=SECRET_QUERY",
            feed_url="wss://feed.example/private/SECRET?token=SECRET_QUERY",
            rpc_probe=rpc_probe,
            feed_probe=feed_probe,
        )
        rendered = str(report)
        self.assertEqual(report["classification"], "PASS_ROBINHOOD_PROVIDER_ACCESS_PREFLIGHT_V0")
        self.assertTrue(report["rpc_endpoint"]["path_redacted"])
        self.assertTrue(report["rpc_endpoint"]["query_redacted"])
        self.assertTrue(report["feed_endpoint"]["path_redacted"])
        self.assertTrue(report["feed_endpoint"]["query_redacted"])
        self.assertNotIn("SECRET_KEY", rendered)
        self.assertNotIn("SECRET_QUERY", rendered)


if __name__ == "__main__":
    unittest.main()
