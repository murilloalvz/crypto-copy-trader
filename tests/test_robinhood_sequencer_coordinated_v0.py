import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.robinhood_sequencer_shadow_v0.coordinated import (
    build_child_commands_v0,
    run_coordinated_shadow_v0,
)


class FakeProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class ArtifactPopenFactory:
    def __init__(self, *, rpc_classification=None, feed_classification=None):
        self.rpc_classification = (
            rpc_classification
            or "PASS_ROBINHOOD_LAUNCH_BURST_CAPTURE_V0_NO_NATIVE_LAUNCHES"
        )
        self.feed_classification = feed_classification or "PASS_RAW_CAPTURE"
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        module = command[command.index("-m") + 1]
        artifacts_root = Path(command[command.index("--artifacts-root") + 1])
        child = artifacts_root / ("rpc-fixture" if "launch_burst_v0.live" in module else "feed-fixture")
        child.mkdir(parents=True)
        classification = (
            self.rpc_classification
            if "launch_burst_v0.live" in module
            else self.feed_classification
        )
        report = {"classification": classification}
        (child / "report.json").write_text(json.dumps(report), encoding="utf-8")
        if "sequencer_shadow_v0.capture" in module:
            (child / "raw-frames.jsonl").write_text("", encoding="utf-8")
        return FakeProcess(0)


def _bootstrap(*, eligible=1, classification="PASS_BOOTSTRAP_CLASSIFICATION", anchor=True):
    def classify(**kwargs):
        return {
            "classification": classification,
            "anchor_reorg_guard_passed": anchor,
            "latency_eligible_messages": eligible,
        }
    return classify


class RobinhoodSequencerCoordinatedV0Tests(unittest.TestCase):
    def test_child_commands_keep_rpc_and_feed_on_same_requested_window(self):
        rpc, feed = build_child_commands_v0(
            python_executable="python",
            duration_seconds=180,
            poll_ms=350,
            rpc_url="https://rpc.example",
            feed_url="wss://feed.example",
            rpc_artifacts_root=Path("rpc-root"),
            feed_artifacts_root=Path("feed-root"),
            factory_address="0x" + "11" * 20,
        )
        self.assertIn("benchmarks.robinhood_launch_burst_v0.live", rpc)
        self.assertIn("benchmarks.robinhood_sequencer_shadow_v0.capture", feed)
        self.assertEqual(rpc[rpc.index("--duration-seconds") + 1], "180")
        self.assertEqual(feed[feed.index("--duration-seconds") + 1], "180")
        self.assertEqual(feed[feed.index("--initial-requested-sequence") + 1], "0")
        self.assertIn("--factory-address", rpc)
        self.assertNotIn("--factory-address", feed)

    def test_coordinated_pass_requires_both_child_reports_and_live_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = ArtifactPopenFactory()
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                child_timeout_slack_seconds=1,
                popen_factory=factory,
                bootstrap_classifier=_bootstrap(eligible=3),
            )
            self.assertEqual(report["classification"], "PASS_COORDINATED_SHADOW_ACQUISITION_V0")
            self.assertEqual(report["bootstrap_latency_eligible_messages"], 3)
            self.assertFalse(report["execution_reconciliation_opened"])
            self.assertFalse(report["latency_claim_opened"])
            self.assertFalse(report["economic_outcomes_opened"])
            self.assertEqual(len(factory.commands), 2)

    def test_zero_live_candidates_is_pass_without_latency_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(),
                bootstrap_classifier=_bootstrap(eligible=0),
            )
            self.assertEqual(
                report["classification"],
                "PASS_COORDINATED_SHADOW_ACQUISITION_V0_NO_LIVE_CANDIDATES",
            )
            self.assertEqual(report["bootstrap_latency_eligible_messages"], 0)

    def test_feed_report_failure_cannot_be_promoted_by_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(feed_classification="FAIL_NO_FEED_FRAMES"),
                bootstrap_classifier=_bootstrap(eligible=1),
            )
            self.assertEqual(report["classification"], "FAIL_COORDINATED_SHADOW_FEED_CAPTURE")

    def test_rpc_report_failure_cannot_be_promoted_by_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(rpc_classification="FAIL_RPC_CAPTURE"),
                bootstrap_classifier=_bootstrap(eligible=1),
            )
            self.assertEqual(report["classification"], "FAIL_COORDINATED_SHADOW_RPC_CAPTURE")

    def test_anchor_guard_failure_blocks_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(),
                bootstrap_classifier=_bootstrap(
                    eligible=1,
                    classification="FAIL_ANCHOR_REORG_GUARD",
                    anchor=False,
                ),
            )
            self.assertEqual(
                report["classification"],
                "FAIL_COORDINATED_SHADOW_BOOTSTRAP_CLASSIFICATION",
            )


if __name__ == "__main__":
    unittest.main()
