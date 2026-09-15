"""Coordinate Robinhood sequencer-feed and RPC feature capture on one machine.

This runner is systems/acquisition-only. It launches the existing RPC Launch
Burst collector, waits until that collector has completed preflight and frozen
its initial block, then starts the raw Nitro sequencer capture. It records the
readiness/launch skew, retains child artifacts, and runs the causal post-capture
backlog classifier. It deliberately does not compute feed latency, trade returns,
selector evidence, or economic outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

from benchmarks.robinhood_sequencer_shadow_v0.classify_bootstrap import (
    classify_capture_v0,
)
from src.robinhood_nitro_ws_v0 import DEFAULT_FEED_URL


RUNNER_VERSION = "robinhood_sequencer_coordinated_shadow_v0"
DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts/robinhood_sequencer_coordinated_shadow_v0")
RPC_READY_VERSION = "robinhood_launch_burst_rpc_ready_v0"


def _endpoint_identity_v0(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path_redacted": bool(parsed.path and parsed.path != "/"),
        "query_redacted": bool(parsed.query),
    }


def build_child_commands_v0(
    *,
    python_executable: str,
    duration_seconds: int,
    poll_ms: int,
    rpc_url: str,
    feed_url: str,
    rpc_artifacts_root: Path,
    feed_artifacts_root: Path,
    rpc_ready_file: Path,
    factory_address: str | None = None,
) -> tuple[list[str], list[str]]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if poll_ms <= 0:
        raise ValueError("poll_ms must be positive")
    if not isinstance(rpc_url, str) or not rpc_url.strip():
        raise ValueError("rpc_url must be non-empty")
    rpc_command = [
        python_executable,
        "-m",
        "benchmarks.robinhood_launch_burst_v0.live",
        "--duration-seconds",
        str(duration_seconds),
        "--poll-ms",
        str(poll_ms),
        "--ready-file",
        str(rpc_ready_file),
        "--artifacts-root",
        str(rpc_artifacts_root),
    ]
    if factory_address:
        rpc_command.extend(["--factory-address", factory_address])

    feed_command = [
        python_executable,
        "-m",
        "benchmarks.robinhood_sequencer_shadow_v0.capture",
        "--duration-seconds",
        str(duration_seconds),
        "--feed-url",
        feed_url,
        "--initial-requested-sequence",
        "0",
        "--artifacts-root",
        str(feed_artifacts_root),
    ]
    return rpc_command, feed_command


def discover_single_child_run_v0(root: Path) -> Path | None:
    if not root.exists():
        return None
    rows = [row for row in root.iterdir() if row.is_dir()]
    if not rows:
        return None
    rows.sort(key=lambda row: row.stat().st_mtime_ns, reverse=True)
    return rows[0]


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return row if isinstance(row, dict) else None


def _report_passed(report: dict[str, Any] | None) -> bool:
    return bool(report and str(report.get("classification") or "").startswith("PASS"))


def _terminate_process(process, *, grace_seconds: float = 3.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace_seconds)


def _wait_for_rpc_ready_v0(
    *,
    process,
    ready_path: Path,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.01,
) -> tuple[dict[str, Any] | None, str | None]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    deadline = time.monotonic() + timeout_seconds
    last_parse_error = None
    while time.monotonic() < deadline:
        if ready_path.exists():
            try:
                row = json.loads(ready_path.read_text(encoding="utf-8"))
            except Exception as exc:
                last_parse_error = f"{type(exc).__name__}:{exc}"
            else:
                if not isinstance(row, dict):
                    return None, "rpc readiness artifact must be a JSON object"
                if row.get("type") != RPC_READY_VERSION:
                    return None, f"unexpected rpc readiness type: {row.get('type')!r}"
                if row.get("preflight_completed") is not True:
                    return None, "rpc readiness artifact does not confirm preflight"
                if row.get("capture_started_at_ns") is None:
                    return None, "rpc readiness artifact missing capture_started_at_ns"
                if row.get("initial_block") is None:
                    return None, "rpc readiness artifact missing initial_block"
                if not row.get("factory"):
                    return None, "rpc readiness artifact missing factory"
                return row, None
        if process.poll() is not None:
            suffix = f"; last_parse_error={last_parse_error}" if last_parse_error else ""
            return None, (
                f"rpc process exited before readiness: return_code={process.returncode}{suffix}"
            )
        remaining = max(0.0, deadline - time.monotonic())
        time.sleep(min(poll_interval_seconds, remaining))
    suffix = f"; last_parse_error={last_parse_error}" if last_parse_error else ""
    return None, f"rpc readiness timeout after {timeout_seconds}s{suffix}"


def run_coordinated_shadow_v0(
    *,
    duration_seconds: int,
    poll_ms: int,
    rpc_url: str,
    feed_url: str,
    artifacts_root: Path,
    factory_address: str | None = None,
    python_executable: str = sys.executable,
    rpc_ready_timeout_seconds: float = 30.0,
    child_timeout_slack_seconds: float = 90.0,
    popen_factory: Any = subprocess.Popen,
    bootstrap_classifier: Any = classify_capture_v0,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if rpc_ready_timeout_seconds <= 0:
        raise ValueError("rpc_ready_timeout_seconds must be positive")
    if child_timeout_slack_seconds <= 0:
        raise ValueError("child_timeout_slack_seconds must be positive")

    run_id = f"{RUNNER_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"
    run_dir = artifacts_root / run_id
    rpc_root = run_dir / "rpc"
    feed_root = run_dir / "feed"
    logs_root = run_dir / "logs"
    rpc_ready_path = run_dir / "rpc-ready.json"
    rpc_root.mkdir(parents=True, exist_ok=False)
    feed_root.mkdir(parents=True, exist_ok=False)
    logs_root.mkdir(parents=True, exist_ok=False)

    rpc_command, feed_command = build_child_commands_v0(
        python_executable=python_executable,
        duration_seconds=duration_seconds,
        poll_ms=poll_ms,
        rpc_url=rpc_url,
        feed_url=feed_url,
        rpc_artifacts_root=rpc_root,
        feed_artifacts_root=feed_root,
        rpc_ready_file=rpc_ready_path,
        factory_address=factory_address,
    )
    child_env = os.environ.copy()
    child_env["ROBINHOOD_RPC_URL"] = rpc_url

    started_at_ns = time.time_ns()
    rpc_started_at_ns = None
    feed_started_at_ns = None
    rpc_process = None
    feed_process = None
    rpc_ready_report = None
    rpc_ready_error = None
    timed_out = False

    with (logs_root / "rpc.stdout.log").open("wb") as rpc_stdout, (
        logs_root / "rpc.stderr.log"
    ).open("wb") as rpc_stderr, (logs_root / "feed.stdout.log").open(
        "wb"
    ) as feed_stdout, (logs_root / "feed.stderr.log").open("wb") as feed_stderr:
        try:
            rpc_started_at_ns = time.time_ns()
            rpc_process = popen_factory(
                rpc_command,
                stdout=rpc_stdout,
                stderr=rpc_stderr,
                env=child_env,
            )
            rpc_ready_report, rpc_ready_error = _wait_for_rpc_ready_v0(
                process=rpc_process,
                ready_path=rpc_ready_path,
                timeout_seconds=rpc_ready_timeout_seconds,
            )

            if rpc_ready_report is not None:
                feed_started_at_ns = time.time_ns()
                feed_process = popen_factory(
                    feed_command,
                    stdout=feed_stdout,
                    stderr=feed_stderr,
                    env=child_env,
                )
                deadline = time.monotonic() + duration_seconds + child_timeout_slack_seconds
                for process in (rpc_process, feed_process):
                    remaining = max(0.1, deadline - time.monotonic())
                    try:
                        process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        break
        finally:
            if rpc_process is not None:
                _terminate_process(rpc_process)
            if feed_process is not None:
                _terminate_process(feed_process)

    finished_at_ns = time.time_ns()
    rpc_run_dir = discover_single_child_run_v0(rpc_root)
    feed_run_dir = discover_single_child_run_v0(feed_root)
    rpc_report = _read_json(rpc_run_dir / "report.json" if rpc_run_dir else None)
    feed_report = _read_json(feed_run_dir / "report.json" if feed_run_dir else None)

    bootstrap_report = None
    bootstrap_error = None
    feed_capture_ok = (
        feed_report is not None
        and feed_report.get("classification") == "PASS_RAW_CAPTURE"
    )
    if feed_run_dir is not None and feed_capture_ok:
        try:
            bootstrap_report = bootstrap_classifier(
                run_dir=feed_run_dir,
                rpc_url=rpc_url,
            )
        except Exception as exc:
            bootstrap_error = f"{type(exc).__name__}:{exc}"

    rpc_return_code = rpc_process.returncode if rpc_process is not None else None
    feed_return_code = feed_process.returncode if feed_process is not None else None
    rpc_ready = rpc_ready_report is not None and rpc_ready_error is None
    child_processes_ok = (
        rpc_return_code == 0
        and feed_return_code == 0
        and not timed_out
        and rpc_ready
    )
    artifacts_present = rpc_report is not None and feed_report is not None
    rpc_capture_ok = _report_passed(rpc_report)
    bootstrap_classification = (
        str(bootstrap_report.get("classification") or "")
        if bootstrap_report
        else ""
    )
    bootstrap_ok = bootstrap_classification == "PASS_BOOTSTRAP_CLASSIFICATION"
    bootstrap_hold = bootstrap_classification.startswith("HOLD_")
    anchor_ok = bool(
        bootstrap_report
        and bootstrap_report.get("anchor_reorg_guard_passed") is True
    )
    eligible_messages = (
        int(bootstrap_report.get("latency_eligible_messages") or 0)
        if bootstrap_report
        else 0
    )

    if not rpc_ready:
        classification = "FAIL_COORDINATED_SHADOW_RPC_READINESS"
    elif timed_out:
        classification = "FAIL_COORDINATED_SHADOW_CHILD_TIMEOUT"
    elif not child_processes_ok:
        classification = "FAIL_COORDINATED_SHADOW_CHILD_PROCESS"
    elif not artifacts_present:
        classification = "FAIL_COORDINATED_SHADOW_ARTIFACTS"
    elif not rpc_capture_ok:
        classification = "FAIL_COORDINATED_SHADOW_RPC_CAPTURE"
    elif not feed_capture_ok:
        classification = "FAIL_COORDINATED_SHADOW_FEED_CAPTURE"
    elif bootstrap_report is None:
        classification = "FAIL_COORDINATED_SHADOW_BOOTSTRAP_CLASSIFICATION"
    elif bootstrap_classification == "FAIL_ANCHOR_REORG_GUARD" or not anchor_ok:
        classification = "FAIL_COORDINATED_SHADOW_ANCHOR_GUARD"
    elif bootstrap_hold:
        classification = "INCONCLUSIVE_COORDINATED_SHADOW_BOOTSTRAP_COVERAGE"
    elif not bootstrap_ok:
        classification = "FAIL_COORDINATED_SHADOW_BOOTSTRAP_CLASSIFICATION"
    elif eligible_messages == 0:
        classification = "PASS_COORDINATED_SHADOW_ACQUISITION_V0_NO_LIVE_CANDIDATES"
    else:
        classification = "PASS_COORDINATED_SHADOW_ACQUISITION_V0"

    rpc_capture_started_at_ns = (
        int(rpc_ready_report.get("capture_started_at_ns"))
        if rpc_ready_report and rpc_ready_report.get("capture_started_at_ns") is not None
        else None
    )
    report = {
        "runner_version": RUNNER_VERSION,
        "classification": classification,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "started_at_ns": started_at_ns,
        "finished_at_ns": finished_at_ns,
        "duration_seconds_requested": duration_seconds,
        "rpc_endpoint": _endpoint_identity_v0(rpc_url),
        "feed_url": feed_url,
        "rpc_started_at_ns": rpc_started_at_ns,
        "rpc_ready": rpc_ready,
        "rpc_ready_path": str(rpc_ready_path),
        "rpc_ready_error": rpc_ready_error,
        "rpc_ready_report": rpc_ready_report,
        "rpc_capture_started_at_ns": rpc_capture_started_at_ns,
        "rpc_spawn_to_ready_ms": (
            (rpc_capture_started_at_ns - rpc_started_at_ns) / 1_000_000.0
            if rpc_capture_started_at_ns is not None and rpc_started_at_ns is not None
            else None
        ),
        "feed_started_at_ns": feed_started_at_ns,
        "rpc_ready_to_feed_start_ms": (
            (feed_started_at_ns - rpc_capture_started_at_ns) / 1_000_000.0
            if feed_started_at_ns is not None and rpc_capture_started_at_ns is not None
            else None
        ),
        "child_start_skew_ms": (
            (feed_started_at_ns - rpc_started_at_ns) / 1_000_000.0
            if rpc_started_at_ns is not None and feed_started_at_ns is not None
            else None
        ),
        "timed_out": timed_out,
        "rpc_return_code": rpc_return_code,
        "feed_return_code": feed_return_code,
        "rpc_command": rpc_command,
        "feed_command": feed_command,
        "rpc_run_dir": str(rpc_run_dir) if rpc_run_dir else None,
        "feed_run_dir": str(feed_run_dir) if feed_run_dir else None,
        "rpc_report_present": rpc_report is not None,
        "feed_report_present": feed_report is not None,
        "rpc_capture_classification": (
            rpc_report.get("classification") if rpc_report else None
        ),
        "feed_capture_classification": (
            feed_report.get("classification") if feed_report else None
        ),
        "rpc_capture_error": rpc_report.get("error") if rpc_report else None,
        "rpc_failure_stage": rpc_report.get("failure_stage") if rpc_report else None,
        "rpc_preflight_completed": (
            rpc_report.get("preflight_completed") if rpc_report else None
        ),
        "rpc_factory_discovery": (
            rpc_report.get("factory_discovery") if rpc_report else None
        ),
        "rpc_transport_errors": (
            rpc_report.get("transport_errors") if rpc_report else None
        ),
        "feed_capture_error": feed_report.get("error") if feed_report else None,
        "feed_frame_count": (
            feed_report.get("frame_count") if feed_report else None
        ),
        "feed_transport_errors": (
            feed_report.get("transport_errors") if feed_report else None
        ),
        "bootstrap_classification": (
            bootstrap_report.get("classification") if bootstrap_report else None
        ),
        "bootstrap_anchor_reorg_guard_passed": anchor_ok,
        "bootstrap_messages_seen": (
            bootstrap_report.get("messages_seen") if bootstrap_report else None
        ),
        "bootstrap_parse_errors": (
            bootstrap_report.get("parse_errors") if bootstrap_report else None
        ),
        "bootstrap_block_resolution_errors": (
            bootstrap_report.get("block_resolution_errors") if bootstrap_report else None
        ),
        "bootstrap_classification_counts": (
            bootstrap_report.get("classification_counts") if bootstrap_report else None
        ),
        "bootstrap_causal_classification_coverage_pct": (
            bootstrap_report.get("causal_classification_coverage_pct")
            if bootstrap_report
            else None
        ),
        "bootstrap_latency_eligible_messages": eligible_messages,
        "bootstrap_error": bootstrap_error,
        "execution_reconciliation_opened": False,
        "latency_claim_opened": False,
        "economic_outcomes_opened": False,
        "selector_frozen": False,
        "notes": [
            "rpc_and_feed_run_on_same_machine_and_wall_clock",
            "rpc_provider_url_is_passed_to_children_only_via_environment",
            "rpc_provider_url_is_redacted_from_commands_and_reports",
            "feed_process_starts_only_after_rpc_preflight_and_initial_block_readiness",
            "rpc_capture_duration_starts_after_rpc_preflight",
            "rpc_ready_to_feed_start_skew_is_recorded",
            "feed_is_not_started_when_rpc_readiness_fails",
            "initial_feed_sequence_zero_is_bootstrap_only",
            "bootstrap_classification_is_required_before_latency_analysis",
            "bootstrap_runs_only_after_PASS_RAW_CAPTURE",
            "child_preflight_errors_are_surfaced_in_parent_report",
            "bootstrap_parse_or_resolution_failures_cannot_be_promoted_to_no_live_candidates",
            "bootstrap_hold_is_inconclusive_coverage_not_systems_pass",
            "zero_post_anchor_messages_is_coverage_not_failure_only_after_clean_bootstrap",
            "this_runner_does_not_compute_feed_advantage_or_trade_returns",
        ],
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--poll-ms", type=int, default=350)
    parser.add_argument("--rpc-url")
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--factory-address")
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--rpc-ready-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--child-timeout-slack-seconds", type=float, default=90.0)
    args = parser.parse_args()
    rpc_url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_RPC_URL
    try:
        result = run_coordinated_shadow_v0(
            duration_seconds=args.duration_seconds,
            poll_ms=args.poll_ms,
            rpc_url=rpc_url,
            feed_url=args.feed_url,
            artifacts_root=args.artifacts_root,
            factory_address=args.factory_address,
            python_executable=args.python_executable,
            rpc_ready_timeout_seconds=args.rpc_ready_timeout_seconds,
            child_timeout_slack_seconds=args.child_timeout_slack_seconds,
        )
    except Exception as exc:
        result = {
            "runner_version": RUNNER_VERSION,
            "classification": "FAIL_COORDINATED_SHADOW_PREFLIGHT",
            "error": f"{type(exc).__name__}:{exc}",
            "execution_reconciliation_opened": False,
            "latency_claim_opened": False,
            "economic_outcomes_opened": False,
            "selector_frozen": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
