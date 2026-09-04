from __future__ import annotations

import argparse
import asyncio

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v20 as v20
from unified_market_latency_smoke_v21 import _event_loop_lag_monitor, _lag_count


async def run_smoke_v22(**kwargs):
    """Run v20 with sequential synchronous radar DB stages off the asyncio thread.

    v21 measured material event-loop starvation while all causal/replay gates remained
    healthy. v22 keeps the same one-at-a-time Pump radar coordinator and the same single
    PumpSwap FIFO finalizer, but executes each coordinator's synchronous SQLite stage on
    its own isolated one-thread executor. Each stage is still awaited before that
    coordinator advances, so source ordering, per-asset FIFO, detector, replay and
    decision semantics are unchanged.
    """

    samples: list[float] = []
    stop = asyncio.Event()
    monitor = asyncio.create_task(
        _event_loop_lag_monitor(samples, stop),
        name="unified-market-event-loop-lag-monitor-v22",
    )
    kwargs = dict(kwargs)
    kwargs["offload_sync_radar"] = True
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
        print("\nV22 SEQUENTIAL RADAR OFFLOAD / EVENT LOOP LAG DIAGNOSTIC")
        print(
            f"event_loop_lag_ms {v19._latency_summary_ms(samples)} "
            f"samples={len(samples)} "
            f"ge_100ms={_lag_count(samples, 0.100)} "
            f"ge_250ms={_lag_count(samples, 0.250)} "
            f"ge_500ms={_lag_count(samples, 0.500)} "
            f"ge_1000ms={_lag_count(samples, 1.000)}"
        )
        print(
            "v22 changes scheduling only: Pump radar remains ingress-sequential and PumpSwap "
            "finalize remains one-worker per-asset FIFO; their synchronous SQLite stages run "
            "on isolated one-thread executors instead of blocking the asyncio event loop."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v22 sequential radar SQLite offload"
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
    print("Crypto Copy Trader — Unified Market Latency Smoke v22 Sequential Radar Offload")
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
        f"pump_radar_executor_workers=1 pumpswap_finalize_executor_workers=1 "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"event_loop_lag_probe_ms=20 "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v22 keeps detector/provider/replay/as_of/reservation/FIFO rules frozen. Only the "
        "already-sequential synchronous Pump radar and PumpSwap finalize SQLite stages are "
        "moved off the asyncio thread."
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
        asyncio.run(run_smoke_v22(**kwargs))
    finally:
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
