import base64
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.robinhood_sequencer_shadow_v0.classify_bootstrap import classify_capture_v0
from src.robinhood_nitro_bootstrap_v0 import (
    BACKLOG_CONFIRMED,
    LIVE_CANDIDATE,
    UNKNOWN_BLOCK_UNRESOLVED,
    UNKNOWN_NO_BLOCK_HASH,
)


ANCHOR_HASH = "0x" + "aa" * 32
BACKLOG_HASH = "0x" + "bb" * 32
LIVE_HASH = "0x" + "cc" * 32
ERROR_HASH = "0x" + "dd" * 32


def _frame(sequence, block_hash, observed_at_ns):
    payload = {
        "version": 1,
        "messages": [{
            "sequenceNumber": sequence,
            "message": {
                "message": {
                    "header": {
                        "kind": 3,
                        "sender": "0x" + "11" * 20,
                        "blockNumber": 1,
                        "timestamp": 2,
                        "requestId": None,
                        "baseFeeL1": 0,
                    },
                    "l2Msg": base64.b64encode(b"\x00").decode(),
                },
                "delayedMessagesRead": 0,
            },
            "blockHash": block_hash,
            "signatureV2": None,
        }],
    }
    return {
        "capture_version": "robinhood_sequencer_shadow_capture_v0",
        "connection_index": 1,
        "requested_sequence_number": 0,
        "observed_at_ns": observed_at_ns,
        "raw_text": json.dumps(payload, separators=(",", ":")),
    }


class FakeRpc:
    def __init__(self, *, anchor_hash=ANCHOR_HASH, fail_hash=None):
        self.anchor_hash = anchor_hash
        self.fail_hash = fail_hash
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_getBlockByNumber":
            return {"number": "0x64", "hash": self.anchor_hash}
        if method == "eth_getBlockByHash":
            block_hash = params[0]
            if block_hash == self.fail_hash:
                raise RuntimeError("provider lookup failed")
            if block_hash == BACKLOG_HASH:
                return {"number": "0x64", "hash": BACKLOG_HASH}
            if block_hash == LIVE_HASH:
                return {"number": "0x65", "hash": LIVE_HASH}
            return None
        raise AssertionError((method, params))


