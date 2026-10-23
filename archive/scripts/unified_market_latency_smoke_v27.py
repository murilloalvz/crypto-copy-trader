from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import threading
import time

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v24 as v24
from src import database
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_radar_bridge import MarketRadarBridgeHit
from src.market_trigger_continuation_writer import (
    ContinuationTriggerRecord,
    MarketTriggerContinuationWriter,
)
from src.pump_radar_bridge_v4 import PumpRadarBridgeV4Result
from src.pumpswap_radar_bridge_v2 import PumpSwapRadarBridgeV2Hit
from src.pumpswap_radar_bridge_v4 import (
    PumpSwapRadarBridgeV4Result,
    PumpSwapRadarBridgeV4Telemetry,
)


class _EpisodeContinuationCache:
    """Run-local immutable episode-window cache used only for continuation classification."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._episodes_by_token: dict[str, list[MarketOpportunityEpisode]] = {}

    def remember(self, episode: MarketOpportunityEpisode) -> None:
        with self._lock:
            items = self._episodes_by_token.setdefault(episode.token_mint, [])
            if any(item.episode_key == episode.episode_key for item in items):
                return
            items.append(episode)
            items.sort(key=lambda item: item.first_trigger_observed_at)

    def find(self, token_mint: str, observed_at: int) -> MarketOpportunityEpisode | None:
        with self._lock:
            items = tuple(self._episodes_by_token.get(token_mint, ()))
        for episode in reversed(items):
            if (
                episode.first_trigger_observed_at
                <= observed_at
                < episode.episode_closes_at
            ):
                return episode
        return None


def _prepared_token_observed_at(prepared, token) -> int:
    token_as_of = getattr(token, "token_as_of", None)
    if token_as_of is not None:
        return int(token_as_of)
    return int(prepared.observed_at)


def _prepared_requires_stateful_episode(
    prepared,
    cache: _EpisodeContinuationCache,
) -> bool:
    """True only when at least one detector-positive token may need episode assignment."""

    for token in prepared.tokens:
        if token.trigger is None:
            continue
        observed_at = _prepared_token_observed_at(prepared, token)
        if cache.find(token.token_mint, observed_at) is None:
            return True
    return False


def _record_counter(counter: Counter[str], lock: threading.Lock, key: str, amount: int = 1) -> None:
    with lock:
        counter[key] += amount


async def run_smoke_v27(
    *,
    continuation_batch_size: int = 32,
    continuation_batch_max_wait_ms: int = 5,
    **kwargs,
):
    """Run v26 semantics with continuation hits removed from the critical commit path.

    The detector remains level-triggered and every raw trigger remains auditable. Only the
    first trigger that may establish a canonical episode requires synchronous stateful
    assignment. Once that immutable episode window is known in this run, later positive
    notifications for the same token/window return against the canonical episode immediately
    and append their trigger rows through a dedicated thread-owned SQLite microbatch writer.

    A job classified as stateful is rechecked at finalize time through the same run-local
    episode cache. This lets a burst of notifications prepared before the opener committed be
    demoted to continuation work after the first stateful predecessor establishes the episode.
    Late-earlier/cross-source cases that fall before the canonical episode T0 still take the
    original store path, preserving the no-retroactive-enrollment conflict semantics.
    """

    if continuation_batch_size <= 0:
        raise ValueError("continuation_batch_size must be positive")
    if continuation_batch_max_wait_ms < 0:
        raise ValueError("continuation_batch_max_wait_ms cannot be negative")

    cache = _EpisodeContinuationCache()
    stats: Counter[str] = Counter()
    stats_lock = threading.Lock()
    writer = MarketTriggerContinuationWriter(
        batch_size=continuation_batch_size,
        max_wait_ms=continuation_batch_max_wait_ms,
    )

    original_has_trigger = v19._prepared_has_trigger
    original_pump_finalize = v19.finalize_prepared_pump_radar_v5
    original_pumpswap_finalize = v19.finalize_prepared_pumpswap_radar_v5

    def continuation_aware_has_trigger(prepared) -> bool:
        has_raw_trigger = any(token.trigger is not None for token in prepared.tokens)
        if not has_raw_trigger:
            _record_counter(stats, stats_lock, "no_trigger_classifications")
            return False
        requires_stateful = _prepared_requires_stateful_episode(prepared, cache)
        _record_counter(
            stats,
            stats_lock,
            "stateful_candidate_classifications" if requires_stateful else "continuation_only_classifications",
        )
        return requires_stateful

    def finalize_pump(prepared, *, acquisition_run_key: str):
        hits: list[MarketRadarBridgeHit] = []
        for token in prepared.tokens:
            trigger = token.trigger
            if trigger is None:
                continue
            trigger_key = f"market-radar:pump:{prepared.signature}:{token.token_mint}"
            observed_at = int(prepared.observed_at)
            episode = cache.find(token.token_mint, observed_at)
            if episode is None:
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key=acquisition_run_key,
                    trigger_key=trigger_key,
                    token_mint=token.token_mint,
                    trigger_kind=trigger.trigger_kind,
                    direction=trigger.direction,
                    chain_time=token.trigger_chain_time,
                    observed_at=observed_at,
                    method_version=trigger.method_version,
                    venue="pump_bonding_curve",
                )
                cache.remember(episode)
                if episode.first_trigger_key == trigger_key:
                    _record_counter(stats, stats_lock, "stateful_episode_openers")
                else:
                    _record_counter(stats, stats_lock, "stateful_store_reuses")
            else:
                writer.enqueue(
                    ContinuationTriggerRecord(
                        acquisition_run_key=acquisition_run_key,
                        episode_key=episode.episode_key,
                        trigger_key=trigger_key,
                        token_mint=token.token_mint,
                        trigger_kind=trigger.trigger_kind,
                        direction=trigger.direction,
                        chain_time=token.trigger_chain_time,
                        observed_at=observed_at,
                        method_version=trigger.method_version,
                        venue="pump_bonding_curve",
                    )
                )
                _record_counter(stats, stats_lock, "continuation_audit_enqueued")
            hits.append(
                MarketRadarBridgeHit(
                    token_mint=token.token_mint,
                    trigger=trigger,
                    episode=episode,
                )
            )

        return PumpRadarBridgeV4Result(
            signature=prepared.signature,
            observed_at=prepared.observed_at,
            newly_persisted_trades=prepared.persist_result.newly_persisted_trades,
            affected_tokens=prepared.affected_tokens,
            hits=tuple(hits),
        )

    def finalize_pumpswap(prepared, *, acquisition_run_key: str):
        hits: list[PumpSwapRadarBridgeV2Hit] = []
        episode_assign_seconds = 0.0
        for token in prepared.tokens:
            trigger = token.trigger
            if trigger is None:
                continue
            trigger_key = (
                f"market-radar:pumpswap-v3:{prepared.signature}:{token.token_mint}"
            )
            observed_at = int(token.token_as_of)
            episode = cache.find(token.token_mint, observed_at)
            if episode is None:
                started = time.perf_counter()
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key=acquisition_run_key,
                    trigger_key=trigger_key,
                    token_mint=token.token_mint,
                    trigger_kind=trigger.trigger_kind,
                    direction=trigger.direction,
                    chain_time=token.trigger_chain_time,
                    observed_at=observed_at,
                    method_version=trigger.method_version,
                    venue="pump_swap",
                )
                episode_assign_seconds += time.perf_counter() - started
                cache.remember(episode)
                if episode.first_trigger_key == trigger_key:
                    _record_counter(stats, stats_lock, "stateful_episode_openers")
                else:
                    _record_counter(stats, stats_lock, "stateful_store_reuses")
            else:
                writer.enqueue(
                    ContinuationTriggerRecord(
                        acquisition_run_key=acquisition_run_key,
                        episode_key=episode.episode_key,
                        trigger_key=trigger_key,
                        token_mint=token.token_mint,
                        trigger_kind=trigger.trigger_kind,
                        direction=trigger.direction,
                        chain_time=token.trigger_chain_time,
                        observed_at=observed_at,
                        method_version=trigger.method_version,
                        venue="pump_swap",
                    )
                )
                _record_counter(stats, stats_lock, "continuation_audit_enqueued")
            hits.append(
                PumpSwapRadarBridgeV2Hit(
                    token_mint=token.token_mint,
                    trigger=trigger,
                    episode=episode,
                )
            )

        return PumpSwapRadarBridgeV4Result(
            signature=prepared.signature,
            observed_at=prepared.observed_at,
            persist_result=prepared.persist_result,
            affected_tokens=prepared.affected_tokens,
            hits=tuple(hits),
            telemetry=PumpSwapRadarBridgeV4Telemetry(
                token_count=len(prepared.tokens),
                transaction_view_read_seconds=prepared.transaction_view_read_seconds,
                history_read_seconds=prepared.history_read_seconds,
                detect_seconds=prepared.detect_seconds,
                episode_assign_seconds=episode_assign_seconds,
            ),
        )

    v19._prepared_has_trigger = continuation_aware_has_trigger
    v19.finalize_prepared_pump_radar_v5 = finalize_pump
    v19.finalize_prepared_pumpswap_radar_v5 = finalize_pumpswap

    kwargs = dict(kwargs)
    kwargs["stateful_only_finalize"] = True
    queue_before_drain = 0
    close_error: BaseException | None = None
    try:
        return await v24.run_smoke_v24(**kwargs)
    finally:
        v19._prepared_has_trigger = original_has_trigger
        v19.finalize_prepared_pump_radar_v5 = original_pump_finalize
        v19.finalize_prepared_pumpswap_radar_v5 = original_pumpswap_finalize
        queue_before_drain = writer.queue_size
        try:
            await writer.close(cancel_pending=False)
        except BaseException as exc:
            close_error = exc

        print("\nV27 EPISODE CONTINUATION FAST-PATH / AUDIT WRITER DIAGNOSTIC")
        print(
            f"stateful_candidate_classifications={stats['stateful_candidate_classifications']} "
            f"continuation_only_classifications={stats['continuation_only_classifications']} "
            f"no_trigger_classifications={stats['no_trigger_classifications']} "
            f"stateful_episode_openers={stats['stateful_episode_openers']} "
            f"stateful_store_reuses={stats['stateful_store_reuses']} "
            f"continuation_audit_enqueued={stats['continuation_audit_enqueued']}"
        )
        print(
            f"continuation_writer_queue_before_drain={queue_before_drain} "
            f"continuation_writer_queue_after_drain={writer.queue_size} "
            f"continuation_writer_batches={len(writer.batch_sizes)} "
            f"continuation_writer_fatal_error={writer.fatal_exception is not None}"
        )
        print(
            f"continuation_writer_queue_wait_ms {v19._latency_summary_ms(writer.queue_wait_seconds)}"
        )
        print(
            f"continuation_writer_result_wait_ms {v19._latency_summary_ms(writer.result_wait_seconds)}"
        )
        print(
            f"continuation_writer_batch_service_ms {v19._latency_summary_ms(writer.batch_service_seconds)}"
        )
        avg_batch = (
            sum(writer.batch_sizes) / len(writer.batch_sizes)
            if writer.batch_sizes
            else 0.0
        )
        print(
            f"continuation_writer_microbatch batches={len(writer.batch_sizes)} "
            f"avg_size={avg_batch:.2f} max_size={max(writer.batch_sizes, default=0)} "
            f"configured_size={continuation_batch_size} "
            f"max_wait_ms={continuation_batch_max_wait_ms}"
        )
        print(
            "v27 keeps every detector-positive hit audit-visible. Only a trigger that may establish "
            "episode state blocks on assign_market_opportunity_trigger; continuation rows are "
            "append-only audit work batched off the causal availability path."
        )
        if close_error is not None:
            raise close_error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v27 episode continuation fast path"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=4)
    parser.add_argument("--pumpswap-workers", type=int, default=64)
    parser.add_argument("--pumpswap-prepare-submitters", type=int, default=48)
    parser.add_argument("--pumpswap-prepare-executor-workers", type=int, default=12)
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    for name in (
        "pump_batch_size",
        "pump_prepare_workers",
        "pumpswap_workers",
        "pumpswap_prepare_submitters",
        "pumpswap_prepare_executor_workers",
        "pumpswap_writer_batch_size",
        "max_concurrent_resolutions",
        "queue_size",
        "continuation_batch_size",
        "max_hydrations",
        "rpc_timeout_seconds",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    if args.pumpswap_writer_batch_max_wait_ms < 0:
        parser.error("pumpswap-writer-batch-max-wait-ms cannot be negative")
    if args.continuation_batch_max_wait_ms < 0:
        parser.error("continuation-batch-max-wait-ms cannot be negative")

    journal_mode, synchronous = v19._enable_wal_mode()
    print("Crypto Copy Trader — Unified Market Latency Smoke v27 Episode Continuation Fast Path")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pump_prepare_workers={args.pump_prepare_workers} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"episode_opener_commit_executor_workers=1 "
        f"continuation_writer_threads=1 "
        f"continuation_batch_size={args.continuation_batch_size} "
        f"continuation_batch_max_wait_ms={args.continuation_batch_max_wait_ms} "
        f"sqlite_transaction_mode=IMMEDIATE "
        f"sqlite_busy_timeout_ms={int(database._SQLITE_BUSY_TIMEOUT_SECONDS * 1000)} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v27 does not change detector thresholds or episode semantics. Episode establishment remains "
        "stateful and serialized; repeated level-triggered hits inside an already-canonical episode "
        "use an append-only microbatched audit writer and do not block causal result availability."
    )

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
    )
    try:
        asyncio.run(
            run_smoke_v27(
                continuation_batch_size=args.continuation_batch_size,
                continuation_batch_max_wait_ms=args.continuation_batch_max_wait_ms,
                **kwargs,
            )
        )
    finally:
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
