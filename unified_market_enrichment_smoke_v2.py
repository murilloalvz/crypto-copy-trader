import argparse
import asyncio
import hashlib
import time
from collections import Counter

from src.config import settings
from src.market_radar_bridge import process_pump_notification_for_radar
from src.opportunity_enrichment_store import admit_opportunity_episode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.pump_bonding_stream import iter_pump_log_notifications
from src.pumpswap_radar_bridge_v2 import process_pumpswap_notification_for_radar_v2
from src.pumpswap_reusable_resolver import ReusablePumpSwapPoolResolver
from src.pumpswap_stream import iter_pumpswap_log_notifications
from src.solana import SolanaRPCError


MAX_SMOKE_SECONDS = 900


class BoundedReusableResolver(ReusablePumpSwapPoolResolver):
    def __init__(self, *args, max_network_hydrations: int, retry_seconds: float = 15.0, **kwargs):
        if max_network_hydrations <= 0:
            raise ValueError("max_network_hydrations must be positive")
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
            raise ValueError("negative-cache skip")
        if self.network_hydration_calls >= self.max_network_hydrations:
            self.hydration_budget_skips += 1
            raise ValueError("hydration budget exhausted")
        self.network_hydration_calls += 1
        try:
            result = super()._load_pool_account(pool_address)
        except (SolanaRPCError, ValueError, TypeError, KeyError):
            self._failed_until[pool_address] = now + self.retry_seconds
            raise
        if result is None:
            self._failed_until[pool_address] = now + self.retry_seconds
        else:
            self._failed_until.pop(pool_address, None)
        return result


def _short_episode(episode_key: str) -> str:
    return hashlib.sha256(episode_key.encode("utf-8")).hexdigest()[:10]


