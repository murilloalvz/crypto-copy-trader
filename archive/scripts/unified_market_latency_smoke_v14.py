import argparse
import asyncio
from dataclasses import dataclass, field
import threading
import time

import unified_market_latency_smoke_v11 as v11
import unified_market_latency_smoke_v12 as v12
from src.pumpswap_radar_bridge_v5 import (
    prepare_persisted_pumpswap_notification_for_radar_v5 as _prepare_v5,
)
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v13 import _enable_wal_mode, run_smoke_v13
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS, _latency_summary_ms


@dataclass
class PrepareHiddenTimeDiagnostics:
    """Thread-safe timing collector for v14's unchanged v5 prepare function."""

    internal_total_seconds: list[float] = field(default_factory=list)
    accounted_seconds: list[float] = field(default_factory=list)
    unaccounted_seconds: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, *, internal_total: float, prepared) -> None:
        accounted = (
            prepared.transaction_view_read_seconds
            + prepared.history_read_seconds
            + prepared.detect_seconds
        )
        unaccounted = max(0.0, internal_total - accounted)
        with self._lock:
            self.internal_total_seconds.append(internal_total)
            self.accounted_seconds.append(accounted)
            self.unaccounted_seconds.append(unaccounted)


async def run_smoke_v14(
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
) -> PrepareHiddenTimeDiagnostics:
    """Run v13 unchanged while measuring time inside the prepare thread itself.

    v13 proved WAL removes the reader/writer persistence regression, but the outer
    prepare service clock remained much larger than the bridge's explicit DB + detector
    phase clocks. v14 changes no acquisition, persistence, detector, causal, replay,
    scheduling or provider semantics. It only wraps the exact v5 prepare callable and
    measures total wall time from inside the dedicated executor thread.
    """

    diagnostics = PrepareHiddenTimeDiagnostics()

    def instrumented_prepare(*args, **kwargs):
        started = time.perf_counter()
        prepared = _prepare_v5(*args, **kwargs)
        diagnostics.record(
            internal_total=time.perf_counter() - started,
            prepared=prepared,
        )
        return prepared

    # v11 supplies the callable to asyncio.to_thread; v12 routes that callable to the
    # dedicated executor by identity. Patch both module references to the same wrapper
    # so execution semantics stay identical while the wrapper runs inside that executor.
    original_v11_prepare = v11.prepare_persisted_pumpswap_notification_for_radar_v5
    original_v12_prepare = v12.prepare_persisted_pumpswap_notification_for_radar_v5
    v11.prepare_persisted_pumpswap_notification_for_radar_v5 = instrumented_prepare
    v12.prepare_persisted_pumpswap_notification_for_radar_v5 = instrumented_prepare
    try:
        await run_smoke_v13(
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
    finally:
        v11.prepare_persisted_pumpswap_notification_for_radar_v5 = original_v11_prepare
        v12.prepare_persisted_pumpswap_notification_for_radar_v5 = original_v12_prepare

    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v14 PumpSwap prepare hidden-time diagnostic"
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

    print("Crypto Copy Trader — Unified Market Latency Smoke v14 Prepare Hidden-Time Diagnostic")
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
        "v14 keeps v13 behavior unchanged and measures total prepare time from inside the "
        "dedicated executor thread. The delta versus explicit DB+detector clocks identifies "
        "Python/GIL work; a low inner total versus high outer service identifies executor/event-loop delay."
    )

    try:
        diagnostics = asyncio.run(
            run_smoke_v14(
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
        print("\nV14 PREPARE HIDDEN-TIME DIAGNOSTIC")
        print(f"prepare_calls={len(diagnostics.internal_total_seconds)}")
        print(
            "pumpswap_prepare_inner_total_ms "
            f"{_latency_summary_ms(diagnostics.internal_total_seconds)}"
        )
        print(
            "pumpswap_prepare_inner_accounted_ms "
            f"{_latency_summary_ms(diagnostics.accounted_seconds)}"
        )
        print(
            "pumpswap_prepare_inner_unaccounted_ms "
            f"{_latency_summary_ms(diagnostics.unaccounted_seconds)}"
        )
    finally:
        _print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
