"""Post-capture backlog/live-candidate classification for sequencer shadow V0."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from benchmarks.robinhood_sequencer_shadow_v0.capture import JsonRpcClientV0
from src.robinhood_nitro_bootstrap_v0 import (
    RpcHeadAnchorV0,
    anchor_is_still_canonical_v0,
    classify_feed_message_against_anchor_v0,
)
from src.robinhood_nitro_feed_v0 import parse_broadcast_message_v0


CLASSIFIER_VERSION = "robinhood_sequencer_bootstrap_classifier_v0"


def _load_json(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return row


def _anchor_from_report(report: dict[str, Any]) -> RpcHeadAnchorV0:
    row = report.get("pre_handshake_anchor")
    if not isinstance(row, dict):
        raise ValueError("capture report has no pre_handshake_anchor")
    return RpcHeadAnchorV0(
        block_number=int(row["block_number"]),
        block_hash=str(row["block_hash"]).lower(),
        block_timestamp_s=int(row["block_timestamp_s"]),
        captured_at_ns=int(row["captured_at_ns"]),
    )


def classify_capture_v0(
    *,
    run_dir: Path,
    rpc_url: str | None = None,
    rpc_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    capture_report = _load_json(run_dir / "report.json")
    frames_path = run_dir / "raw-frames.jsonl"
    if not frames_path.exists():
        raise FileNotFoundError(frames_path)
    anchor = _anchor_from_report(capture_report)
    resolved_rpc_url = rpc_url or str(capture_report.get("rpc_url") or "")
    if not resolved_rpc_url:
        raise ValueError("RPC URL missing from capture report and CLI")
    rpc = JsonRpcClientV0(resolved_rpc_url, timeout_seconds=rpc_timeout_seconds)

    anchor_now = rpc.call("eth_getBlockByNumber", [hex(anchor.block_number), False])
    anchor_canonical = anchor_is_still_canonical_v0(anchor, anchor_now)

    output_path = run_dir / "bootstrap-classifications.jsonl"
    block_cache: dict[str, dict[str, Any] | None] = {}
    counts: Counter[str] = Counter()
    messages_seen = 0
    parse_errors = 0
    eligible = 0

    with frames_path.open("r", encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8", buffering=1
    ) as target:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            frame = json.loads(line)
            raw_text = frame.get("raw_text")
            observed_at_ns = int(frame.get("observed_at_ns"))
            try:
                messages = parse_broadcast_message_v0(
                    raw_text,
                    observed_at_ns=observed_at_ns,
                )
            except Exception as exc:
                parse_errors += 1
                target.write(
                    json.dumps(
                        {
                            "line_number": line_number,
                            "classification": "PARSE_ERROR",
                            "error": f"{type(exc).__name__}:{exc}",
                            "eligible_for_feed_latency": False,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
                continue
            for message in messages:
                messages_seen += 1
                if message.block_hash is not None and message.block_hash not in block_cache:
                    row = rpc.call("eth_getBlockByHash", [message.block_hash, False])
                    block_cache[message.block_hash] = row if isinstance(row, dict) else None
                resolved = (
                    block_cache.get(message.block_hash)
                    if message.block_hash is not None
                    else None
                )
                classification = classify_feed_message_against_anchor_v0(
                    message,
                    anchor=anchor,
                    resolved_block_row=resolved,
                )
                row = classification.to_dict()
                if not anchor_canonical:
                    row["eligible_for_feed_latency"] = False
                    row["anchor_reorg_guard_passed"] = False
                else:
                    row["anchor_reorg_guard_passed"] = True
                row["line_number"] = line_number
                counts[row["classification"]] += 1
                eligible += int(bool(row["eligible_for_feed_latency"]))
                target.write(
                    json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
                )

    report = {
        "classifier_version": CLASSIFIER_VERSION,
        "capture_version": capture_report.get("capture_version"),
        "run_id": capture_report.get("run_id"),
        "anchor": anchor.to_dict(),
        "anchor_reorg_guard_passed": anchor_canonical,
        "messages_seen": messages_seen,
        "parse_errors": parse_errors,
        "resolved_unique_block_hashes": len(block_cache),
        "classification_counts": dict(sorted(counts.items())),
        "latency_eligible_messages": eligible if anchor_canonical else 0,
        "classification": (
            "PASS_BOOTSTRAP_CLASSIFICATION"
            if anchor_canonical
            else "FAIL_ANCHOR_REORG_GUARD"
        ),
        "execution_confirmed": False,
        "economic_outcomes_opened": False,
        "latency_claim_opened": False,
        "notes": [
            "post_capture_resolution_does_not_modify_feed_observed_at_ns",
            "only_blocks_strictly_newer_than_pre_handshake_anchor_are_latency_eligible",
            "unresolved_or_hashless_messages_are_not_latency_eligible",
        ],
    }
    (run_dir / "bootstrap-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--rpc-url")
    parser.add_argument("--rpc-timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    try:
        report = classify_capture_v0(
            run_dir=args.run_dir,
            rpc_url=args.rpc_url,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
        )
    except Exception as exc:
        report = {
            "classifier_version": CLASSIFIER_VERSION,
            "classification": "FAIL_BOOTSTRAP_CLASSIFICATION",
            "error": f"{type(exc).__name__}:{exc}",
            "execution_confirmed": False,
            "economic_outcomes_opened": False,
            "latency_claim_opened": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
