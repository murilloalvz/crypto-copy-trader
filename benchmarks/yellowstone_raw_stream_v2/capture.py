from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlparse

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
TRACE_VERSION = "yellowstone_raw_transaction_trace_v2"


@dataclass
class CaptureCounters:
    updates_seen: int = 0
    transaction_updates: int = 0
    pump_updates: int = 0
    pumpswap_updates: int = 0
    ping_updates: int = 0
    other_updates: int = 0
    missing_transaction_info: int = 0
    write_errors: int = 0
    stream_errors: int = 0
    bytes_protobuf: int = 0


def endpoint_connection(endpoint: str) -> tuple[str, str, bool]:
    """Return (grpc_target, safe_host, use_tls) without retaining path/query data."""
    value = endpoint.strip()
    if not value:
        raise ValueError("endpoint cannot be blank")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("endpoint scheme must be http or https")
    if not parsed.hostname:
        raise ValueError("invalid endpoint")
    port = parsed.port or (443 if scheme == "https" else 80)
    target = f"{parsed.hostname}:{port}"
    safe_host = parsed.hostname
    return target, safe_host, scheme == "https"


def endpoint_target(endpoint: str) -> tuple[str, str]:
    """Backward-compatible helper used by tests/docs."""
    target, safe_host, _ = endpoint_connection(endpoint)
    return target, safe_host


def _build_metadata(auth_header: str, auth_token: str) -> tuple[tuple[str, str], ...]:
    header = auth_header.strip().lower()
    if header in {"", "none"}:
        return ()
    token = auth_token.strip()
    if not token:
        raise ValueError(
            f"authentication header {header!r} requires YELLOWSTONE_AUTH_TOKEN "
            "(or legacy YELLOWSTONE_X_TOKEN)"
        )
    return ((header, token),)


def load_generated_modules():
    try:
        from .generated import geyser_pb2, geyser_pb2_grpc  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Yellowstone protobuf stubs are missing. Run: "
            "python -m benchmarks.yellowstone_raw_stream_v2.generate_proto"
        ) from exc
    return geyser_pb2, geyser_pb2_grpc


