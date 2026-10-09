import argparse
import asyncio

from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v8 import run_smoke_v8
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified market latency smoke v9")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=24)
    parser.add_argument("--pumpswap-radar-workers", type=int, default=8)
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

    print("Crypto Copy Trader — Unified Market Latency Smoke v9")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_radar_workers={args.pumpswap_radar_workers} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size}"
    )
    print(
        "v9 is a measured capacity stress: v8 persistence/scheduler semantics are unchanged; "
        "PumpSwap radar workers increase from 4 to 8 because v8 measured ~29.4 persisted/s "
        "versus ~18.0 radar-processed/s. Scheduler backlog telemetry is preserved before cancellation."
    )

    try:
        asyncio.run(
            run_smoke_v8(
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