async def run_smoke(*, run_key: str, duration_seconds: int, commitment: str,
                    max_hydrations: int, rpc_timeout_seconds: int) -> None:
    started = time.monotonic()
    deadline = started + duration_seconds
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=2000)

    resolver = BoundedReusableResolver(
        acquisition_run_key=run_key,
        commitment=commitment,
        rpc_url=settings.rpc_url,
        fallback_urls=settings.rpc_fallback_urls,
        timeout=rpc_timeout_seconds,
        max_network_hydrations=max_hydrations,
    )

    produced: Counter[str] = Counter()
    processed: Counter[str] = Counter()
    persisted: Counter[str] = Counter()
    hits_by_source: Counter[str] = Counter()
    episodes_by_source: Counter[str] = Counter()
    affected_tokens: set[str] = set()
    episodes_seen: set[str] = set()
    enrichment_admitted = 0
    flow30_total = 0
    wallets_total = 0
    risk_missing = 0
    queue_high_water = 0

    async def producer(source: str) -> None:
        stream = (iter_pump_log_notifications(rpc_url=settings.rpc_url, commitment=commitment)
                  if source == "pump" else
                  iter_pumpswap_log_notifications(rpc_url=settings.rpc_url, commitment=commitment))
        iterator = stream.__aiter__()
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    notification = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
                await queue.put((source, notification))
                produced[source] += 1
        finally:
            await stream.aclose()

    producers = [asyncio.create_task(producer("pump")), asyncio.create_task(producer("pumpswap"))]

    try:
        while time.monotonic() < deadline:
            queue_high_water = max(queue_high_water, queue.qsize())
            remaining = deadline - time.monotonic()
            try:
                source, notification = await asyncio.wait_for(queue.get(), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                continue

            processed[source] += 1
            if source == "pump":
                result = process_pump_notification_for_radar(notification, acquisition_run_key=run_key)
                persisted[source] += result.newly_persisted_trades
            else:
                result = await process_pumpswap_notification_for_radar_v2(
                    notification, acquisition_run_key=run_key, resolver=resolver
                )
                persisted[source] += result.persist_result.newly_persisted_trades

            affected_tokens.update(result.affected_tokens)
            for hit in result.hits:
                hits_by_source[source] += 1
                episode = hit.episode
                if episode.episode_key in episodes_seen:
                    continue
                episodes_seen.add(episode.episode_key)
                episodes_by_source[source] += 1

                admitted = admit_opportunity_episode(
                    acquisition_run_key=run_key,
                    episode_key=episode.episode_key,
                    admitted_at=episode.first_trigger_observed_at,
                )
                if not admitted:
                    continue
                enrichment_admitted += 1

                # No network enrichment provider is called in this smoke. The local bundle is
                # therefore anchored to the exact causal trigger availability boundary, not to
                # delayed queue-processing wall time.
                bundle = build_episode_enrichment_bundle(
                    episode=episode,
                    as_of=episode.first_trigger_observed_at,
                )
                fast30 = next(item for item in bundle.core.flow_windows if item.window_seconds == 30)
                flow30_total += fast30.event_count
                wallets_total += bundle.wallet_intelligence.participant_wallet_count
                if bundle.risk.status != "available":
                    risk_missing += 1

                print(
                    f"[episode+bundle] id={_short_episode(episode.episode_key)} source={source} "
                    f"token={episode.token_mint[:10]}… kind={episode.first_trigger_kind} "
                    f"dir={episode.first_trigger_direction} flow30={fast30.event_count} "
                    f"wallets={bundle.wallet_intelligence.participant_wallet_count} "
                    f"execution_quotes={bundle.core.execution.quote_count} risk={bundle.risk.status}"
                )
            queue.task_done()
    finally:
        for task in producers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*producers, return_exceptions=True)

    backlog: Counter[str] = Counter()
    while not queue.empty():
        source, _ = queue.get_nowait()
        backlog[source] += 1
        queue.task_done()

    elapsed = time.monotonic() - started
    resolver_operational_skips = resolver.hydration_budget_skips + resolver.negative_cache_skips
    resolver_rpc_failures = max(0, resolver.hydration_failures - resolver_operational_skips)

    print("\nSUMMARY")
    print(
        f"elapsed={elapsed:.1f}s produced={dict(produced)} processed={dict(processed)} "
        f"backlog_at_deadline={dict(backlog)} queue_high_water={queue_high_water}"
    )
    print(
        f"persisted_trades={dict(persisted)} affected_tokens={len(affected_tokens)} "
        f"raw_radar_hits={dict(hits_by_source)} unique_episodes={len(episodes_seen)} "
        f"opened_by_source={dict(episodes_by_source)} enrichment_admitted={enrichment_admitted}"
    )
    print(
        f"bundle_wallets_total={wallets_total} bundle_flow30_total={flow30_total} "
        f"risk_missing={risk_missing}"
    )
    print(
        f"pumpswap_historical_pool_hits={resolver.historical_store_hits} "
        f"pumpswap_run_store_hits={resolver.store_hits} cache_hits={resolver.cache_hits} "
        f"network_hydrations={resolver.network_hydration_calls} "
        f"hydration_successes={resolver.hydration_successes} rpc_failures={resolver_rpc_failures} "
        f"budget_skips={resolver.hydration_budget_skips} "
        f"negative_cache_skips={resolver.negative_cache_skips}"
    )
    print(
        "This bounded smoke stops at the acquisition deadline and reports backlog. "
        "Execution/risk providers are intentionally not called."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Pump + PumpSwap radar/enrichment smoke v2")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", choices=("processed", "confirmed", "finalized"), default="confirmed")
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

    print("Crypto Copy Trader — Unified Market Enrichment Smoke v2")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"max_hydrations={args.max_hydrations} rpc_timeout={args.rpc_timeout_seconds}s"
    )
    asyncio.run(run_smoke(
        run_key=args.run_key.strip(),
        duration_seconds=args.duration_seconds,
        commitment=args.commitment,
        max_hydrations=args.max_hydrations,
        rpc_timeout_seconds=args.rpc_timeout_seconds,
    ))


if __name__ == "__main__":
    main()
