import base64
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.carbon_decoder_parity_v1.parity import PUMP_TRADE_EVENT_DISCRIMINATOR
from benchmarks.helius_standard_wss_shadow_v0 import TRACE_VERSION
from benchmarks.helius_standard_wss_shadow_v0.collect import PUMP_PROGRAM_ID
from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow


class HeliusStandardWssShadowReduceV0Tests(unittest.TestCase):
    def _event_logs(self):
        payload = PUMP_TRADE_EVENT_DISCRIMINATOR + b"synthetic-payload"
        encoded = base64.b64encode(payload).decode("ascii")
        return [
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            f"Program data: {encoded}",
            f"Program {PUMP_PROGRAM_ID} success",
        ]

    def _event_data_line(self, suffix=b"synthetic-payload"):
        payload = PUMP_TRADE_EVENT_DISCRIMINATOR + suffix
        return "Program data: " + base64.b64encode(payload).decode("ascii")

    def _write_trace(self, path: Path, rows):
        path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _header(self, **overrides):
        row = {
            "type": "trace_header",
            "version": TRACE_VERSION,
            "chain_complete_coverage_claimed": False,
        }
        row.update(overrides)
        return row

    def _footer(self, **overrides):
        row = {
            "type": "trace_footer",
            "version": TRACE_VERSION,
            "chain_complete_coverage_claimed": False,
        }
        row.update(overrides)
        return row

    def _notification(self, **overrides):
        row = {
            "type": "logs_notification",
            "version": TRACE_VERSION,
            "session_key": "session-0001",
            "received_wall_ns": 1_000_000_000,
            "subscription_label": "pump_logs",
            "slot": 123,
            "signature": "SIG_A",
            "err": None,
            "logs": self._event_logs(),
        }
        row.update(overrides)
        return row

    def test_reuses_contextual_parser_and_emits_carbon_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), self._notification(), self._footer()])
            report = reduce_shadow(
                trace_path=trace,
                carbon_input_path=carbon,
                manifest_path=manifest,
            )
            carbon_rows = [json.loads(line) for line in carbon.read_text(encoding="utf-8").splitlines()]
            manifest_rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(report["trace_contract_valid"])
        self.assertTrue(report["valid_for_carbon_decode"])
        self.assertEqual(report["accepted_success_target_events"], 1)
        self.assertEqual(report["program_log_stack_errors"], 0)
        self.assertEqual(report["successful_tx_stack_errors"], 0)
        self.assertEqual(report["failed_tx_stack_errors"], 0)
        self.assertEqual(report["successful_tx_unexplained_stack_anomalies"], 0)
        self.assertEqual(carbon_rows[0]["event_type"], "pump_trade")
        self.assertTrue(manifest_rows[0]["transaction_log_complete"])
        self.assertTrue(manifest_rows[0]["eligible_for_complete_transaction_inference"])

    def test_duplicate_notification_keeps_first_observation_and_one_carbon_event(self):
        first = self._notification(received_wall_ns=1_000_000_000)
        later = self._notification(received_wall_ns=2_000_000_000)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), later, first, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
            carbon_rows = carbon.read_text(encoding="utf-8").splitlines()
            manifest_row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(len(carbon_rows), 1)
        self.assertEqual(manifest_row["first_received_wall_ns"], 1_000_000_000)
        self.assertEqual(report["duplicate_notifications"], 1)

    def test_failed_transaction_target_is_audited_but_not_sent_to_market_decode(self):
        failed = self._notification(
            signature="SIG_FAIL",
            err={"InstructionError": [1, "Custom"]},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), failed, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
            carbon_text = carbon.read_text(encoding="utf-8")
            manifest_row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(carbon_text, "")
        self.assertEqual(report["failed_transaction_target_events"], 1)
        self.assertFalse(report["valid_for_carbon_decode"])
        self.assertFalse(manifest_row["accepted_for_market_research"])

    def test_trace_claiming_chain_completeness_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(
                trace,
                [
                    self._header(chain_complete_coverage_claimed=True),
                    self._notification(),
                    self._footer(),
                ],
            )
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
        self.assertFalse(report["trace_contract_valid"])
        self.assertFalse(report["valid_for_carbon_decode"])

    def test_program_stack_error_blocks_carbon_decode_validity(self):
        malformed_logs = [
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            self._event_data_line(b"x"),
        ]
        row = self._notification(logs=malformed_logs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), row, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
        self.assertGreater(report["program_log_stack_errors"], 0)
        self.assertGreater(report["successful_tx_stack_errors"], 0)
        self.assertGreater(report["successful_tx_unexplained_stack_anomalies"], 0)
        self.assertFalse(report["valid_for_carbon_decode"])

    def test_failed_tx_stack_error_is_audited_without_poisoning_successful_input(self):
        malformed_failed_logs = [
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            self._event_data_line(b"failed-synthetic-payload"),
        ]
        succeeded = self._notification(signature="SIG_OK", received_wall_ns=1_000_000_000)
        failed = self._notification(
            signature="SIG_FAIL",
            received_wall_ns=2_000_000_000,
            err={"InstructionError": [1, "Custom"]},
            logs=malformed_failed_logs,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), succeeded, failed, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
            carbon_rows = carbon.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(carbon_rows), 1)
        self.assertEqual(report["accepted_success_target_events"], 1)
        self.assertEqual(report["failed_transaction_target_events"], 1)
        self.assertEqual(report["program_log_stack_errors"], 1)
        self.assertEqual(report["successful_tx_stack_errors"], 0)
        self.assertEqual(report["failed_tx_stack_errors"], 1)
        self.assertTrue(report["valid_for_carbon_decode"])

    def test_successful_truncation_is_explicit_missingness_not_parser_failure(self):
        truncated_logs = [
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            self._event_data_line(b"before-truncation"),
            "Log truncated",
        ]
        row = self._notification(logs=truncated_logs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), row, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
            carbon_rows = carbon.read_text(encoding="utf-8").splitlines()
            manifest_row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(report["truncated_notifications"], 1)
        self.assertEqual(report["successful_truncated_notifications"], 1)
        self.assertEqual(report["program_log_stack_errors"], 1)
        self.assertEqual(report["successful_tx_stack_errors"], 1)
        self.assertEqual(report["successful_tx_unexplained_stack_anomalies"], 0)
        self.assertEqual(len(carbon_rows), 1)
        self.assertTrue(report["valid_for_carbon_decode"])
        self.assertFalse(manifest_row["transaction_log_complete"])
        self.assertFalse(manifest_row["eligible_for_complete_transaction_inference"])
        self.assertEqual(manifest_row["first_truncation_log_index"], 2)

    def test_post_truncation_target_event_is_rejected_from_carbon_input(self):
        truncated_logs = [
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            self._event_data_line(b"safe-before"),
            "Log truncated",
            self._event_data_line(b"unsafe-after"),
            f"Program {PUMP_PROGRAM_ID} success",
        ]
        row = self._notification(logs=truncated_logs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), row, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)
            carbon_rows = carbon.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(carbon_rows), 1)
        self.assertEqual(report["post_truncation_target_events_rejected"], 1)
        self.assertEqual(report["accepted_success_target_events"], 1)
        self.assertTrue(report["valid_for_carbon_decode"])

    def test_pre_truncation_stack_anomaly_still_blocks_carbon_decode(self):
        unrelated_program = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        logs = [
            f"Program {unrelated_program} success",
            f"Program {PUMP_PROGRAM_ID} invoke [1]",
            self._event_data_line(b"event"),
            "Log truncated",
        ]
        row = self._notification(logs=logs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "trace.jsonl"
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            self._write_trace(trace, [self._header(), row, self._footer()])
            report = reduce_shadow(trace_path=trace, carbon_input_path=carbon, manifest_path=manifest)

        self.assertEqual(report["truncated_notifications"], 1)
        self.assertGreater(report["successful_tx_unexplained_stack_anomalies"], 0)
        self.assertFalse(report["valid_for_carbon_decode"])


if __name__ == "__main__":
    unittest.main()
