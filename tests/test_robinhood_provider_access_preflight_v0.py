import unittest

from benchmarks.robinhood_sequencer_shadow_v0.provider_access_preflight import (
    USER_AGENT,
    build_feed_handshake_request_v0,
    classify_provider_access_v0,
    run_provider_access_preflight_v0,
)


OK_RPC = {"ok": True, "http_status": 200}
OK_FEED = {"ok": True, "http_status": 101}


class RobinhoodProviderAccessPreflightV0Tests(unittest.TestCase):
    def test_baseline_pass_wins_when_existing_transport_is_accessible(self):
        self.assertEqual(
            classify_provider_access_v0(OK_RPC, OK_FEED, OK_RPC, OK_FEED),
            "PASS_ROBINHOOD_PROVIDER_ACCESS_BASELINE_V0",
        )

    def test_identified_client_pass_is_distinct_from_baseline(self):
        denied = {"ok": False, "http_status": 403}
        self.assertEqual(
            classify_provider_access_v0(denied, denied, OK_RPC, OK_FEED),
            "PASS_ROBINHOOD_PROVIDER_ACCESS_IDENTIFIED_CLIENT_V0",
        )

    def test_identified_403_is_provider_access_denied(self):
        denied = {"ok": False, "http_status": 403}
        self.assertEqual(
            classify_provider_access_v0(denied, denied, denied, denied),
            "FAIL_ROBINHOOD_PROVIDER_ACCESS_DENIED_V0",
        )

    def test_identified_429_is_inconclusive_rate_limit(self):
        limited = {"ok": False, "http_status": 429}
        self.assertEqual(
            classify_provider_access_v0(limited, OK_FEED, limited, OK_FEED),
            "INCONCLUSIVE_ROBINHOOD_PROVIDER_RATE_LIMITED_V0",
        )

    def test_feed_handshake_ab_diff_is_only_explicit_user_agent(self):
        kwargs = {
            "feed_url": "wss://feed.mainnet.chain.robinhood.com",
            "requested_sequence_number": 0,
            "websocket_key": "dGVzdGtleXRlc3RrZXk=",
        }
        baseline = build_feed_handshake_request_v0(**kwargs).decode("ascii")
        identified = build_feed_handshake_request_v0(**kwargs, user_agent=USER_AGENT).decode("ascii")
        self.assertNotIn("User-Agent:", baseline)
        self.assertIn(f"User-Agent: {USER_AGENT}\r\n", identified)
        self.assertIn("Arbitrum-Feed-Client-Version: 2\r\n", baseline)
        self.assertIn("Arbitrum-Requested-Sequence-Number: 0\r\n", baseline)
        self.assertNotIn("Sec-WebSocket-Extensions", baseline)

    def test_report_redacts_provider_path_and_runs_same_session_ab(self):
        calls = []

        def rpc_probe(url, *, timeout_seconds, user_agent):
            calls.append(("rpc", user_agent))
            return {"ok": True, "http_status": 200, "chain_id": 4663}

        def feed_probe(url, *, timeout_seconds, user_agent):
            calls.append(("feed", user_agent))
            return {"ok": True, "http_status": 101, "chain_id": 4663}

        report = run_provider_access_preflight_v0(
            rpc_url="https://provider.example/v2/SECRET_KEY?x=SECRET_QUERY",
            feed_url="wss://feed.example/private/SECRET?token=SECRET_QUERY",
            rpc_probe=rpc_probe,
            feed_probe=feed_probe,
        )
        rendered = str(report)
        self.assertEqual(report["classification"], "PASS_ROBINHOOD_PROVIDER_ACCESS_BASELINE_V0")
        self.assertEqual(
            calls,
            [("rpc", None), ("feed", None), ("rpc", USER_AGENT), ("feed", USER_AGENT)],
        )
        self.assertTrue(report["rpc_endpoint"]["path_redacted"])
        self.assertTrue(report["rpc_endpoint"]["query_redacted"])
        self.assertTrue(report["feed_endpoint"]["path_redacted"])
        self.assertTrue(report["feed_endpoint"]["query_redacted"])
        self.assertNotIn("SECRET_KEY", rendered)
        self.assertNotIn("SECRET_QUERY", rendered)


if __name__ == "__main__":
    unittest.main()
