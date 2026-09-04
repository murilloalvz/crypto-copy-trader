from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time

from src.config import settings
from src.jupiter_episode_execution import (
    JUPITER_ENTRY_PROVIDER,
    JUPITER_ENTRY_PURPOSE,
    JupiterEpisodeQuoteConfig,
    JupiterEpisodeQuoteProbe,
)
from src.market_opportunity_episode_store import get_market_opportunity_episode
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v30 as v30


PASS_PUMPSWAP_WORKERS = 256
PASS_PUMP_PREPARE_WORKERS = 12
PASS_PUMPSWAP_PREPARE_SUBMITTERS = 64
PASS_PUMPSWAP_PREPARE_EXECUTOR_WORKERS = 32
PASS_DEFAULT_IO_WORKERS = 32


@dataclass(frozen=True)
class QuoteJob:
    episode_key: str
    enqueued_monotonic: float


def _terminal_reason(attempt) -> str:
    details = attempt.details or {}
    code = details.get("provider_error_code")
    message = details.get("provider_error_message") or attempt.error_message
    if code is None and not message:
        return "none"
    text = str(message or "").replace("\n", " ").replace("\r", " ")[:180]
    return f"code={code},message={text}" if code is not None else f"message={text}"


async def run_smoke_v31(
    *,
    max_quote_episodes: int,
    quote_workers: int,
    jupiter_timeout_seconds: int,
    quote_notional_usd: float,
    quote_slippage_bps: int,
    default_io_workers: int,
    **kwargs,
) -> None:
    """Run the proven v30 pipeline and probe Jupiter only on newly admitted episodes.

    This is not a new latency gate. The v30 market pipeline remains unchanged; provider work is
    enqueued only when the idempotent episode-admission store returns True, so continuation hits,
    replayed triggers and restarts cannot create duplicate Jupiter calls. A predeclared first-N
    cap keeps the first provider smoke small and prevents selection after seeing outcomes.
    """

    if max_quote_episodes <= 0 or quote_workers <= 0:
        raise ValueError("quote smoke counts must be positive")
    if jupiter_timeout_seconds <= 0 or quote_notional_usd <= 0:
        raise ValueError("quote timeout/notional must be positive")
    if not 0 <= quote_slippage_bps <= 10_000:
        raise ValueError("quote_slippage_bps must be between 0 and 10000")

    quote_queue: asyncio.Queue[QuoteJob] = asyncio.Queue(maxsize=max_quote_episodes)
    counters: Counter[str] = Counter()
    quote_latencies: list[float] = []
    original_admit = v19.admit_opportunity_episode
    selected_episode_keys: set[str] = set()
    probe = JupiterEpisodeQuoteProbe(
        JupiterEpisodeQuoteConfig(
            api_key=settings.jupiter_api_key,
            taker_public_key=settings.jupiter_taker_public_key,
            rpc_url=settings.rpc_url,
            rpc_fallback_urls=settings.rpc_fallback_urls,
            rpc_timeout_seconds=kwargs["rpc_timeout_seconds"],
            jupiter_timeout_seconds=jupiter_timeout_seconds,
            notional_usd=quote_notional_usd,
            slippage_bps=quote_slippage_bps,
        )
    )
    quote_executor = ThreadPoolExecutor(
        max_workers=quote_workers,
        thread_name_prefix="jupiter-episode-quote-v31",
    )

    def admit_and_enqueue(**admit_kwargs) -> bool:
        admitted = original_admit(**admit_kwargs)
        if not admitted:
            counters["admission_replays"] += 1
            return False
        counters["new_admissions"] += 1
        episode_key = str(admit_kwargs["episode_key"])
        if len(selected_episode_keys) >= max_quote_episodes:
            counters["not_selected_after_predeclared_cap"] += 1
            return True
        if episode_key in selected_episode_keys:
            raise RuntimeError("new admission unexpectedly selected twice")
        selected_episode_keys.add(episode_key)
        quote_queue.put_nowait(QuoteJob(episode_key, time.monotonic()))
        counters["selected_for_jupiter"] += 1
        return True

    async def quote_worker(index: int) -> None:
        loop = asyncio.get_running_loop()
        while True:
            job = await quote_queue.get()
            try:
                episode = get_market_opportunity_episode(job.episode_key)
                if episode is None:
                    counters["missing_episode_after_admission"] += 1
                    continue
                started = time.monotonic()
                result = await loop.run_in_executor(
                    quote_executor,
                    probe.capture,
                    episode,
                )
                finished = time.monotonic()
                quote_latencies.append(finished - job.enqueued_monotonic)
                counters[f"status_{result.attempt.status.lower()}"] += 1
                if result.reused_attempt:
                    counters["reused_attempts"] += 1
                if result.quote is not None:
                    counters["quotes_persisted"] += 1
                    if result.quote.executable:
                        counters["executable_quotes"] += 1
                print(
                    f"[jupiter-episode] worker={index} episode={job.episode_key[-12:]} "
                    f"status={result.attempt.status} "
                    f"latency_ms={(finished-started)*1000.0:.1f} "
                    f"executable={bool(result.quote and result.quote.executable)} "
                    f"reason={_terminal_reason(result.attempt)}"
                )
            except Exception as exc:
                counters["quote_worker_errors"] += 1
                print(
                    f"[jupiter-episode-error] worker={index} episode={job.episode_key[-12:]} "
                    f"error={type(exc).__name__}:{exc}"
                )
            finally:
                quote_queue.task_done()

    workers = [
        asyncio.create_task(quote_worker(index), name=f"jupiter-quote-{index}")
        for index in range(quote_workers)
    ]
    v19.admit_opportunity_episode = admit_and_enqueue
    try:
        await v30.run_smoke_v30(default_io_workers=default_io_workers, **kwargs)
        await quote_queue.join()
    finally:
        v19.admit_opportunity_episode = original_admit
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        quote_executor.shutdown(wait=True, cancel_futures=False)

    selected = counters["selected_for_jupiter"]
    available = counters["status_available"]
    explicit_terminal = sum(
        counters[f"status_{status}"]
        for status in (
            "available",
            "unavailable",
            "config_missing",
            "provider_error",
            "metadata_error",
            "normalization_error",
        )
    )
    coverage = 100.0 * explicit_terminal / selected if selected else 0.0
    availability = 100.0 * available / selected if selected else 0.0

    print("\nV31 JUPITER NEW-EPISODE EXECUTABLE QUOTE DIAGNOSTIC")
    print(
        f"provider={JUPITER_ENTRY_PROVIDER} purpose={JUPITER_ENTRY_PURPOSE} "
        f"new_admissions={counters['new_admissions']} selected={selected} "
        f"predeclared_cap={max_quote_episodes} quote_workers={quote_workers}"
    )
    print(
        f"statuses={{'AVAILABLE': {available}, "
        f"'UNAVAILABLE': {counters['status_unavailable']}, "
        f"'CONFIG_MISSING': {counters['status_config_missing']}, "
        f"'PROVIDER_ERROR': {counters['status_provider_error']}, "
        f"'METADATA_ERROR': {counters['status_metadata_error']}, "
        f"'NORMALIZATION_ERROR': {counters['status_normalization_error']}}} "
        f"attempt_terminal_coverage_pct={coverage:.1f}% "
        f"executable_availability_pct={availability:.1f}%"
    )
    print(
        f"quotes_persisted={counters['quotes_persisted']} "
        f"executable_quotes={counters['executable_quotes']} "
        f"reused_attempts={counters['reused_attempts']} "
        f"quote_worker_errors={counters['quote_worker_errors']} "
        f"not_selected_after_predeclared_cap={counters['not_selected_after_predeclared_cap']}"
    )
    print(f"episode_to_quote_terminal_ms {v19._latency_summary_ms(quote_latencies)}")
    print(
        "v31 calls Jupiter only after a first-time episode admission. It never signs or submits "
        "the assembled transaction. Missing/unavailable/error results are persisted explicitly "
        "and must not be replaced by candles or later quotes."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market v31 first Jupiter executable-quote smoke"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=PASS_PUMP_PREPARE_WORKERS)
    parser.add_argument("--pumpswap-workers", type=int, default=PASS_PUMPSWAP_WORKERS)
    parser.add_argument(
        "--pumpswap-prepare-submitters",
        type=int,
        default=PASS_PUMPSWAP_PREPARE_SUBMITTERS,
    )
    parser.add_argument(
        "--pumpswap-prepare-executor-workers",
        type=int,
        default=PASS_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
    )
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--default-io-workers", type=int, default=PASS_DEFAULT_IO_WORKERS)
    parser.add_argument("--max-quote-episodes", type=int, default=12)
    parser.add_argument("--quote-workers", type=int, default=2)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--quote-notional-usd", type=float, default=25.0)
    parser.add_argument("--quote-slippage-bps", type=int, default=100)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    try:
        v30.validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        parser.error(str(exc))
    for name in (
        "max_quote_episodes",
        "quote_workers",
        "jupiter_timeout_seconds",
        "quote_notional_usd",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")
    if not 0 <= args.quote_slippage_bps <= 10_000:
        parser.error("quote-slippage-bps must be between 0 and 10000")

    print("Crypto Copy Trader — Unified Market Execution Quote Smoke v31")
    print("Mode: PAPER / RESEARCH / READ ONLY — Jupiter order assembly only; no signing/execute.")
    kwargs = dict(
        run_key=args.run_key,
        duration_seconds=args.duration_seconds,
        commitment=args.commitment,
        max_hydrations=args.max_hydrations,
        rpc_timeout_seconds=args.rpc_timeout_seconds,
        pump_batch_size=args.pump_batch_size,
        pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
        pump_prepare_workers=args.pump_prepare_workers,
        pumpswap_workers=args.pumpswap_workers,
        pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
        pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
        pumpswap_writer_batch_size=args.pumpswap_writer_batch_size,
        pumpswap_writer_batch_max_wait_ms=args.pumpswap_writer_batch_max_wait_ms,
        max_concurrent_resolutions=args.max_concurrent_resolutions,
        queue_size=args.queue_size,
        continuation_batch_size=args.continuation_batch_size,
        continuation_batch_max_wait_ms=args.continuation_batch_max_wait_ms,
    )
    asyncio.run(
        run_smoke_v31(
            max_quote_episodes=args.max_quote_episodes,
            quote_workers=args.quote_workers,
            jupiter_timeout_seconds=args.jupiter_timeout_seconds,
            quote_notional_usd=args.quote_notional_usd,
            quote_slippage_bps=args.quote_slippage_bps,
            default_io_workers=args.default_io_workers,
            **kwargs,
        )
    )


if __name__ == "__main__":
    main()
