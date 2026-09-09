import unittest

from benchmarks.yellowstone_raw_stream_v2.capture import (
    CaptureCounters,
    _build_footer,
    endpoint_target,
)


class YellowstoneRawStreamV2Tests(unittest.TestCase):
    def test_endpoint_target_strips_path_query_and_secret_material(self):
        target, safe_host = endpoint_target(
            "https://example.rpc.invalid/private-token?api_key=secret"
        )
        self.assertEqual(target, "example.rpc.invalid:443")
        self.assertEqual(safe_host, "example.rpc.invalid")

    def test_footer_requires_transaction_and_zero_errors(self):
        counters = CaptureCounters(transaction_updates=2, bytes_protobuf=100)
        footer = _build_footer(
            counters,
            started_wall_ns=1_000_000_000,
            finished_wall_ns=2_000_000_000,
            first_transaction_wall_ns=1_100_000_000,
        )
        self.assertTrue(footer["valid_for_decoder_parity"])

        counters.stream_errors = 1
        footer = _build_footer(
            counters,
            started_wall_ns=1_000_000_000,
            finished_wall_ns=2_000_000_000,
            first_transaction_wall_ns=1_100_000_000,
        )
        self.assertFalse(footer["valid_for_decoder_parity"])

    def test_footer_rejects_empty_corpus(self):
        footer = _build_footer(
            CaptureCounters(),
            started_wall_ns=1,
            finished_wall_ns=2,
            first_transaction_wall_ns=None,
        )
        self.assertFalse(footer["valid_for_decoder_parity"])


if __name__ == "__main__":
    unittest.main()
