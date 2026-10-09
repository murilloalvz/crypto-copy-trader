from __future__ import annotations

import argparse
import asyncio
import time

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v20 as v20


async def _event_loop_lag_monitor(
    samples: list[float],
    stop: asyncio.Event,
    *,
    interval_seconds: float = 0.020,
) -> None:
    """Measure scheduler delay without changing the v20 acquisition pipeline."""

    loop = asyncio.get_running_loop()
    expected = loop.time() + interval_seconds
    while not stop.is_set():
        await asyncio.sleep(max(0.0, expected - loop.time()))
        now = loop.time()
        samples.append(max(0.0, now - expected))
        expected += interval_seconds
        # Do not spin through a large catch-up burst after a long loop stall.
        if expected < now:
            expected = now + interval_seconds


def _lag_count(samples: list[float], threshold_seconds: float) -> int:
    return sum(1 for item in samples if item >= threshold_seconds)


async def run_smoke_v21(**kwargs):
    """Run v20 unchanged while sampling event-loop scheduling lag.

    v20 removed the per-notification replay-safety SQLite read and restored burst
    throughput, but its remaining p95 tail can still be caused by synchronous work on
    the asyncio thread. v21 intentionally changes no detector, persistence, reservation,
    FIFO, provider, writer, prepare or finalize semantics. It only adds one lightweight
    20ms scheduler-lag probe so the next architecture change is evidence-driven.
    """

    samples: list[float] = []
    stop = asyncio.Event()
    monitor = asyncio.create_task(
        _event_loop_lag_monitor(samples, stop),
        name="unified-market-event-loop-lag-monitor",
    )
    try:
        return await v20.run_smoke_v20(**kwargs)
    finally:
        stop.set()
        if not monitor.done():
            try:
                await asyncio.wait_for(monitor, timeout=0.1)
            except asyncio.TimeoutError:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
        print("\nV21 EVENT LOOP LAG DIAGNOSTIC")
        print(
            f"event_loop_lag_ms {v19._latency_summary_ms(samples)} "
            f"samples={len(samples)} "
            f"ge_100ms={_lag_count(samples, 0.100)} "
            f"ge_250ms={_lag_count(samples, 0.250)} "
            f"ge_500ms={_lag_count(samples, 0.500)} "
            f"ge_1000ms={_lag_count(samples, 1.000)}"
        )
        print(
            "v21 is diagnostic-only: acquisition, detector, replay, reservation, writer, "
            "prepare and FIFO finalize behavior are identical to v20."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v21 event-loop lag diagnostic"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=64)
    parser.add_argument("--pumpswap-prepare-submitters", type=int, default=48)
    parser.add_argument("--pumpswap-prepare-executor-workers", type=int, default=12)
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    if args.pump_batch_size <= 1:
        parser.error("pump-batch-size must be greater than 1")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    if args.pumpswap_writer_batch_size <= 1:
        parser.error("pumpswap-writer-batch-size must be greater than 1")
    if args.pumpswap_writer_batch_max_wait_ms < 0:
        parser.error("pumpswap-writer-batch-max-wait-ms cannot be negative")
    for name in (
        "max_hydrations",
        "rpc_timeout_seconds",
        "pumpswap_workers",
        "pumpswap_prepare_submitters",
        "pumpswap_prepare_executor_workers",
        "max_concurrent_resolutions",
        "queue_size",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")

    journal_mode, synchronous = v19._enable_wal_mode()
    print("Crypto Copy Trader — Unified Market Latency Smoke v21 Event Loop Lag Diagnostic")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} pumpswap_sqlite_writer_threads=1 "
        f"pumpswap_writer_loop=thread_owned "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"pumpswap_reservation_watermark=post_normalization_pre_writer_result "
        f"pumpswap_reservation_replay_index=preloaded_once "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"event_loop_lag_probe_ms=20 "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v21 keeps v20 behavior frozen and only samples scheduler lag. No latency threshold, "
        "worker count, detector rule, replay rule, provider policy or FIFO semantic changed."
    )

    kwargs = dict(
        run_key=args.run_key,
        duration_seconds=args.duration_seconds,
        commitment=args.commitment,
        max_hydrations=args.max_hydrations,
        rpc_timeout_seconds=args.rpc_timeout_seconds,
        pump_batch_size=args.pump_batch_size,
        pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
        pumpswap_workers=args.pumpswap_workers,
        pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
        pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
        pumpswap_writer_batch_size=args.pumpswap_writer_batch_size,
        pumpswap_writer_batch_max_wait_ms=args.pumpswap_writer_batch_max_wait_ms,
        max_concurrent_resolutions=args.max_concurrent_resolutions,
        queue_size=args.queue_size,
    )
    try:
        asyncio.run(run_smoke_v21(**kwargs))
    finally:
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
