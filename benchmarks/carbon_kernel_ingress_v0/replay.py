from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import struct
import subprocess
from typing import Any

from src.carbon_market_trade_adapter import (
    adapt_carbon_matched_unit_to_market_trade_v0,
)
from src.carbon_matched_unit_adapter import ADAPTED, adapt_carbon_pump_trade_v0
from src.market_signal_kernel import IndexedMarketSignalKernel

VERSION = "carbon_kernel_ingress_v0"
PUMP_PROGRAM_ID = "6EF8rrecthR5DkU8L4pFj6PaL2DStQp6L7x4CAt4q2p5"
TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
DEFAULT_EVENTS = 500


def _u64(value: int) -> bytes:
    return struct.pack("<Q", value)


def _i64(value: int) -> bytes:
    return struct.pack("<q", value)


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def synthetic_pump_trade_payload(sequence: int) -> bytes:
    payload = bytearray(TRADE_EVENT_DISCRIMINATOR)
    mint = bytes([7]) * 32
    user = bytes([(sequence % 250) + 1]) * 32
    fee_recipient = bytes([8]) * 32
    creator = bytes([9]) * 32
    quote_mint = bytes([10]) * 32

    payload += mint
    payload += _u64(1_000 + sequence)
    payload += _u64(2_000 + sequence)
    payload += b"\x01"
    payload += user
    payload += _i64(1_700_000_000 + sequence)
    payload += _u64(10_000 + sequence)
    payload += _u64(20_000 + sequence)
    payload += _u64(5_000 + sequence)
    payload += _u64(6_000 + sequence)
    payload += fee_recipient
    payload += _u64(100)
    payload += _u64(11)
    payload += creator
    payload += _u64(25)
    payload += _u64(3)
    payload += b"\x01"
    payload += _u64(4)
    payload += _u64(5)
    payload += _u64(6)
    payload += _i64(1_700_000_000 + sequence)
    payload += _string("buy")
    payload += b"\x00"
    payload += _u64(0)
    payload += _u64(0)
    payload += _u64(0)
    payload += _u64(0)
    payload += struct.pack("<I", 0)  # shareholders: Vec<Shareholder>
    payload += quote_mint
    payload += _u64(1_500 + sequence)
    payload += _u64(30_000 + sequence)
    payload += _u64(15_000 + sequence)
    return bytes(payload)


def carbon_input(sequence: int) -> dict[str, Any]:
    return {
        "type": "carbon_decoder_input",
        "event_key": f"pump-stream-{sequence}:0:pump_trade",
        "signature": f"SIG-{sequence}",
        "slot": 10_000 + sequence,
        "log_index": 0,
        "program_id": PUMP_PROGRAM_ID,
        "event_type": "pump_trade",
        "payload_base64": base64.b64encode(
            synthetic_pump_trade_payload(sequence)
        ).decode("ascii"),
    }


