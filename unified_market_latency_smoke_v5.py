import argparse
import asyncio

from src.database import connection
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS, run_smoke


def _print_pump_replay_conflicts(run_key: str) -> None:
    with connection() as conn:
        table = conn.execute(
            """SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='pump_replay_conflicts'"""
        ).fetchone()
        if table is None:
            print("pump_replay_conflicts=0 actions={}")
            return
        rows = conn.execute(
            """SELECT canonical_action, COUNT(*) AS count
            FROM pump_replay_conflicts
            WHERE acquisition_run_key=?
            GROUP BY canonical_action
            ORDER BY canonical_action""",
            (run_key,),
        ).fetchall()
    actions = {str(row["canonical_action"]): int(row["count"]) for row in rows}
    print(f"pump_replay_conflicts={sum(actions.values())} actions={actions}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified market latency smoke v5")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1000)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-workers", type=int, default=4)
    parser.add_argument("--pumpswap-workers", type=int, default=8)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=6)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if args.duration_seconds <= 0 or args.duration_seconds > MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")

    print("Crypto Copy Trader — Unified Market Latency Smoke v5")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_workers={args.pump_workers} pumpswap_workers={args.pumpswap_workers} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size}"
    )

    asyncio.run(
        run_smoke(
            run_key=args.run_key,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
            max_hydrations=args.max_hydrations,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
            pump_workers=args.pump_workers,
            pumpswap_workers=args.pumpswap_workers,
            max_concurrent_resolutions=args.max_concurrent_resolutions,
            queue_size=args.queue_size,
        )
    )
    _print_pump_replay_conflicts(args.run_key)
    print(
        "v5 keeps v4 causal ordering/gates and hot-path schema readiness caching. "
        "Pump replay conflicts are audited with earliest-observed canonical semantics. "
        "Execution/risk providers are not called."
    )


if __name__ == "__main__":
    main()
