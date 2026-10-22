import unittest

from benchmarks.yellowstone_raw_stream_v2.capture import (
    CaptureCounters,
    _build_footer,
    _build_metadata,
    endpoint_connection,
    endpoint_target,
)


class YellowstoneRawStreamV2Tests(unittest.TestCase):
    def test_endpoint_target_strips_path_query_and_secret_material(self):
        target, safe_host = endpoint_target(
            "https://example.rpc.invalid/private-token?api_key=secret"
        )
        self.assertEqual(target, "example.rpc.invalid:443")
        self.assertEqual(safe_host, "example.rpc.invalid")

    def test_endpoint_connection_supports_tls_and_plaintext(self):
        self.assertEqual(
            endpoint_connection("https://grpc.example.invalid"),
            ("grpc.example.invalid:443", "grpc.example.invalid", True),
        )
        self.assertEqual(
            endpoint_connection("http://grpc.example.invalid:10000"),
            ("grpc.example.invalid:10000", "grpc.example.invalid", False),
        )

    def test_auth_metadata_supports_token_and_ip_allowlist(self):
        self.assertEqual(_build_metadata("none", ""), ())
        self.assertEqual(_build_metadata("x-token", "secret"), (("x-token", "secret"),))
        with self.assertRaises(ValueError):
            _build_metadata("x-token", "")

    def test_footer_requires_both_venues_and_zero_errors(self):
        counters = CaptureCounters(
            transaction_updates=2,
            pump_updates=1,
            pumpswap_updates=1,
            bytes_protobuf=100,
        )
        footer = _build_footer(
            counters,
            started_wall_ns=1_000_000_000,
            finished_wall_ns=2_000_000_000,
            first_transaction_wall_ns=1_100_000_000,
            stop_reason="max_transactions",
            max_transactions=500,
        )
        self.assertTrue(footer["valid_for_decoder_parity"])

        counters.stream_errors = 1
        footer = _build_footer(
            counters,
            started_wall_ns=1_000_000_000,
            finished_wall_ns=2_000_000_000,
            first_transaction_wall_ns=1_100_000_000,
            stop_reason="duration",
            max_transactions=500,
        )
        self.assertFalse(footer["valid_for_decoder_parity"])

    def test_footer_rejects_single_venue_corpus(self):
        footer = _build_footer(
            CaptureCounters(transaction_updates=1, pump_updates=1),
            started_wall_ns=1,
            finished_wall_ns=2,
            first_transaction_wall_ns=1,
            stop_reason="duration",
            max_transactions=500,
        )
        self.assertFalse(footer["valid_for_decoder_parity"])

    def test_footer_rejects_empty_corpus(self):
        footer = _build_footer(
            CaptureCounters(),
            started_wall_ns=1,
            finished_wall_ns=2,
            first_transaction_wall_ns=None,
            stop_reason="duration",
            max_transactions=500,
        )
        self.assertFalse(footer["valid_for_decoder_parity"])


if __name__ == "__main__":
    unittest.main()