class RobinhoodSequencerBootstrapClassifierV0Tests(unittest.TestCase):
    def _make_run(self, root: Path, frames):
        run_dir = root / "run"
        run_dir.mkdir()
        report = {
            "capture_version": "robinhood_sequencer_shadow_capture_v0",
            "run_id": "fixture-run",
            "rpc_url": "https://example.invalid",
            "pre_handshake_anchor": {
                "block_number": 100,
                "block_hash": ANCHOR_HASH,
                "block_timestamp_s": 1_000,
                "captured_at_ns": 1_000,
            },
        }
        (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
        with (run_dir / "raw-frames.jsonl").open("w", encoding="utf-8") as handle:
            for frame in frames:
                handle.write(json.dumps(frame) + "\n")
        return run_dir

    def test_backlog_and_live_are_causally_classified_without_opening_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._make_run(
                Path(directory),
                [
                    _frame(1, BACKLOG_HASH, 2_000),
                    _frame(2, LIVE_HASH, 3_000),
                ],
            )
            report = classify_capture_v0(run_dir=run_dir, rpc_client=FakeRpc())
            self.assertEqual(report["classification"], "PASS_BOOTSTRAP_CLASSIFICATION")
            self.assertTrue(report["anchor_reorg_guard_passed"])
            self.assertEqual(report["messages_seen"], 2)
            self.assertEqual(report["latency_eligible_messages"], 1)
            self.assertEqual(report["classification_counts"][BACKLOG_CONFIRMED], 1)
            self.assertEqual(report["classification_counts"][LIVE_CANDIDATE], 1)
            self.assertEqual(report["causally_classified_messages"], 2)
            self.assertEqual(report["unknown_messages"], 0)
            self.assertEqual(report["causal_classification_coverage_pct"], 100.0)
            self.assertFalse(report["execution_confirmed"])
            self.assertFalse(report["economic_outcomes_opened"])
            self.assertFalse(report["latency_claim_opened"])

            rows = [
                json.loads(line)
                for line in (run_dir / "bootstrap-classifications.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            live = next(row for row in rows if row["classification"] == LIVE_CANDIDATE)
            self.assertEqual(live["feed_observed_at_ns"], 3_000)
            self.assertTrue(live["eligible_for_feed_latency"])

    def test_null_block_resolution_fails_closed_not_no_live_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            unknown_hash = "0x" + "ee" * 32
            run_dir = self._make_run(
                Path(directory), [_frame(1, unknown_hash, 2_000)]
            )
            report = classify_capture_v0(run_dir=run_dir, rpc_client=FakeRpc())
            self.assertEqual(
                report["classification"],
                "FAIL_BOOTSTRAP_BLOCK_RESOLUTION_ERRORS",
            )
            self.assertEqual(report["block_resolution_errors"], 0)
            self.assertEqual(report["latency_eligible_messages"], 0)
            self.assertEqual(
                report["classification_counts"][UNKNOWN_BLOCK_UNRESOLVED], 1
            )

    def test_block_resolution_exception_fails_closed_not_run_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._make_run(
                Path(directory), [_frame(1, ERROR_HASH, 2_000)]
            )
            report = classify_capture_v0(
                run_dir=run_dir,
                rpc_client=FakeRpc(fail_hash=ERROR_HASH),
            )
            self.assertEqual(
                report["classification"],
                "FAIL_BOOTSTRAP_BLOCK_RESOLUTION_ERRORS",
            )
            self.assertEqual(report["block_resolution_errors"], 1)
            self.assertEqual(report["latency_eligible_messages"], 0)
            self.assertEqual(
                report["classification_counts"][UNKNOWN_BLOCK_UNRESOLVED], 1
            )
            self.assertEqual(len(report["block_resolution_error_samples"]), 1)

    def test_anchor_reorg_guard_disables_all_latency_eligibility(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._make_run(
                Path(directory), [_frame(1, LIVE_HASH, 2_000)]
            )
            report = classify_capture_v0(
                run_dir=run_dir,
                rpc_client=FakeRpc(anchor_hash="0x" + "ff" * 32),
            )
            self.assertEqual(report["classification"], "FAIL_ANCHOR_REORG_GUARD")
            self.assertFalse(report["anchor_reorg_guard_passed"])
            self.assertEqual(report["latency_eligible_messages"], 0)
            row = json.loads(
                (run_dir / "bootstrap-classifications.jsonl")
                .read_text(encoding="utf-8")
                .strip()
            )
            self.assertEqual(row["classification"], LIVE_CANDIDATE)
            self.assertFalse(row["eligible_for_feed_latency"])
            self.assertFalse(row["anchor_reorg_guard_passed"])

    def test_malformed_frame_fails_closed_even_when_another_row_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._make_run(
                Path(directory), [_frame(1, LIVE_HASH, 2_000)]
            )
            with (run_dir / "raw-frames.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")
            report = classify_capture_v0(run_dir=run_dir, rpc_client=FakeRpc())
            self.assertEqual(report["messages_seen"], 1)
            self.assertEqual(report["parse_errors"], 1)
            self.assertEqual(report["latency_eligible_messages"], 1)
            self.assertEqual(report["classification"], "FAIL_BOOTSTRAP_PARSE_ERRORS")

    def test_all_hashless_messages_hold_for_causal_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._make_run(
                Path(directory), [_frame(1, None, 2_000)]
            )
            report = classify_capture_v0(run_dir=run_dir, rpc_client=FakeRpc())
            self.assertEqual(
                report["classification"],
                "HOLD_BOOTSTRAP_NO_CAUSAL_BLOCK_HASH_COVERAGE",
            )
            self.assertEqual(report["messages_seen"], 1)
            self.assertEqual(report["classification_counts"][UNKNOWN_NO_BLOCK_HASH], 1)
            self.assertEqual(report["causally_classified_messages"], 0)
            self.assertEqual(report["unknown_messages"], 1)
            self.assertEqual(report["causal_classification_coverage_pct"], 0.0)
            self.assertEqual(report["latency_eligible_messages"], 0)


if __name__ == "__main__":
    unittest.main()