def run_replay(*, binary: Path, events: int = DEFAULT_EVENTS) -> dict[str, Any]:
    if events <= 0:
        raise ValueError("events must be positive")

    process = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    ready_line = process.stdout.readline()
    ready = json.loads(ready_line) if ready_line else {}
    ready_received = ready.get("type") == "carbon_stream_decoder_ready"

    kernel = IndexedMarketSignalKernel()
    decoded = 0
    matched_adapted = 0
    market_trade_adapted = 0
    trigger_count = 0
    semantic_errors: list[dict[str, Any]] = []

    for sequence in range(events):
        row = carbon_input(sequence)
        local_observed_at = 2_000_000_000 + sequence
        process.stdin.write(json.dumps(row, separators=(",", ":")) + "\n")
        process.stdin.flush()

        output_line = process.stdout.readline()
        if not output_line:
            semantic_errors.append({"sequence": sequence, "error": "missing_sidecar_output"})
            break
        canonical = json.loads(output_line)
        if canonical.get("type") != "carbon_canonical_event" or canonical.get("status") != "decoded":
            semantic_errors.append(
                {"sequence": sequence, "error": "carbon_decode_failed", "row": canonical}
            )
            continue
        decoded += 1

        matched = adapt_carbon_pump_trade_v0(
            canonical,
            observed_at=local_observed_at,
        )
        if matched.status != ADAPTED or matched.observation is None:
            semantic_errors.append(
                {
                    "sequence": sequence,
                    "error": "matched_unit_not_adapted",
                    "status": matched.status,
                    "flags": list(matched.data_quality_flags),
                }
            )
            continue
        matched_adapted += 1

        market_trade = adapt_carbon_matched_unit_to_market_trade_v0(canonical, matched)
        if market_trade.status != ADAPTED or market_trade.observation is None:
            semantic_errors.append(
                {
                    "sequence": sequence,
                    "error": "market_trade_not_adapted",
                    "status": market_trade.status,
                    "flags": list(market_trade.data_quality_flags),
                }
            )
            continue
        market_trade_adapted += 1

        observation = market_trade.observation
        if observation.observed_at != local_observed_at:
            semantic_errors.append(
                {"sequence": sequence, "error": "local_observed_at_not_preserved"}
            )
            continue
        if observation.notional_usd is not None or observation.price_usd is not None:
            semantic_errors.append(
                {"sequence": sequence, "error": "usd_or_price_was_manufactured"}
            )
            continue

        trigger = kernel.ingest_trade(observation)
        if trigger is not None:
            trigger_count += 1

    process.stdin.close()
    footer_line = process.stdout.readline()
    footer = json.loads(footer_line) if footer_line else {}
    return_code = process.wait(timeout=10.0)
    stderr = process.stderr.read()
    stats = kernel.stats()

    valid = (
        ready_received
        and decoded == events
        and matched_adapted == events
        and market_trade_adapted == events
        and stats.trade_events_ingested == events
        and not semantic_errors
        and footer.get("type") == "carbon_stream_decoder_footer"
        and footer.get("input_lines") == events
        and footer.get("decoded_events") == events
        and footer.get("decode_failures") == 0
        and footer.get("input_errors") == 0
        and return_code == 0
    )

    return {
        "type": "carbon_kernel_ingress_replay",
        "version": VERSION,
        "classification": (
            "PASS_CARBON_KERNEL_INGRESS_V0"
            if valid
            else "FAIL_CARBON_KERNEL_INGRESS_V0"
        ),
        "ready_received": ready_received,
        "carbon_decoder_version": ready.get("carbon_decoder_version"),
        "carbon_release_commit": ready.get("carbon_release_commit"),
        "input_events": events,
        "decoded_events": decoded,
        "matched_unit_adapted_events": matched_adapted,
        "market_trade_adapted_events": market_trade_adapted,
        "kernel_trade_events_ingested": stats.trade_events_ingested,
        "kernel_tracked_assets": stats.tracked_assets,
        "kernel_retained_trade_rows": stats.retained_trade_rows,
        "kernel_triggers_emitted": trigger_count,
        "semantic_errors": len(semantic_errors),
        "semantic_error_examples": semantic_errors[:10],
        "footer": footer,
        "process_return_code": return_code,
        "stderr": stderr[-4000:],
        "economic_edge_evaluated": False,
        "notes": [
            "Local observed_at is assigned at the acquisition boundary and kept outside the Carbon payload/decoder clock domain.",
            "Pump event-native quote identity allows this replay to isolate the decoder-to-kernel seam without external Pool context.",
            "USD notional and USD price remain missing; no conversion is inferred.",
            "A PASS validates deterministic component composition only, not provider latency, WSS completeness, PumpSwap context coverage, or economic edge.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Carbon sidecar output into the indexed signal kernel")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENTS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = run_replay(binary=args.binary, events=args.events)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["classification"] == "PASS_CARBON_KERNEL_INGRESS_V0" else 1


if __name__ == "__main__":
    raise SystemExit(main())
