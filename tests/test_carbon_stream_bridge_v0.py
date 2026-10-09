import unittest

from benchmarks.carbon_stream_bridge_v0.benchmark import (
    BUY_EVENT_DISCRIMINATOR,
    P95_GATE_MS,
    P99_GATE_MS,
    classify,
    input_row,
    synthetic_pumpswap_buy_payload,
)


class CarbonStreamBridgeV0Tests(unittest.TestCase):
    def test_synthetic_buy_payload_has_exact_event_discriminator(self):
        payload = synthetic_pumpswap_buy_payload(7)
        self.assertGreater(len(payload), 8)
        self.assertEqual(payload[:8], BUY_EVENT_DISCRIMINATOR)

    def test_input_contract_is_carbon_decoder_input(self):
        row = input_row(3)
        self.assertEqual(row["type"], "carbon_decoder_input")
        self.assertEqual(row["event_type"], "pumpswap_buy")
        self.assertTrue(row["payload_base64"])

    def test_classification_requires_accounting_order_rate_and_latency(self):
        report = {
            "ready_received": True,
            "input_events": 5000,
            "decoded_events": 5000,
            "decode_failures": 0,
            "input_errors": 0,
            "order_violations": 0,
            "footer_accounting_valid": True,
            "achieved_ingress_events_per_second": 5000.0,
            "target_ingress_events_per_second": 5000.0,
            "round_trip_latency_ms": {"p95": P95_GATE_MS, "p99": P99_GATE_MS},
        }
        self.assertEqual(classify(report), "PASS_CARBON_STREAM_BRIDGE_V0")
        report["order_violations"] = 1
        self.assertEqual(
            classify(report), "REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V0"
        )


if __name__ == "__main__":
    unittest.main()
