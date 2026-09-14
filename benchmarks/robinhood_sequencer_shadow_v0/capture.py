"""Raw Robinhood Nitro sequencer-feed shadow capture V0.

Scientific scope:
- freeze one RPC head before the first WebSocket handshake;
- clock each complete WebSocket text message before parsing;
- persist raw frames before any interpretation;
- track feed sequence continuity and reconnect from last_sequence + 1;
- do not classify execution, returns, fills, or economic outcomes here.

Backlog-vs-live classification is deliberately post-capture and uses the frozen
RPC anchor from this artifact. Initial requested sequence 0 is bootstrap-only and
must never be interpreted as a live latency boundary.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import time
from typing import Any
from urllib.request import Request, urlopen
import uuid

from src.robinhood_nitro_bootstrap_v0 import make_rpc_head_anchor_v0
from src.robinhood_nitro_feed_v0 import parse_broadcast_message_v0
from src.robinhood_nitro_ws_v0 import (
    DEFAULT_FEED_URL,
    NitroSequencerFeedClientV0,
    ROBINHOOD_CHAIN_ID,
    WebSocketProtocolError,
)


DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts/robinhood_sequencer_shadow_v0")
CAPTURE_VERSION = "robinhood_sequencer_shadow_capture_v0"


class JsonRpcClientV0:
    def __init__(self, url: str, timeout_seconds: float = 10.0):
        self.url = url
        self.timeout_seconds = float(timeout_seconds)
        self._next_id = 1

    def call(self, method: str, params: list[Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            row = json.loads(response.read().decode("utf-8"))
        if not isinstance(row, dict) or row.get("id") != request_id:
            raise RuntimeError("invalid JSON-RPC response identity")
        if row.get("error") is not None:
            raise RuntimeError(f"JSON-RPC error: {row['error']}")
        return row.get("result")

    def chain_id(self) -> int:
        value = self.call("eth_chainId", [])
        return int(str(value), 16)

    def latest_block(self) -> dict[str, Any]:
        row = self.call("eth_getBlockByNumber", ["latest", False])
        if not isinstance(row, dict):
            raise RuntimeError("eth_getBlockByNumber latest returned no block")
        return row


class SequenceTrackerV0:
    def __init__(self):
        self.first_sequence: int | None = None
        self.last_sequence: int | None = None
        self.message_count = 0
        self.duplicate_or_reordered_count = 0
        self.missing_sequence_count = 0
        self.gaps: list[dict[str, int]] = []

    def observe(self, sequence_number: int) -> None:
        if sequence_number < 0:
            raise ValueError("sequence_number must be non-negative")
        self.message_count += 1
        if self.first_sequence is None:
            self.first_sequence = sequence_number
            self.last_sequence = sequence_number
            return
        assert self.last_sequence is not None
        expected = self.last_sequence + 1
        if sequence_number == expected:
            self.last_sequence = sequence_number
            return
        if sequence_number <= self.last_sequence:
            self.duplicate_or_reordered_count += 1
            return
        missing = sequence_number - expected
        self.missing_sequence_count += missing
        self.gaps.append(
            {
                "after_sequence": self.last_sequence,
                "next_observed_sequence": sequence_number,
                "missing_count": missing,
            }
        )
        self.last_sequence = sequence_number

    @property
    def next_requested_sequence(self) -> int | None:
        return None if self.last_sequence is None else self.last_sequence + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_count": self.message_count,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "next_requested_sequence": self.next_requested_sequence,
            "duplicate_or_reordered_count": self.duplicate_or_reordered_count,
            "missing_sequence_count": self.missing_sequence_count,
            "gaps": self.gaps,
        }


def _write_json(path: Path, row: dict[str, Any]) -> None:
    path.write_text(json.dumps(row, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(handle, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    handle.flush()


def run_capture_v0(
    *,
    rpc_url: str,
    feed_url: str,
    duration_seconds: float,
    initial_requested_sequence: int,
    artifacts_root: Path,
    rpc_timeout_seconds: float = 10.0,
    feed_timeout_seconds: float = 20.0,
    max_reconnects: int = 5,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if initial_requested_sequence < 0:
        raise ValueError("initial_requested_sequence must be non-negative")
    if max_reconnects < 0:
        raise ValueError("max_reconnects must be non-negative")

    run_id = f"{CAPTURE_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    frames_path = run_dir / "raw-frames.jsonl"
    report_path = run_dir / "report.json"

    rpc = JsonRpcClientV0(rpc_url, timeout_seconds=rpc_timeout_seconds)
    chain_id = rpc.chain_id()
    if chain_id != ROBINHOOD_CHAIN_ID:
        raise RuntimeError(f"wrong Robinhood chain id: {chain_id}")

    anchor_block = rpc.latest_block()
    anchor_captured_at_ns = time.time_ns()
    anchor = make_rpc_head_anchor_v0(
        anchor_block,
        captured_at_ns=anchor_captured_at_ns,
    )

    tracker = SequenceTrackerV0()
    start_ns = time.time_ns()
    deadline_ns = start_ns + int(duration_seconds * 1_000_000_000)
    requested_sequence = initial_requested_sequence
    connection_index = 0
    reconnects = 0
    frame_count = 0
    parse_error_count = 0
    transport_errors: list[str] = []
    handshakes: list[dict[str, Any]] = []
    stop_reason = "unknown"

    with frames_path.open("a", encoding="utf-8", buffering=1) as handle:
        while time.time_ns() < deadline_ns:
            client = NitroSequencerFeedClientV0(
                feed_url,
                requested_sequence_number=requested_sequence,
                expected_chain_id=ROBINHOOD_CHAIN_ID,
                timeout_seconds=feed_timeout_seconds,
            )
            connection_index += 1
            try:
                handshake = client.connect()
                handshakes.append(
                    {
                        "connection_index": connection_index,
                        "connected_at_ns": time.time_ns(),
                        "requested_sequence_number": requested_sequence,
                        "feed_client_version": handshake.feed_client_version,
                        "feed_server_version": handshake.feed_server_version,
                        "chain_id": handshake.chain_id,
                    }
                )
                while time.time_ns() < deadline_ns:
                    raw_text, observed_at_ns = client.read_text()
                    frame_count += 1
                    # Persist the raw frame and immutable receive clock before parsing.
                    _append_jsonl(
                        handle,
                        {
                            "capture_version": CAPTURE_VERSION,
                            "connection_index": connection_index,
                            "requested_sequence_number": requested_sequence,
                            "observed_at_ns": observed_at_ns,
                            "raw_text": raw_text,
                        },
                    )
                    try:
                        messages = parse_broadcast_message_v0(
                            raw_text,
                            observed_at_ns=observed_at_ns,
                        )
                    except Exception:
                        parse_error_count += 1
                        continue
                    for message in messages:
                        tracker.observe(message.sequence_number)
                    next_sequence = tracker.next_requested_sequence
                    if next_sequence is not None:
                        requested_sequence = next_sequence
                stop_reason = "duration_elapsed"
                break
            except (EOFError, OSError, socket.timeout, WebSocketProtocolError) as exc:
                transport_errors.append(f"{type(exc).__name__}:{exc}")
                if time.time_ns() >= deadline_ns:
                    stop_reason = "duration_elapsed"
                    break
                if reconnects >= max_reconnects:
                    stop_reason = "reconnect_limit"
                    break
                reconnects += 1
                next_sequence = tracker.next_requested_sequence
                if next_sequence is not None:
                    requested_sequence = next_sequence
                time.sleep(min(1.0, max(0.0, (deadline_ns - time.time_ns()) / 1e9)))
            finally:
                client.close()

    ended_at_ns = time.time_ns()
    report = {
        "capture_version": CAPTURE_VERSION,
        "classification": "PASS_RAW_CAPTURE" if frame_count > 0 else "FAIL_NO_FEED_FRAMES",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "rpc_url": rpc_url,
        "feed_url": feed_url,
        "chain_id": chain_id,
        "started_at_ns": start_ns,
        "ended_at_ns": ended_at_ns,
        "duration_seconds_observed": (ended_at_ns - start_ns) / 1e9,
        "stop_reason": stop_reason,
        "pre_handshake_anchor": anchor.to_dict(),
        "initial_requested_sequence": initial_requested_sequence,
        "initial_sequence_semantics": "BOOTSTRAP_ONLY_NOT_LIVE_BOUNDARY",
        "frame_count": frame_count,
        "parse_error_count": parse_error_count,
        "connections": connection_index,
        "reconnects": reconnects,
        "transport_errors": transport_errors,
        "handshakes": handshakes,
        "sequence": tracker.to_dict(),
        "bootstrap_classification": "PENDING_POST_CAPTURE_RPC_HASH_RESOLUTION",
        "execution_confirmed": False,
        "economic_outcomes_opened": False,
        "latency_claim_opened": False,
    }
    _write_json(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url")
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--duration-seconds", type=float, default=300.0)
    parser.add_argument("--initial-requested-sequence", type=int, default=0)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--rpc-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--feed-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-reconnects", type=int, default=5)
    args = parser.parse_args()
    rpc_url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_RPC_URL
    try:
        result = run_capture_v0(
            rpc_url=rpc_url,
            feed_url=args.feed_url,
            duration_seconds=args.duration_seconds,
            initial_requested_sequence=args.initial_requested_sequence,
            artifacts_root=args.artifacts_root,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
            feed_timeout_seconds=args.feed_timeout_seconds,
            max_reconnects=args.max_reconnects,
        )
    except Exception as exc:
        result = {
            "capture_version": CAPTURE_VERSION,
            "classification": "FAIL_CAPTURE_PREFLIGHT",
            "error": f"{type(exc).__name__}:{exc}",
            "execution_confirmed": False,
            "economic_outcomes_opened": False,
            "latency_claim_opened": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
