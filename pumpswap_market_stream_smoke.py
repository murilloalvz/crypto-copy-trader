import argparse
import asyncio
import time

from src.config import settings
from src.pumpswap_stream import (
    PumpSwapPoolResolver,
    iter_pumpswap_log_notifications,
    persist_pumpswap_notification,
)
from src.solana import SolanaRPCError


MAX_SMOKE_SECONDS = 900


class SmokeBudgetedPoolResolver(PumpSwapPoolResolver):
    """Bound RPC hydration cost during a short operational smoke.

    The production resolver semantics remain unchanged. This wrapper limits actual network
    hydration calls and temporarily negative-caches failed pools so a hot unresolved pool cannot
    dominate the smoke or hammer the configured RPC endpoint.
    """

    def __init__(self, *args, max_network_hydrations: int, retry_seconds: float = 15.0, **kwargs):
        if max_network_hydrations <= 0:
            raise ValueError("max_network_hydrations must be positive")
        if retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive")
        super().__init__(*args, **kwargs)
        self.max_network_hydrations = int(max_network_hydrations)
        self.retry_seconds = float(retry_seconds)
        self.network_hydration_calls = 0
        self.hydration_budget_skips = 0
        self.negative_cache_skips = 0
        self._failed_until: dict[str, float] = {}

    def _load_pool_account(self, pool_address: str):
        now = time.monotonic()
        retry_at = self._failed_until.get(pool_address)
        if retry_at is not None and now < retry_at:
            self.negative_cache_skips += 1
            raise ValueError("PumpSwap smoke negative-cache skip")
        if self.network_hydration_calls >= self.max_network_hydrations:
            self.hydration_budget_skips += 1
            raise ValueError("PumpSwap smoke hydration budget exhausted")

        self.network_hydration_calls += 1
        try:
            result = super()._load_pool_account(pool_address)
        except (SolanaRPCError, ValueError, TypeError, KeyError):
            self._failed_until[pool_address] = time.monotonic() + self.retry_seconds
            raise
        if result is None:
            self._failed_until[pool_address] = time.monotonic() + self.retry_seconds
        else:
            self._failed_until.pop(pool_address, None)
        return result


async def run_smoke(
    *,
    run_key: str,
    duration_seconds: int,
    commitment: str,
    max_hydrations: int,
    rpc_timeout_seconds: int,
) -> None:
    started = time.monotonic()
    deadline = started + duration_seconds

    resolver = SmokeBudgetedPoolResolver(
        acquisition_run_key=run_key,
        commitment=commitment,
        rpc_url=settings.rpc_url,
        fallback_urls=settings.rpc_fallback_urls,
        timeout=rpc_timeout_seconds,
        max_network_hydrations=max_hydrations,
    )

    notifications = 0
    decoded_buys = 0
    decoded_sells = 0
    decoded_create_pools = 0
    newly_persisted_trades = 0
    duplicate_or_replayed_trades = 0
    unresolved_trades = 0
    newly_persisted_lifecycle = 0
    unique_pools: set[str] = set()
    unique_wallets: set[str] = set()
    create_event_pools: set[str] = set()

    stream = iter_pumpswap_log_notifications(
        rpc_url=settings.rpc_url,
        commitment=commitment,
    )
    iterator = stream.__aiter__()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                notification = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
            except (asyncio.TimeoutError, StopAsyncIteration):
                break

            notifications += 1
            for event in notification.trade_events:
                unique_pools.add(event.pool)
                unique_wallets.add(event.user)
                if event.side == "buy":
                    decoded_buys += 1
                else:
                    decoded_sells += 1
            for event in notification.lifecycle_events:
                unique_pools.add(event.pool)
                create_event_pools.add(event.pool)
                decoded_create_pools += 1

            result = await persist_pumpswap_notification(
                notification,
                acquisition_run_key=run_key,
                resolver=resolver,
            )
            newly_persisted_trades += result.newly_persisted_trades
            duplicate_or_replayed_trades += result.duplicate_or_replayed_trades
            unresolved_trades += result.unresolved_trades
            newly_persisted_lifecycle += result.newly_persisted_lifecycle
    finally:
        await stream.aclose()

    elapsed = time.monotonic() - started
    decoded_trades = decoded_buys + decoded_sells
    resolved_trades = newly_persisted_trades + duplicate_or_replayed_trades
    resolution_denominator = resolved_trades + unresolved_trades
    resolution_pct = (
        100.0 * resolved_trades / resolution_denominator if resolution_denominator else None
    )

    print("\nSUMMARY")
    print(
        f"elapsed={elapsed:.1f}s notifications={notifications} decoded_trades={decoded_trades} "
        f"buys={decoded_buys} sells={decoded_sells} create_pools={decoded_create_pools}"
    )
    print(
        f"persisted_trades={newly_persisted_trades} duplicate_or_replayed={duplicate_or_replayed_trades} "
        f"unresolved_trades={unresolved_trades} resolution_pct="
        f"{resolution_pct:.1f}%" if resolution_pct is not None else
        f"persisted_trades={newly_persisted_trades} duplicate_or_replayed={duplicate_or_replayed_trades} "
        f"unresolved_trades={unresolved_trades} resolution_pct=None"
    )
    print(
        f"persisted_lifecycle={newly_persisted_lifecycle} unique_pools={len(unique_pools)} "
        f"unique_wallets={len(unique_wallets)} create_event_pools={len(create_event_pools)}"
    )
    print(
        f"pool_cache_hits={resolver.cache_hits} pool_store_hits={resolver.store_hits} "
        f"hydration_attempts={resolver.hydration_attempts} hydration_successes={resolver.hydration_successes} "
        f"hydration_failures={resolver.hydration_failures} actual_network_hydrations={resolver.network_hydration_calls}"
    )
    print(
        f"hydration_budget_skips={resolver.hydration_budget_skips} "
        f"negative_cache_skips={resolver.negative_cache_skips} max_hydrations={max_hydrations} "
        f"rpc_timeout={rpc_timeout_seconds}s"
    )
    print(
        "This smoke validates PumpSwap acquisition/pool-resolution plumbing only. "
        "It does not measure edge, profitability or executable fills."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded native PumpSwap market-stream smoke")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument(
        "--commitment",
        choices=("processed", "confirmed", "finalized"),
        default="confirmed",
    )
    parser.add_argument("--max-hydrations", type=int, default=100)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    args = parser.parse_args()

    if not args.run_key.strip():
        parser.error("--run-key cannot be empty")
    if args.duration_seconds <= 0 or args.duration_seconds > MAX_SMOKE_SECONDS:
        parser.error(f"--duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")
    if args.max_hydrations <= 0:
        parser.error("--max-hydrations must be positive")
    if args.rpc_timeout_seconds <= 0 or args.rpc_timeout_seconds > 30:
        parser.error("--rpc-timeout-seconds must be between 1 and 30")

    print("Crypto Copy Trader — PumpSwap Native Market Stream Smoke")
    print("Mode: PAPER / RESEARCH / READ ONLY — no transaction signing or submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"max_hydrations={args.max_hydrations} rpc_timeout={args.rpc_timeout_seconds}s"
    )
    print(
        "Pool identity is resolved causally from CreatePoolEvent or PumpSwap Pool account hydration. "
        "Unresolved pools are counted, never guessed."
    )

    asyncio.run(
        run_smoke(
            run_key=args.run_key,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
            max_hydrations=args.max_hydrations,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
        )
    )


if __name__ == "__main__":
    main()
