from __future__ import annotations

import argparse
import asyncio

import unified_market_latency_smoke_v19 as v19
from src.pumpswap_deferred_persistence_v5 import (
    PumpSwapEarlyReservationAssetIndex,
    begin_pumpswap_notification_normalized_v5,
)


async def run_smoke_v20(**kwargs):
    """Run v19 semantics with a run-scoped in-memory reservation replay index.

    v19 proved early reservations and direct FIFO successor release. v19d then exposed
    a burst-capacity ceiling because every PumpSwap notification still performed a
    replay-safety SQLite SELECT through a four-thread executor before its reservation
    hint could be emitted. v20 bootstraps that canonical transaction->asset knowledge
    once per run and conservatively unions causally normalized incoming assets in
    memory. The authoritative writer result and fail-closed superset guard are unchanged.
    """

    run_key = str(kwargs["run_key"])
    reservation_asset_index = await asyncio.to_thread(
        PumpSwapEarlyReservationAssetIndex.load_from_store,
        acquisition_run_key=run_key,
    )

    original_begin = v19.begin_pumpswap_notification_normalized_v5

    async def indexed_begin(
        notification,
        *,
        acquisition_run_key,
        resolver,
        writer,
        reservation_read_executor=None,
    ):
        return await begin_pumpswap_notification_normalized_v5(
            notification,
            acquisition_run_key=acquisition_run_key,
            resolver=resolver,
            writer=writer,
            reservation_read_executor=reservation_read_executor,
            reservation_asset_index=reservation_asset_index,
        )

    v19.begin_pumpswap_notification_normalized_v5 = indexed_begin
    try:
        return await v19.run_smoke_v19(**kwargs)
    finally:
        v19.begin_pumpswap_notification_normalized_v5 = original_begin


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v20 preloaded PumpSwap reservation replay index"
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
    print("Crypto Copy Trader — Unified Market Latency Smoke v20 Preloaded Reservation Replay Index")
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
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v20 keeps detector/provider/replay/as_of/FIFO semantics frozen. Existing canonical "
        "transaction assets are loaded once before the timed run; incoming normalized assets "
        "are unioned in memory before writer enqueue, while the canonical writer-result guard "
        "remains fatal on any missing reservation asset."
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
        asyncio.run(run_smoke_v20(**kwargs))
    finally:
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
