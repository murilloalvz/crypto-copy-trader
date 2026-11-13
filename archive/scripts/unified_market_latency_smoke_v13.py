import argparse
import asyncio

from src.database import connection
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v12 import run_smoke_v12
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS


def _enable_wal_mode() -> tuple[str, int]:
    """Enable SQLite WAL without changing durability/synchronous policy.

    v12 showed a strong reader/writer interference pattern once PumpSwap prepare reads
    were isolated into a 12-thread executor: prepare improved, but persistence queue
    latency regressed sharply. WAL allows concurrent readers and the single SQLite
    writer to make progress without weakening detector, replay, causal or persistence
    semantics. ``PRAGMA synchronous`` is intentionally left untouched and reported.
    """

    with connection() as conn:
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        mode = str(row[0]).lower() if row is not None else "unknown"
        sync_row = conn.execute("PRAGMA synchronous").fetchone()
        synchronous = int(sync_row[0]) if sync_row is not None else -1

    if mode != "wal":
        raise RuntimeError(f"SQLite WAL activation failed: journal_mode={mode}")
    return mode, synchronous


async def run_smoke_v13(
    *,
    run_key: str,
    duration_seconds: int,
    commitment: str,
    max_hydrations: int,
    rpc_timeout_seconds: int,
    pump_batch_size: int,
    pump_batch_max_wait_ms: int,
    pumpswap_workers: int,
    pumpswap_radar_workers: int,
    max_concurrent_resolutions: int,
    queue_size: int,
) -> None:
    await run_smoke_v12(
        run_key=run_key,
        duration_seconds=duration_seconds,
        commitment=commitment,
        max_hydrations=max_hydrations,
        rpc_timeout_seconds=rpc_timeout_seconds,
        pump_batch_size=pump_batch_size,
        pump_batch_max_wait_ms=pump_batch_max_wait_ms,
        pumpswap_workers=pumpswap_workers,
        pumpswap_radar_workers=pumpswap_radar_workers,
        max_concurrent_resolutions=max_concurrent_resolutions,
        queue_size=queue_size,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v13 WAL reader/writer coexistence"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=24)
    parser.add_argument("--pumpswap-radar-workers", type=int, default=12)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")
    if args.pump_batch_size <= 1:
        parser.error("pump-batch-size must be greater than 1")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    for name in (
        "max_hydrations",
        "rpc_timeout_seconds",
        "pumpswap_workers",
        "pumpswap_radar_workers",
        "max_concurrent_resolutions",
        "queue_size",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")

    journal_mode, synchronous = _enable_wal_mode()

    print("Crypto Copy Trader — Unified Market Latency Smoke v13 WAL")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_prepare_workers={args.pumpswap_radar_workers} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_radar_workers} "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v13 keeps v12's dedicated prepare executor and changes only SQLite journal mode "
        "to WAL so read-heavy prepare work can coexist with persistence writes. Detector, "
        "causal clocks, replay, trigger/episode and provider semantics are unchanged."
    )

    try:
        asyncio.run(
            run_smoke_v13(
                run_key=args.run_key,
                duration_seconds=args.duration_seconds,
                commitment=args.commitment,
                max_hydrations=args.max_hydrations,
                rpc_timeout_seconds=args.rpc_timeout_seconds,
                pump_batch_size=args.pump_batch_size,
                pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
                pumpswap_workers=args.pumpswap_workers,
                pumpswap_radar_workers=args.pumpswap_radar_workers,
                max_concurrent_resolutions=args.max_concurrent_resolutions,
                queue_size=args.queue_size,
            )
        )
    finally:
        _print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