def _write_jsonl(handle, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _build_footer(
    counters: CaptureCounters,
    *,
    started_wall_ns: int,
    finished_wall_ns: int,
    first_transaction_wall_ns: int | None,
    stop_reason: str,
    max_transactions: int,
) -> dict[str, Any]:
    return {
        "type": "trace_footer",
        "version": TRACE_VERSION,
        "started_wall_ns": started_wall_ns,
        "finished_wall_ns": finished_wall_ns,
        "first_transaction_wall_ns": first_transaction_wall_ns,
        "elapsed_seconds": (finished_wall_ns - started_wall_ns) / 1_000_000_000,
        "stop_reason": stop_reason,
        "max_transactions": max_transactions,
        "counters": asdict(counters),
        "valid_for_decoder_parity": (
            counters.transaction_updates > 0
            and counters.pump_updates > 0
            and counters.pumpswap_updates > 0
            and counters.missing_transaction_info == 0
            and counters.write_errors == 0
            and counters.stream_errors == 0
        ),
    }


async def capture(
    *,
    endpoint: str,
    auth_header: str,
    auth_token: str,
    out_path: Path,
    duration_seconds: float,
    max_transactions: int,
    commitment: str,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if max_transactions <= 0:
        raise ValueError("max_transactions must be positive")
    if commitment not in {"processed", "confirmed", "finalized"}:
        raise ValueError("unsupported commitment")

    try:
        import grpc
    except ImportError as exc:
        raise RuntimeError(
            "grpcio is required. Install benchmark requirements first."
        ) from exc

    geyser_pb2, geyser_pb2_grpc = load_generated_modules()
    target, safe_host, use_tls = endpoint_connection(endpoint)
    metadata = _build_metadata(auth_header, auth_token)

    commitment_value = {
        "processed": geyser_pb2.PROCESSED,
        "confirmed": geyser_pb2.CONFIRMED,
        "finalized": geyser_pb2.FINALIZED,
    }[commitment]

    request = geyser_pb2.SubscribeRequest(
        commitment=commitment_value,
        transactions={
            "pump": geyser_pb2.SubscribeRequestFilterTransactions(
                vote=False,
                failed=False,
                account_include=[PUMP_PROGRAM_ID],
            ),
            "pumpswap": geyser_pb2.SubscribeRequestFilterTransactions(
                vote=False,
                failed=False,
                account_include=[PUMPSWAP_PROGRAM_ID],
            ),
        },
    )

    request_queue: asyncio.Queue[Any | None] = asyncio.Queue()
    await request_queue.put(request)

    async def request_iter():
        while True:
            item = await request_queue.get()
            if item is None:
                return
            yield item

    options = (("grpc.max_receive_message_length", 64 * 1024 * 1024),)
    if use_tls:
        channel = grpc.aio.secure_channel(
            target, grpc.ssl_channel_credentials(), options=options
        )
    else:
        channel = grpc.aio.insecure_channel(target, options=options)
    stub = geyser_pb2_grpc.GeyserStub(channel)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    counters = CaptureCounters()
    started_wall_ns = time.time_ns()
    started_mono_ns = time.monotonic_ns()
    deadline_ns = started_mono_ns + int(duration_seconds * 1_000_000_000)
    first_transaction_wall_ns: int | None = None
    stop_reason = "duration"

    with out_path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as handle:
        _write_jsonl(
            handle,
            {
                "type": "trace_header",
                "version": TRACE_VERSION,
                "source": "yellowstone_grpc",
                "endpoint_host": safe_host,
                "transport": "tls" if use_tls else "plaintext",
                "auth_header": None if not metadata else metadata[0][0],
                "commitment": commitment,
                "duration_seconds": duration_seconds,
                "max_transactions": max_transactions,
                "programs": {
                    "pump": PUMP_PROGRAM_ID,
                    "pumpswap": PUMPSWAP_PROGRAM_ID,
                },
                "started_wall_ns": started_wall_ns,
                "started_monotonic_ns": started_mono_ns,
                "payload_encoding": "base64(protobuf SubscribeUpdate)",
            },
        )
        handle.flush()

        call = stub.Subscribe(request_iter(), metadata=metadata)
        try:
            while time.monotonic_ns() < deadline_ns:
                if counters.transaction_updates >= max_transactions:
                    stop_reason = "max_transactions"
                    break

                remaining = max(
                    0.001,
                    (deadline_ns - time.monotonic_ns()) / 1_000_000_000,
                )
                try:
                    message = await asyncio.wait_for(call.read(), timeout=remaining)
                except asyncio.TimeoutError:
                    stop_reason = "duration"
                    break
                except grpc.aio.AioRpcError:
                    counters.stream_errors += 1
                    raise

                if message is grpc.aio.EOF:
                    stop_reason = "stream_eof"
                    break

                received_wall_ns = time.time_ns()
                received_monotonic_ns = time.monotonic_ns()
                counters.updates_seen += 1
                kind = message.WhichOneof("update_oneof")

                if kind == "ping":
                    counters.ping_updates += 1
                    await request_queue.put(
                        geyser_pb2.SubscribeRequest(
                            ping=geyser_pb2.SubscribeRequestPing(id=1)
                        )
                    )
                    continue

                if kind != "transaction":
                    counters.other_updates += 1
                    continue

                counters.transaction_updates += 1
                filters = set(message.filters)
                if "pump" in filters:
                    counters.pump_updates += 1
                if "pumpswap" in filters:
                    counters.pumpswap_updates += 1

                tx_update = message.transaction
                if tx_update.HasField("transaction"):
                    tx_info = tx_update.transaction
                else:
                    tx_info = None
                    counters.missing_transaction_info += 1

                if first_transaction_wall_ns is None:
                    first_transaction_wall_ns = received_wall_ns

                payload = message.SerializeToString()
                counters.bytes_protobuf += len(payload)
                signature_b64 = (
                    base64.b64encode(tx_info.signature).decode("ascii")
                    if tx_info is not None
                    else None
                )
                record = {
                    "type": "yellowstone_transaction",
                    "version": TRACE_VERSION,
                    "filters": list(message.filters),
                    "slot": int(tx_update.slot),
                    "index": int(tx_info.index) if tx_info is not None else None,
                    "signature_b64": signature_b64,
                    "provider_created_at_ns": (
                        int(message.created_at.seconds) * 1_000_000_000
                        + int(message.created_at.nanos)
                        if message.HasField("created_at")
                        else None
                    ),
                    "received_wall_ns": received_wall_ns,
                    "received_monotonic_ns": received_monotonic_ns,
                    "protobuf_b64": base64.b64encode(payload).decode("ascii"),
                }
                try:
                    _write_jsonl(handle, record)
                except OSError:
                    counters.write_errors += 1
                    raise

                if counters.transaction_updates % 128 == 0:
                    handle.flush()

        finally:
            await request_queue.put(None)
            await channel.close()

        finished_wall_ns = time.time_ns()
        footer = _build_footer(
            counters,
            started_wall_ns=started_wall_ns,
            finished_wall_ns=finished_wall_ns,
            first_transaction_wall_ns=first_transaction_wall_ns,
            stop_reason=stop_reason,
            max_transactions=max_transactions,
        )
        _write_jsonl(handle, footer)
        handle.flush()

    return footer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture Pump/PumpSwap transactions directly from a Yellowstone-compatible "
            "gRPC stream. No JSON-RPC hydration is performed."
        )
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("YELLOWSTONE_ENDPOINT", ""),
        help="Yellowstone http(s) endpoint; can also use YELLOWSTONE_ENDPOINT.",
    )
    parser.add_argument(
        "--auth-header",
        default=os.getenv("YELLOWSTONE_AUTH_HEADER", "x-token"),
        help=(
            "gRPC metadata header for provider auth (default: x-token). "
            "Use 'none' for IP-allowlisted/no-token providers such as ERPC."
        ),
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--max-transactions", type=int, default=500)
    parser.add_argument(
        "--commitment",
        choices=("processed", "confirmed", "finalized"),
        default="confirmed",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if not args.endpoint:
        print(
            "Missing Yellowstone endpoint. Set YELLOWSTONE_ENDPOINT or pass --endpoint.",
            file=sys.stderr,
        )
        return 2

    auth_token = os.getenv(
        "YELLOWSTONE_AUTH_TOKEN",
        os.getenv("YELLOWSTONE_X_TOKEN", ""),
    ).strip()

    try:
        footer = asyncio.run(
            capture(
                endpoint=args.endpoint,
                auth_header=args.auth_header,
                auth_token=auth_token,
                out_path=args.out,
                duration_seconds=args.duration_seconds,
                max_transactions=args.max_transactions,
                commitment=args.commitment,
            )
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(footer, indent=2, sort_keys=True))
    return 0 if footer["valid_for_decoder_parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
