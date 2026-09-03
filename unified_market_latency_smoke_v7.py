import argparse
import asyncio

from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS, run_smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified market latency smoke v7")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=24)
    parser.add_argument("--pumpswap-radar-workers", type=int, default=4)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if args.duration_seconds <= 0 or args.duration_seconds > MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")
    if args.pump_batch_size <= 1:
        parser.error("pump-batch-size must be greater than 1 for v7")
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

    print("Crypto Copy Trader — Unified Market Latency Smoke v7")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_radar_workers={args.pumpswap_radar_workers} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size}"
    )

    try:
        asyncio.run(
            run_smoke(
                run_key=args.run_key,
                duration_seconds=args.duration_seconds,
                commitment=args.commitment,
                max_hydrations=args.max_hydrations,
                rpc_timeout_seconds=args.rpc_timeout_seconds,
                pump_workers=1,
                pumpswap_workers=args.pumpswap_workers,
                max_concurrent_resolutions=args.max_concurrent_resolutions,
                queue_size=args.queue_size,
                pump_microbatch_size=args.pump_batch_size,
                pump_microbatch_max_wait_ms=args.pump_batch_max_wait_ms,
                pumpswap_radar_workers=args.pumpswap_radar_workers,
            )
        )
    finally:
        _print_replay_telemetry(args.run_key)

    print(
        "v7 keeps the v6 ordered Pump microbatch writer and changes only PumpSwap radar scheduling. "
        "Persistence completions are dispatched in websocket ingress order, then per-asset tickets "
        "preserve FIFO for every shared opportunity token while disjoint assets can be evaluated "
        "concurrently. Detector thresholds, causal clocks, replay semantics, and provider policy are "
        "unchanged. Execution/risk providers are not called."
    )


if __name__ == "__main__":
    main()
