import json
from pathlib import Path
import tempfile
import time
import unittest

from benchmarks.robinhood_sequencer_shadow_v0.coordinated import (
    RPC_READY_VERSION,
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
    def __init__(
        self,
        *,
        rpc_classification=None,
        feed_classification=None,
        rpc_error=None,
        feed_error=None,
        rpc_ready=True,
    ):
        self.rpc_classification = (
            rpc_classification
            or "PASS_ROBINHOOD_LAUNCH_BURST_CAPTURE_V0_NO_NATIVE_LAUNCHES"
        )
        self.feed_classification = feed_classification or "PASS_RAW_CAPTURE"
        self.rpc_error = rpc_error
        self.feed_error = feed_error
        self.rpc_ready = rpc_ready
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        module = command[command.index("-m") + 1]
        artifacts_root = Path(command[command.index("--artifacts-root") + 1])
        is_rpc = "launch_burst_v0.live" in module
        child = artifacts_root / ("rpc-fixture" if is_rpc else "feed-fixture")
        child.mkdir(parents=True)
        classification = self.rpc_classification if is_rpc else self.feed_classification
        error = self.rpc_error if is_rpc else self.feed_error
        report = {"classification": classification}
        if error is not None:
            report["error"] = error
        if is_rpc:
            report["factory_discovery"] = {"classification": "SYNTHETIC_FACTORY_STATE"}
            report["transport_errors"] = []
            report["preflight_completed"] = self.rpc_ready
            if not self.rpc_ready:
                report["failure_stage"] = "preflight_factory_discovery"
            if self.rpc_ready:
                ready_path = Path(command[command.index("--ready-file") + 1])
                ready_path.write_text(
                    json.dumps(
                        {
                            "type": RPC_READY_VERSION,
                            "run_id": "rpc-fixture",
                            "run_dir": str(child),
                            "preflight_completed": True,
                            "capture_started_at_ns": time.time_ns(),
                            "initial_block": 100,
                            "factory": "0x" + "11" * 20,
                            "chain_id": 4663,
                            "economic_outcomes_opened": False,
                            "selector_frozen": False,
                        }
                    ),
                    encoding="utf-8",
                )
        else:
            report["frame_count"] = 1 if classification == "PASS_RAW_CAPTURE" else None
            report["transport_errors"] = []
            (child / "raw-frames.jsonl").write_text("", encoding="utf-8")
        (child / "report.json").write_text(json.dumps(report), encoding="utf-8")
        return FakeProcess(0)


def _bootstrap(
    *,
    eligible=1,
    classification="PASS_BOOTSTRAP_CLASSIFICATION",
    anchor=True,
    messages_seen=1,
    parse_errors=0,
    block_resolution_errors=0,
    coverage_pct=100.0,
):
    def classify(**kwargs):
        return {
            "classification": classification,
            "anchor_reorg_guard_passed": anchor,
            "messages_seen": messages_seen,
            "parse_errors": parse_errors,
            "block_resolution_errors": block_resolution_errors,
            "classification_counts": {},
            "causal_classification_coverage_pct": coverage_pct,
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
            rpc_ready_file=Path("rpc-ready.json"),
            factory_address="0x" + "11" * 20,
        )
        self.assertIn("benchmarks.robinhood_launch_burst_v0.live", rpc)
        self.assertIn("benchmarks.robinhood_sequencer_shadow_v0.capture", feed)
        self.assertEqual(rpc[rpc.index("--duration-seconds") + 1], "180")
        self.assertEqual(feed[feed.index("--duration-seconds") + 1], "180")
        self.assertEqual(feed[feed.index("--initial-requested-sequence") + 1], "0")
        self.assertEqual(rpc[rpc.index("--ready-file") + 1], "rpc-ready.json")
        self.assertIn("--factory-address", rpc)
        self.assertNotIn("--factory-address", feed)

    def test_coordinated_pass_requires_rpc_ready_and_both_child_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = ArtifactPopenFactory()
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=factory,
                bootstrap_classifier=_bootstrap(eligible=3),
            )
            self.assertEqual(report["classification"], "PASS_COORDINATED_SHADOW_ACQUISITION_V0")
            self.assertTrue(report["rpc_ready"])
            self.assertIsNone(report["rpc_ready_error"])
            self.assertIsNotNone(report["rpc_capture_started_at_ns"])
            self.assertIsNotNone(report["rpc_ready_to_feed_start_ms"])
            self.assertGreaterEqual(report["rpc_ready_to_feed_start_ms"], 0.0)
            self.assertEqual(report["bootstrap_latency_eligible_messages"], 3)
            self.assertEqual(report["bootstrap_messages_seen"], 1)
            self.assertEqual(report["bootstrap_parse_errors"], 0)
            self.assertEqual(report["bootstrap_block_resolution_errors"], 0)
            self.assertEqual(report["bootstrap_causal_classification_coverage_pct"], 100.0)
            self.assertFalse(report["execution_reconciliation_opened"])
            self.assertFalse(report["latency_claim_opened"])
            self.assertFalse(report["economic_outcomes_opened"])
            self.assertTrue(report["rpc_report_present"])
            self.assertTrue(report["feed_report_present"])
            self.assertEqual(len(factory.commands), 2)

    def test_rpc_not_ready_blocks_feed_start(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = ArtifactPopenFactory(
                rpc_classification="FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0",
                rpc_error="JsonRpcError:synthetic preflight failure",
                rpc_ready=False,
            )
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=factory,
                bootstrap_classifier=_bootstrap(eligible=1),
            )
            self.assertEqual(
                report["classification"],
                "FAIL_COORDINATED_SHADOW_RPC_READINESS",
            )
            self.assertFalse(report["rpc_ready"])
            self.assertIn("exited before readiness", report["rpc_ready_error"])
            self.assertIsNone(report["feed_started_at_ns"])
            self.assertIsNone(report["feed_return_code"])
            self.assertEqual(report["rpc_failure_stage"], "preflight_factory_discovery")
            self.assertEqual(len(factory.commands), 1)

    def test_zero_live_candidates_is_pass_only_after_clean_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(),
                bootstrap_classifier=_bootstrap(eligible=0),
            )
            self.assertEqual(
                report["classification"],
                "PASS_COORDINATED_SHADOW_ACQUISITION_V0_NO_LIVE_CANDIDATES",
            )
            self.assertEqual(report["bootstrap_latency_eligible_messages"], 0)
            self.assertEqual(report["bootstrap_parse_errors"], 0)
            self.assertEqual(report["bootstrap_block_resolution_errors"], 0)

    def test_feed_report_failure_cannot_be_promoted_by_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            bootstrap_calls = []

            def should_not_run(**kwargs):
                bootstrap_calls.append(kwargs)
                raise AssertionError("bootstrap must not run after failed raw capture")

            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(
                    feed_classification="FAIL_CAPTURE_PREFLIGHT",
                    feed_error="RuntimeError:feed preflight failed",
                ),
                bootstrap_classifier=should_not_run,
            )
            self.assertEqual(report["classification"], "FAIL_COORDINATED_SHADOW_FEED_CAPTURE")
            self.assertEqual(report["feed_capture_error"], "RuntimeError:feed preflight failed")
            self.assertEqual(bootstrap_calls, [])
            self.assertIsNone(report["bootstrap_error"])

    def test_rpc_report_failure_after_ready_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(
                    rpc_classification="FAIL_ROBINHOOD_LAUNCH_BURST_TRANSPORT_V0",
                    rpc_error="JsonRpcError:synthetic",
                    rpc_ready=True,
                ),
                bootstrap_classifier=_bootstrap(eligible=1),
            )
            self.assertEqual(report["classification"], "FAIL_COORDINATED_SHADOW_RPC_CAPTURE")
            self.assertEqual(report["rpc_capture_error"], "JsonRpcError:synthetic")
            self.assertEqual(
                report["rpc_factory_discovery"],
                {"classification": "SYNTHETIC_FACTORY_STATE"},
            )

    def test_anchor_guard_failure_has_specific_parent_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(),
                bootstrap_classifier=_bootstrap(
                    eligible=0,
                    classification="FAIL_ANCHOR_REORG_GUARD",
                    anchor=False,
                ),
            )
            self.assertEqual(
                report["classification"],
                "FAIL_COORDINATED_SHADOW_ANCHOR_GUARD",
            )

    def test_bootstrap_hold_is_inconclusive_not_fail_or_no_live_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(),
                bootstrap_classifier=_bootstrap(
                    eligible=0,
                    classification="HOLD_BOOTSTRAP_NO_CAUSAL_BLOCK_HASH_COVERAGE",
                    coverage_pct=0.0,
                ),
            )
            self.assertEqual(
                report["classification"],
                "INCONCLUSIVE_COORDINATED_SHADOW_BOOTSTRAP_COVERAGE",
            )
            self.assertEqual(report["bootstrap_causal_classification_coverage_pct"], 0.0)

    def test_bootstrap_parse_failure_is_systems_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_coordinated_shadow_v0(
                duration_seconds=1,
                poll_ms=350,
                rpc_url="https://rpc.example",
                feed_url="wss://feed.example",
                artifacts_root=Path(directory),
                python_executable="python",
                rpc_ready_timeout_seconds=1,
                child_timeout_slack_seconds=1,
                popen_factory=ArtifactPopenFactory(),
                bootstrap_classifier=_bootstrap(
                    eligible=0,
                    classification="FAIL_BOOTSTRAP_PARSE_ERRORS",
                    parse_errors=1,
                    coverage_pct=0.0,
                ),
            )
            self.assertEqual(
                report["classification"],
                "FAIL_COORDINATED_SHADOW_BOOTSTRAP_CLASSIFICATION",
            )
            self.assertEqual(report["bootstrap_parse_errors"], 1)


if __name__ == "__main__":
    unittest.main()
