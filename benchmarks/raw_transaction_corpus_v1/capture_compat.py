from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time

from benchmarks.raw_transaction_corpus_v1.capture import (
    TRACE_VERSION,
    CaptureCounters,
    RawIngressObservation,
    _hydrate_with_retry,
    _write_jsonl,
    build_logs_subscribe_request,
    parse_raw_logs_notification,
)
from src.pump_bonding_stream import PUMP_PROGRAM_ID, rpc_http_to_ws_url
from src.pumpswap_stream import PUMPSWAP_PROGRAM_ID
from src.solana import SolanaClient


async def _subscribe_one(
    websocket,
    *,
    request_id: int,
    venue: str,
    program_id: str,
    commitment: str,
    timeout_seconds: float = 15.0,
) -> tuple[int, tuple[str, str]]:
    """Subscribe one program and tolerate interleaved non-ACK websocket messages.

    The capture window has not started while this function runs. Any early notification
    from a previously acknowledged subscription is intentionally ignored instead of being
    misclassified as an acknowledgement.
    """

    await websocket.send(
        json.dumps(
            build_logs_subscribe_request(
                request_id=request_id,
                program_id=program_id,
                commitment=commitment,
            )
        )
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"logsSubscribe acknowledgement timeout request_id={request_id} venue={venue}"
            )
        raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        message = json.loads(raw)

        # Notifications may interleave after another subscription has already been
        # acknowledged. They are outside the official capture window and are discarded.
        if message.get("method") == "logsNotification":
            continue

        if "error" in message:
            raise RuntimeError(
                f"logsSubscribe failed request_id={request_id} venue={venue}: {message['error']}"
            )

        if message.get("id") != request_id:
            # Ignore unrelated JSON-RPC responses rather than treating them as this ACK.
            continue

        subscription_id = message.get("result")
        if not isinstance(subscription_id, int):
            raise RuntimeError(
                "invalid logsSubscribe acknowledgement "
                f"request_id={request_id} venue={venue} payload={message!r}"
            )
        return subscription_id, (venue, program_id)


