from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any

from src.pump_bonding_stream import PUMP_PROGRAM_ID, rpc_http_to_ws_url
from src.pumpswap_stream import PUMPSWAP_PROGRAM_ID
from src.solana import SolanaClient, SolanaRPCError


TRACE_VERSION = "raw_solana_transaction_trace_v1"


@dataclass(frozen=True)
class RawIngressObservation:
    sequence: int
    venue: str
    program_id: str
    signature: str
    slot: int
    wall_observed_at_ns: int
    monotonic_observed_at_ns: int
    logs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.venue not in {"pump", "pumpswap"}:
            raise ValueError("unsupported venue")
        if not self.program_id.strip() or not self.signature.strip():
            raise ValueError("program_id/signature cannot be blank")
        if self.slot < 0 or self.wall_observed_at_ns < 0 or self.monotonic_observed_at_ns < 0:
            raise ValueError("timestamps/slot must be non-negative")


@dataclass
class CaptureCounters:
    notifications_seen: int = 0
    queued: int = 0
    duplicate_notifications: int = 0
    queue_overflow: int = 0
    hydrated: int = 0
    hydrate_missing: int = 0
    hydrate_errors: int = 0


def build_logs_subscribe_request(*, request_id: int, program_id: str, commitment: str) -> dict:
    if request_id <= 0:
        raise ValueError("request_id must be positive")
    if commitment not in {"processed", "confirmed", "finalized"}:
        raise ValueError("unsupported commitment")
    if not str(program_id).strip():
        raise ValueError("program_id cannot be blank")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "logsSubscribe",
        "params": [{"mentions": [program_id]}, {"commitment": commitment}],
    }


def parse_raw_logs_notification(
    message: dict[str, Any],
    *,
    sequence: int,
    venue: str,
    program_id: str,
    wall_observed_at_ns: int,
    monotonic_observed_at_ns: int,
) -> RawIngressObservation | None:
    if message.get("method") != "logsNotification":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        raise ValueError("logsNotification missing params")
    result = params.get("result")
    if not isinstance(result, dict):
        raise ValueError("logsNotification missing result")
    context = result.get("context")
    value = result.get("value")
    if not isinstance(context, dict) or not isinstance(value, dict):
        raise ValueError("logsNotification missing context/value")
    if value.get("err") is not None:
        return None

    signature = str(value.get("signature", "")).strip()
    logs = value.get("logs")
    if not signature or not isinstance(logs, list):
        raise ValueError("invalid logsNotification signature/logs")
    slot = int(context.get("slot"))
    return RawIngressObservation(
        sequence=sequence,
        venue=venue,
        program_id=program_id,
        signature=signature,
        slot=slot,
        wall_observed_at_ns=int(wall_observed_at_ns),
        monotonic_observed_at_ns=int(monotonic_observed_at_ns),
        logs=tuple(str(item) for item in logs),
    )


def _write_jsonl(handle, payload: dict) -> None:
    handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    handle.flush()


def _hydrate_transaction(
    client: SolanaClient,
    signature: str,
    *,
    commitment: str,
) -> dict | None:
    return client.call(
        "getTransaction",
        [
            signature,
            {
                "encoding": "json",
                "commitment": commitment,
                "maxSupportedTransactionVersion": 0,
            },
        ],
        max_attempts=1,
    )


async def _hydrate_with_retry(
    client: SolanaClient,
    observation: RawIngressObservation,
    *,
    commitment: str,
    attempts: int,
    retry_delay_ms: int,
) -> tuple[dict | None, int, str | None]:
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.to_thread(
                _hydrate_transaction,
                client,
                observation.signature,
                commitment=commitment,
            )
        except (SolanaRPCError, OSError, TimeoutError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            result = None
        if result is not None:
            return result, attempt, None
        if attempt < attempts:
            await asyncio.sleep(retry_delay_ms / 1000.0)
    return None, attempts, last_error


async def capture_raw_transaction_corpus(
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
    started_wall_ns = time.time_ns()
    started_mono_ns = time.monotonic_ns()
    deadline_ns = started_mono_ns + int(duration_seconds * 1_000_000_000)
    writer_lock = asyncio.Lock()

    rpc_client = SolanaClient(rpc_url=rpc_url, timeout=5, fallback_urls=())
    ws_url = rpc_http_to_ws_url(rpc_url)

    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        _write_jsonl(
            handle,
            {
                "type": "trace_header",
                "version": TRACE_VERSION,
                "rpc_url_host": rpc_client.rpc_host,
                "commitment": commitment,
                "duration_seconds": duration_seconds,
                "queue_size": queue_size,
                "hydrate_workers": hydrate_workers,
                "hydrate_attempts": hydrate_attempts,
                "hydrate_retry_delay_ms": hydrate_retry_delay_ms,
                "started_wall_ns": started_wall_ns,
                "started_monotonic_ns": started_mono_ns,
                "programs": {
                    "pump": PUMP_PROGRAM_ID,
                    "pumpswap": PUMPSWAP_PROGRAM_ID,
                },
            },
        )

        async def worker(worker_id: int) -> None:
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

        workers = [asyncio.create_task(worker(i)) for i in range(hydrate_workers)]

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_queue=4096,
            ) as websocket:
                request_map = {
                    1: ("pump", PUMP_PROGRAM_ID),
                    2: ("pumpswap", PUMPSWAP_PROGRAM_ID),
                }
                subscription_map: dict[int, tuple[str, str]] = {}
                for request_id, (_, program_id) in request_map.items():
                    await websocket.send(
                        json.dumps(
                            build_logs_subscribe_request(
                                request_id=request_id,
                                program_id=program_id,
                                commitment=commitment,
                            )
                        )
                    )

                while len(subscription_map) < len(request_map):
                    ack_raw = await asyncio.wait_for(websocket.recv(), timeout=15)
                    ack = json.loads(ack_raw)
                    if "error" in ack:
                        raise RuntimeError(f"logsSubscribe failed: {ack['error']}")
                    request_id = int(ack.get("id", -1))
                    subscription_id = ack.get("result")
                    if request_id not in request_map or not isinstance(subscription_id, int):
                        raise RuntimeError("unexpected logsSubscribe acknowledgement")
                    subscription_map[subscription_id] = request_map[request_id]

                while time.monotonic_ns() < deadline_ns:
                    remaining = max(0.001, (deadline_ns - time.monotonic_ns()) / 1_000_000_000)
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
            "finished_wall_ns": finished_wall_ns,
            "elapsed_seconds": (time.monotonic_ns() - started_mono_ns) / 1_000_000_000,
            "counters": asdict(counters),
            "valid_for_decoder_parity": (
                counters.queue_overflow == 0
                and counters.hydrate_missing == 0
                and counters.hydrate_errors == 0
                and counters.hydrated == counters.queued
            ),
        }
        _write_jsonl(handle, summary)

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a bounded raw Solana transaction corpus for Pump/PumpSwap decoder parity."
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
        capture_raw_transaction_corpus(
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
