from __future__ import annotations

import asyncio
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
import functools
import threading
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


def _load_existing_run_transaction_tokens(
    *, acquisition_run_key: str,
) -> dict[str, set[str]]:
    """Load replay-safety transaction assets once for a run.

    v19 originally queried SQLite once per PumpSwap notification before issuing its
    early reservation. Under burst load that four-thread read executor became a
    throughput ceiling. A run-scoped bootstrap preserves the same conservative replay
    knowledge while moving the hot path to an in-memory union.
    """

    ensure_market_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT transaction_key, token_mint
            FROM market_trade_observations
            WHERE acquisition_run_key=? AND venue='pumpswap'
              AND transaction_key IS NOT NULL
            ORDER BY transaction_key, token_mint""",
            (acquisition_run_key,),
        ).fetchall()
    indexed: dict[str, set[str]] = {}
    for row in rows:
        transaction_key = str(row["transaction_key"] or "").strip()
        token_mint = str(row["token_mint"] or "").strip()
        if not transaction_key or not token_mint:
            continue
        indexed.setdefault(transaction_key, set()).add(token_mint)
    return indexed


class PumpSwapEarlyReservationAssetIndex:
    """Run-scoped replay asset index for early PumpSwap reservations.

    The index is bootstrapped from canonical SQLite state once, then conservatively
    unions every causally normalized incoming token before that notification is sent
    to the writer. It removes the per-notification SQLite read from the latency-critical
    path without weakening the existing fail-closed canonical-result guard.
    """

    def __init__(
        self,
        *,
        acquisition_run_key: str,
        tokens_by_transaction: dict[str, set[str]] | None = None,
    ) -> None:
        run_key = str(acquisition_run_key).strip()
        if not run_key:
            raise ValueError("acquisition_run_key cannot be empty")
        self.acquisition_run_key = run_key
        self._tokens_by_transaction = {
            str(transaction_key): {str(token) for token in tokens if str(token).strip()}
            for transaction_key, tokens in (tokens_by_transaction or {}).items()
            if str(transaction_key).strip()
        }
        self._lock = threading.Lock()

    @classmethod
    def load_from_store(cls, *, acquisition_run_key: str) -> "PumpSwapEarlyReservationAssetIndex":
        run_key = str(acquisition_run_key).strip()
        if not run_key:
            raise ValueError("acquisition_run_key cannot be empty")
        return cls(
            acquisition_run_key=run_key,
            tokens_by_transaction=_load_existing_run_transaction_tokens(
                acquisition_run_key=run_key
            ),
        )

    def reservation_assets(
        self,
        prepared: PreparedPumpSwapPersistenceV3,
    ) -> tuple[str, ...]:
        if prepared.acquisition_run_key != self.acquisition_run_key:
            raise ValueError("reservation asset index run key mismatch")
        incoming = set(_incoming_trade_tokens(prepared))
        transaction_key = str(prepared.transaction_key).strip()
        with self._lock:
            known = self._tokens_by_transaction.setdefault(transaction_key, set())
            known.update(incoming)
            return tuple(sorted(known))


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
    reservation_asset_index: PumpSwapEarlyReservationAssetIndex | None = None,
) -> DeferredPumpSwapPersistHandle:
    """Normalize causally, emit a safe reservation hint, then persist asynchronously.

    The writer future is deliberately *not* awaited here. Callers may establish the
    per-asset FIFO reservation from ``reservation_assets`` immediately and await the
    canonical persistence result independently. Without a run-scoped asset index the
    legacy isolated replay-safety read remains available for compatibility.
    """

    prepared = await prepare_pumpswap_notification_normalized_v3(
        notification,
        acquisition_run_key=acquisition_run_key,
        resolver=resolver,
    )
    if reservation_asset_index is not None:
        reservation_assets = reservation_asset_index.reservation_assets(prepared)
    else:
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