async def capture_raw_transaction_corpus_compat(
    *,
    rpc_url: str,
    out_path: Path,
    duration_seconds: float,
    commitment: str = "confirmed",
    hydrate_workers: int = 8,
    queue_size: int = 2048,
    hydrate_attempts: int = 4,
    hydrate_retry_delay_ms: int = 250,
) -> dict:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if hydrate_workers <= 0 or queue_size <= 0:
        raise ValueError("hydrate_workers/queue_size must be positive")
    if hydrate_attempts <= 0 or hydrate_retry_delay_ms < 0:
        raise ValueError("invalid hydration retry configuration")

    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets dependency is required") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    queue: asyncio.Queue[RawIngressObservation | None] = asyncio.Queue(maxsize=queue_size)
    counters = CaptureCounters()
    seen: set[tuple[str, str]] = set()
    sequence = 0
    writer_lock = asyncio.Lock()

    rpc_client = SolanaClient(rpc_url=rpc_url, timeout=5, fallback_urls=())
    ws_url = rpc_http_to_ws_url(rpc_url)

    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    transaction, attempt_count, error = await _hydrate_with_retry(
                        rpc_client,
                        item,
                        commitment=commitment,
                        attempts=hydrate_attempts,
                        retry_delay_ms=hydrate_retry_delay_ms,
                    )
                    hydrated_at_ns = time.time_ns()
                    if transaction is None:
                        if error is None:
                            counters.hydrate_missing += 1
                        else:
                            counters.hydrate_errors += 1
                    else:
                        counters.hydrated += 1
                    record = {
                        "type": "raw_transaction",
                        "version": TRACE_VERSION,
                        **asdict(item),
                        "logs": list(item.logs),
                        "hydrated_at_ns": hydrated_at_ns,
                        "hydrate_attempts_used": attempt_count,
                        "hydrate_error": error,
                        "transaction": transaction,
                    }
                    async with writer_lock:
                        _write_jsonl(handle, record)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(hydrate_workers)]

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_queue=4096,
            ) as websocket:
                subscription_map: dict[int, tuple[str, str]] = {}
                for request_id, venue, program_id in (
                    (1, "pump", PUMP_PROGRAM_ID),
                    (2, "pumpswap", PUMPSWAP_PROGRAM_ID),
                ):
                    subscription_id, mapping = await _subscribe_one(
                        websocket,
                        request_id=request_id,
                        venue=venue,
                        program_id=program_id,
                        commitment=commitment,
                    )
                    subscription_map[subscription_id] = mapping

                # Official corpus clocks begin only after BOTH subscriptions are confirmed.
                started_wall_ns = time.time_ns()
                started_mono_ns = time.monotonic_ns()
                deadline_ns = started_mono_ns + int(duration_seconds * 1_000_000_000)
                _write_jsonl(
                    handle,
                    {
                        "type": "trace_header",
                        "version": TRACE_VERSION,
                        "capture_variant": "compat_sequential_handshake_v1_1",
                        "rpc_url_host": rpc_client.rpc_host,
                        "commitment": commitment,
                        "duration_seconds": duration_seconds,
                        "queue_size": queue_size,
                        "hydrate_workers": hydrate_workers,
                        "hydrate_attempts": hydrate_attempts,
                        "hydrate_retry_delay_ms": hydrate_retry_delay_ms,
                        "started_wall_ns": started_wall_ns,
                        "started_monotonic_ns": started_mono_ns,
                        "subscriptions": {
                            str(key): value[0] for key, value in subscription_map.items()
                        },
                        "programs": {
                            "pump": PUMP_PROGRAM_ID,
                            "pumpswap": PUMPSWAP_PROGRAM_ID,
                        },
                    },
                )

                while time.monotonic_ns() < deadline_ns:
                    remaining = max(
                        0.001,
                        (deadline_ns - time.monotonic_ns()) / 1_000_000_000,
                    )
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break
                    wall_ns = time.time_ns()
                    mono_ns = time.monotonic_ns()
                    message = json.loads(raw)
                    params = message.get("params")
                    if not isinstance(params, dict):
                        continue
                    subscription_id = params.get("subscription")
                    mapping = subscription_map.get(subscription_id)
                    if mapping is None:
                        continue
                    venue, program_id = mapping
                    counters.notifications_seen += 1
                    observation = parse_raw_logs_notification(
                        message,
                        sequence=sequence,
                        venue=venue,
                        program_id=program_id,
                        wall_observed_at_ns=wall_ns,
                        monotonic_observed_at_ns=mono_ns,
                    )
                    if observation is None:
                        continue
                    dedupe_key = (venue, observation.signature)
                    if dedupe_key in seen:
                        counters.duplicate_notifications += 1
                        continue
                    seen.add(dedupe_key)
                    sequence += 1
                    try:
                        queue.put_nowait(observation)
                    except asyncio.QueueFull:
                        counters.queue_overflow += 1
                    else:
                        counters.queued += 1
        finally:
            await queue.join()
            for _ in workers:
                await queue.put(None)
            await asyncio.gather(*workers)

        finished_wall_ns = time.time_ns()
        summary = {
            "type": "trace_footer",
            "version": TRACE_VERSION,
            "capture_variant": "compat_sequential_handshake_v1_1",
            "finished_wall_ns": finished_wall_ns,
            "counters": asdict(counters),
            "valid_for_decoder_parity": (
                counters.queue_overflow == 0
                and counters.hydrate_missing == 0
                and counters.hydrate_errors == 0
                and counters.hydrated == counters.queued
                and counters.queued > 0
            ),
        }
        _write_jsonl(handle, summary)
        return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture Pump/PumpSwap raw transactions with robust sequential WS handshake."
    )
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument(
        "--commitment",
        choices=("processed", "confirmed", "finalized"),
        default="confirmed",
    )
    parser.add_argument("--hydrate-workers", type=int, default=8)
    parser.add_argument("--queue-size", type=int, default=2048)
    parser.add_argument("--hydrate-attempts", type=int, default=4)
    parser.add_argument("--hydrate-retry-delay-ms", type=int, default=250)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    summary = asyncio.run(
        capture_raw_transaction_corpus_compat(
            rpc_url=args.rpc_url,
            out_path=args.out,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
            hydrate_workers=args.hydrate_workers,
            queue_size=args.queue_size,
            hydrate_attempts=args.hydrate_attempts,
            hydrate_retry_delay_ms=args.hydrate_retry_delay_ms,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["valid_for_decoder_parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
