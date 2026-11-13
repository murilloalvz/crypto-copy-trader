import unittest

from benchmarks.carbon_kernel_ingress_v1.benchmark import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_BATCH_WAIT_MS,
    P95_GATE_MS,
    P99_GATE_MS,
    classify,
)


class CarbonKernelIngressV1Tests(unittest.TestCase):
    def _passing_report(self):
        return {
            "ready_received": True,
            "transport": "ndjson_stdio_microbatch_v1",
            "input_events": 5000,
            "decoded_events": 5000,
            "matched_unit_adapted_events": 5000,
            "market_trade_adapted_events": 5000,
            "kernel_trade_events_ingested": 5000,
            "decode_failures": 0,
            "input_errors": 0,
            "semantic_errors": 0,
            "order_violations": 0,
            "footer_accounting_valid": True,
            "observed_max_batch_size": DEFAULT_BATCH_SIZE,
            "configured_batch_size": DEFAULT_BATCH_SIZE,
            "achieved_ingress_events_per_second": 5000.0,
            "target_ingress_events_per_second": 5000.0,
            "source_to_kernel_latency_ms": {"p95": P95_GATE_MS, "p99": P99_GATE_MS},
        }

    def test_frozen_integrated_contract(self):
        self.assertEqual(DEFAULT_BATCH_SIZE, 16)
        self.assertEqual(DEFAULT_MAX_BATCH_WAIT_MS, 1.0)
        self.assertEqual(P95_GATE_MS, 25.0)
        self.assertEqual(P99_GATE_MS, 75.0)

    def test_pass_requires_full_decode_adapt_and_kernel_accounting(self):
        report = self._passing_report()
        self.assertEqual(classify(report), "PASS_CARBON_KERNEL_INGRESS_V1")
        report["market_trade_adapted_events"] = 4999
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_KERNEL_INGRESS_V1")

    def test_pass_rejects_semantic_or_order_error(self):
        report = self._passing_report()
        report["semantic_errors"] = 1
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_KERNEL_INGRESS_V1")
        report = self._passing_report()
        report["order_violations"] = 1
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_KERNEL_INGRESS_V1")

    def test_pass_rejects_latency_or_oversized_batch(self):
        report = self._passing_report()
        report["source_to_kernel_latency_ms"]["p95"] = P95_GATE_MS + 0.001
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_KERNEL_INGRESS_V1")
        report = self._passing_report()
        report["observed_max_batch_size"] = DEFAULT_BATCH_SIZE + 1
        self.assertEqual(classify(report), "REJECT_OR_INVESTIGATE_CARBON_KERNEL_INGRESS_V1")


if __name__ == "__main__":
    unittest.main()
