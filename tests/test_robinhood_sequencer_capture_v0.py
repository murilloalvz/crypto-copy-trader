import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.robinhood_sequencer_shadow_v0.capture import (
    CAPTURE_VERSION,
    JsonRpcClientV0,
    SequenceTrackerV0,
    _existing_capture_run_dirs_v0,
    _persist_cli_failure_report_v0,
)


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class RobinhoodSequencerCaptureV0Tests(unittest.TestCase):
    def test_contiguous_sequences_advance_reconnect_cursor(self):
        tracker = SequenceTrackerV0()
        for value in (100, 101, 102):
            tracker.observe(value)
        row = tracker.to_dict()
        self.assertEqual(row["message_count"], 3)
        self.assertEqual(row["first_sequence"], 100)
        self.assertEqual(row["last_sequence"], 102)
        self.assertEqual(row["next_requested_sequence"], 103)
        self.assertEqual(row["missing_sequence_count"], 0)
        self.assertEqual(row["duplicate_or_reordered_count"], 0)
        self.assertEqual(row["gaps"], [])

    def test_gap_is_counted_exactly_and_cursor_moves_to_new_high_watermark(self):
        tracker = SequenceTrackerV0()
        tracker.observe(10)
        tracker.observe(14)
        row = tracker.to_dict()
        self.assertEqual(row["missing_sequence_count"], 3)
        self.assertEqual(
            row["gaps"],
            [{
                "after_sequence": 10,
                "next_observed_sequence": 14,
                "missing_count": 3,
            }],
        )
        self.assertEqual(row["last_sequence"], 14)
        self.assertEqual(row["next_requested_sequence"], 15)

    def test_duplicate_or_reordered_sequence_does_not_move_high_watermark(self):
        tracker = SequenceTrackerV0()
        for value in (20, 21, 21, 19, 22):
            tracker.observe(value)
        row = tracker.to_dict()
        self.assertEqual(row["message_count"], 5)
        self.assertEqual(row["duplicate_or_reordered_count"], 2)
        self.assertEqual(row["last_sequence"], 22)
        self.assertEqual(row["next_requested_sequence"], 23)
        self.assertEqual(row["missing_sequence_count"], 0)

    def test_empty_tracker_has_no_reconnect_cursor(self):
        tracker = SequenceTrackerV0()
        self.assertIsNone(tracker.next_requested_sequence)
        self.assertIsNone(tracker.to_dict()["first_sequence"])

    def test_negative_sequence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            SequenceTrackerV0().observe(-1)

    def test_rpc_transport_failure_includes_method_name(self):
        client = JsonRpcClientV0("https://rpc.example")
        with patch(
            "benchmarks.robinhood_sequencer_shadow_v0.capture.urlopen",
            side_effect=OSError("synthetic transport failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "eth_chainId transport/response failure: OSError:synthetic transport failure",
            ):
                client.call("eth_chainId", [])

    def test_rpc_error_payload_includes_method_name(self):
        client = JsonRpcClientV0("https://rpc.example")
        response = FakeHttpResponse({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "synthetic rpc failure"},
        })
        with patch(
            "benchmarks.robinhood_sequencer_shadow_v0.capture.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "eth_chainId JSON-RPC error"):
                client.call("eth_chainId", [])

    def test_invalid_chain_id_result_has_method_context(self):
        client = JsonRpcClientV0("https://rpc.example")
        response = FakeHttpResponse({"jsonrpc": "2.0", "id": 1, "result": None})
        with patch(
            "benchmarks.robinhood_sequencer_shadow_v0.capture.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "eth_chainId invalid result"):
                client.chain_id()

    def test_cli_preflight_failure_is_persisted_into_the_single_new_run_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_run = root / f"{CAPTURE_VERSION}-old"
            old_run.mkdir()
            before = _existing_capture_run_dirs_v0(root)
            new_run = root / f"{CAPTURE_VERSION}-new"
            new_run.mkdir()
            result = {
                "capture_version": CAPTURE_VERSION,
                "classification": "FAIL_CAPTURE_PREFLIGHT",
                "error": "RuntimeError:synthetic",
            }

            persisted = _persist_cli_failure_report_v0(
                artifacts_root=root,
                before_run_dirs=before,
                result=result,
            )

            self.assertEqual(persisted, new_run)
            self.assertTrue(result["artifact_report_persisted"])
            self.assertEqual(result["run_dir"], str(new_run))
            report = json.loads((new_run / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["classification"], "FAIL_CAPTURE_PREFLIGHT")
            self.assertEqual(report["error"], "RuntimeError:synthetic")

    def test_cli_failure_persistence_fails_closed_when_new_run_dir_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = _existing_capture_run_dirs_v0(root)
            first = root / f"{CAPTURE_VERSION}-one"
            second = root / f"{CAPTURE_VERSION}-two"
            first.mkdir()
            second.mkdir()
            result = {
                "capture_version": CAPTURE_VERSION,
                "classification": "FAIL_CAPTURE_PREFLIGHT",
            }

            persisted = _persist_cli_failure_report_v0(
                artifacts_root=root,
                before_run_dirs=before,
                result=result,
            )

            self.assertIsNone(persisted)
            self.assertFalse(result["artifact_report_persisted"])
            self.assertIn("found 2", result["artifact_report_persist_error"])
            self.assertFalse((first / "report.json").exists())
            self.assertFalse((second / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
