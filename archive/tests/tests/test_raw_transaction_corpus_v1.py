import unittest

from benchmarks.raw_transaction_corpus_v1.capture import (
    PUMP_PROGRAM_ID,
    RawIngressObservation,
    build_logs_subscribe_request,
    parse_raw_logs_notification,
)


class RawTransactionCorpusV1Tests(unittest.TestCase):
    def test_build_logs_subscribe_request_is_program_scoped(self):
        payload = build_logs_subscribe_request(
            request_id=7,
            program_id=PUMP_PROGRAM_ID,
            commitment="confirmed",
        )
        self.assertEqual(payload["id"], 7)
        self.assertEqual(payload["params"][0]["mentions"], [PUMP_PROGRAM_ID])

    def test_parse_raw_notification_preserves_fine_receipt_clocks(self):
        message = {
            "method": "logsNotification",
            "params": {
                "subscription": 12,
                "result": {
                    "context": {"slot": 99},
                    "value": {
                        "err": None,
                        "signature": "sig",
                        "logs": ["Program log: x"],
                    },
                },
            },
        }
        item = parse_raw_logs_notification(
            message,
            sequence=3,
            venue="pump",
            program_id=PUMP_PROGRAM_ID,
            wall_observed_at_ns=1234567890123,
            monotonic_observed_at_ns=444,
        )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.sequence, 3)
        self.assertEqual(item.slot, 99)
        self.assertEqual(item.wall_observed_at_ns, 1234567890123)
        self.assertEqual(item.monotonic_observed_at_ns, 444)
        self.assertEqual(item.logs, ("Program log: x",))

    def test_failed_transaction_notification_is_ignored(self):
        message = {
            "method": "logsNotification",
            "params": {
                "subscription": 12,
                "result": {
                    "context": {"slot": 99},
                    "value": {
                        "err": {"InstructionError": [0, "Custom"]},
                        "signature": "sig",
                        "logs": [],
                    },
                },
            },
        }
        self.assertIsNone(
            parse_raw_logs_notification(
                message,
                sequence=0,
                venue="pump",
                program_id=PUMP_PROGRAM_ID,
                wall_observed_at_ns=10,
                monotonic_observed_at_ns=10,
            )
        )

    def test_observation_rejects_invalid_venue(self):
        with self.assertRaises(ValueError):
            RawIngressObservation(
                sequence=0,
                venue="other",
                program_id=PUMP_PROGRAM_ID,
                signature="sig",
                slot=1,
                wall_observed_at_ns=1,
                monotonic_observed_at_ns=1,
                logs=(),
            )


if __name__ == "__main__":
    unittest.main()
