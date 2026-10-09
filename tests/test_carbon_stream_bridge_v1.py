import unittest

from benchmarks.carbon_stream_bridge_v1.benchmark import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_BATCH_WAIT_MS,
    P95_GATE_MS,
    P99_GATE_MS,
    classify,
)


class CarbonStreamBridgeV1Tests(unittest.TestCase):
    def _passing_report(self):
        return {
            "ready_received": True,
            "transport": "ndjson_stdio_microbatch_v1",
            "input_events": 5000,
            "decoded_events": 5000,
            "decode_failures": 0,
            "input_errors": 0,
            "order_violations": 0,
            "footer_accounting_valid": True,
            "observed_max_batch_size": DEFAULT_BATCH_SIZE,
            "configured_batch_size": DEFAULT_BATCH_SIZE,
            "achieved_ingress_events_per_second": 5000.0,
            "target_ingress_events_per_second": 5000.0,
            "round_trip_latency_ms": {"p95": P95_GATE_MS, "p99": P99_GATE_MS},
        }

    def test_frozen_transport_contract(self):
        self.assertEqual(DEFAULT_BATCH_SIZE, 16)
        self.assertEqual(DEFAULT_MAX_BATCH_WAIT_MS, 1.0)
        self.assertEqual(P95_GATE_MS, 25.0)
        self.assertEqual(P99_GATE_MS, 75.0)

    def test_classification_requires_exact_accounting_order_and_transport(self):
        report = self._passing_report()
        self.assertEqual(classify(report), "PASS_CARBON_STREAM_BRIDGE_V1")
        report["order_violations"] = 1
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V1")

    def test_classification_rejects_oversized_batch(self):
        report = self._passing_report()
        report["observed_max_batch_size"] = DEFAULT_BATCH_SIZE + 1
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V1")

    def test_classification_rejects_wrong_transport(self):
        report = self._passing_report()
        report["transport"] = "ndjson_stdio"
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V1")


if __name__ == "__main__":
    unittest.main()
