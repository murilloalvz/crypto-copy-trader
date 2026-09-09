import json
import unittest

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    COVERAGE_CLASSIFICATION,
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    classify_notification,
    helius_wss_url,
    redact_secret,
    subscription_payloads,
    trace_header,
)


class HeliusStandardWssShadowV0Tests(unittest.TestCase):
    def test_wss_url_uses_key_but_header_never_does(self):
        key = "secret/key+value"
        url = helius_wss_url(key)
        self.assertTrue(url.startswith("wss://mainnet.helius-rpc.com/?api-key="))
        self.assertNotIn("secret/key+value", url)

        header = trace_header(
            duration_seconds=60.0,
            max_log_notifications=100,
            started_wall_ns=123,
        )
        encoded = json.dumps(header)
        self.assertNotIn(key, encoded)
        self.assertFalse(header["api_key_embedded_in_trace"])
        self.assertFalse(header["chain_complete_coverage_claimed"])
        self.assertEqual(header["coverage_classification"], COVERAGE_CLASSIFICATION)

    def test_redaction_removes_raw_and_url_encoded_key(self):
        key = "secret/key+value"
        text = (
            "failed wss://mainnet.helius-rpc.com/?api-key=secret/key+value "
            "and api-key=secret%2Fkey%2Bvalue"
        )
        redacted = redact_secret(text, key)
        self.assertNotIn(key, redacted)
        self.assertNotIn("secret%2Fkey%2Bvalue", redacted)
        self.assertIn("<REDACTED>", redacted)

    def test_subscriptions_are_standard_logs_plus_slot_only(self):
        payloads = subscription_payloads()
        self.assertEqual([item["method"] for item in payloads], [
            "logsSubscribe",
            "logsSubscribe",
            "slotSubscribe",
        ])
        self.assertEqual(payloads[0]["params"][0], {"mentions": [PUMP_PROGRAM_ID]})
        self.assertEqual(payloads[1]["params"][0], {"mentions": [PUMPSWAP_PROGRAM_ID]})
        self.assertEqual(payloads[0]["params"][1]["commitment"], "processed")
        self.assertNotIn("transactionSubscribe", json.dumps(payloads))

    def test_pump_logs_notification_is_normalized(self):
        message = {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "subscription": 71,
                "result": {
                    "context": {"slot": 123},
                    "value": {
                        "signature": "SIG_A",
                        "err": None,
                        "logs": ["Program A invoke [1]", "Program A success"],
                    },
                },
            },
        }
        label, row = classify_notification(message, {71: "pump_logs"})
        self.assertEqual(label, "pump_logs")
        self.assertEqual(row["slot"], 123)
        self.assertEqual(row["signature"], "SIG_A")
        self.assertEqual(len(row["logs"]), 2)

    def test_failed_transaction_logs_are_preserved_not_silently_dropped(self):
        message = {
            "method": "logsNotification",
            "params": {
                "subscription": 72,
                "result": {
                    "context": {"slot": 124},
                    "value": {
                        "signature": "SIG_FAIL",
                        "err": {"InstructionError": [1, "Custom"]},
                        "logs": ["Program failed"],
                    },
                },
            },
        }
        label, row = classify_notification(message, {72: "pumpswap_logs"})
        self.assertEqual(label, "pumpswap_logs")
        self.assertIsNotNone(row["err"])

    def test_slot_notification_is_operational_liveness_only(self):
        message = {
            "method": "slotNotification",
            "params": {
                "subscription": 9,
                "result": {"parent": 998, "root": 990, "slot": 999},
            },
        }
        label, row = classify_notification(message, {9: "slot"})
        self.assertEqual(label, "slot")
        self.assertEqual(row["slot"], 999)
        self.assertEqual(row["root"], 990)

    def test_unknown_or_malformed_notifications_are_not_fabricated(self):
        samples = (
            ({"method": "logsNotification", "params": {"subscription": 777}}, {71: "pump_logs"}),
            ({"method": "logsNotification", "params": {"subscription": 71, "result": {}}}, {71: "pump_logs"}),
            ({"method": "slotNotification", "params": {"subscription": 9, "result": {"slot": True}}}, {9: "slot"}),
        )
        for message, labels in samples:
            with self.subTest(message=message):
                label, row = classify_notification(message, labels)
                self.assertIsNone(label)
                self.assertIsNone(row)

    def test_header_explicitly_refuses_chain_complete_coverage(self):
        header = trace_header(
            duration_seconds=300.0,
            max_log_notifications=5000,
            started_wall_ns=123,
        )
        self.assertEqual(
            header["coverage_classification"],
            "operational_only_not_chain_complete",
        )
        self.assertFalse(header["chain_complete_coverage_claimed"])
        self.assertTrue(
            any("not treated as proof" in note for note in header["notes"])
        )


if __name__ == "__main__":
    unittest.main()
