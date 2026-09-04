from __future__ import annotations

import asyncio
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
import functools
import time

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_normalized_persistence_v3 import (
    PreparedPumpSwapPersistenceV3,
    prepare_pumpswap_notification_normalized_v3,
)
from src.pumpswap_normalized_persistence_v4 import PumpSwapSQLiteThreadedMicrobatchWriter
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPoolResolver


_RESERVATION_READ_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="pumpswap-early-reservation-read",
)


@dataclass(frozen=True)
class DeferredPumpSwapPersistHandle:
    """Persistence handle returned once causal normalization is complete.

    ``reservation_assets`` is a conservative superset of the assets that can appear
    in the eventual canonical transaction readback. This lets the latency smoke issue
    ingress-ordered per-asset tickets before waiting for SQLite completion without
    weakening causal ordering. The actual persistence result is still authoritative
    for detector input and no-new-evidence handling.
    """

    reservation_assets: tuple[str, ...]
    normalization_completed_monotonic: float
    result_future: Future

    async def wait_result(self) -> PumpSwapNormalizedPersistResult:
        return await asyncio.wrap_future(self.result_future)


def _load_existing_transaction_tokens(
    *, acquisition_run_key: str,
    transaction_key: str,
) -> tuple[str, ...]:
    ensure_market_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT DISTINCT token_mint
            FROM market_trade_observations
            WHERE acquisition_run_key=? AND transaction_key=? AND venue='pumpswap'
            ORDER BY token_mint""",
            (acquisition_run_key, transaction_key),
        ).fetchall()
    return tuple(str(row["token_mint"]) for row in rows)


def _incoming_trade_tokens(prepared: PreparedPumpSwapPersistenceV3) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item.observation.token_mint)
                for item in prepared.trade_writes
                if str(item.observation.token_mint).strip()
            }
        )
    )


async def begin_pumpswap_notification_normalized_v5(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    writer: PumpSwapSQLiteThreadedMicrobatchWriter,
    reservation_read_executor: Executor | None = None,
) -> DeferredPumpSwapPersistHandle:
    """Normalize causally, emit a safe reservation hint, then persist asynchronously.

    The writer future is deliberately *not* awaited here. Callers may establish the
    per-asset FIFO reservation from ``reservation_assets`` immediately and await the
    canonical persistence result independently. Replay-safety reads use an isolated
    four-thread executor by default so they never compete with Pump's default
    ``asyncio.to_thread`` persistence path.
    """

    prepared = await prepare_pumpswap_notification_normalized_v3(
        notification,
        acquisition_run_key=acquisition_run_key,
        resolver=resolver,
    )
    loop = asyncio.get_running_loop()
    existing_tokens = await loop.run_in_executor(
        reservation_read_executor or _RESERVATION_READ_EXECUTOR,
        functools.partial(
            _load_existing_transaction_tokens,
            acquisition_run_key=acquisition_run_key,
            transaction_key=prepared.transaction_key,
        ),
    )
    reservation_assets = tuple(
        sorted(set(_incoming_trade_tokens(prepared)).union(existing_tokens))
    )
    normalization_completed = time.monotonic()
    result_future = writer.enqueue(prepared)
    return DeferredPumpSwapPersistHandle(
        reservation_assets=reservation_assets,
        normalization_completed_monotonic=normalization_completed,
        result_future=result_future,
    )
