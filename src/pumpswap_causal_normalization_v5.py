from __future__ import annotations

import asyncio
import time

from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
import src.pumpswap_normalized_persistence_v3 as v3


async def prepare_pumpswap_notification_causal_v5(
    notification,
    *,
    acquisition_run_key: str,
    resolver,
):
    """Normalize PumpSwap work with explicit delayed-availability resolver semantics.

    The persisted observation contract is intentionally identical to v3 except for how pool
    identity is obtained:

    * V5 resolvers may reuse identity that became durable after the notification arrived, but the
      normalized trade remains unavailable until that later mapping timestamp through the existing
      ``max(notification.observed_at, mapping.observed_at)`` rule.
    * CreatePoolEvent learning is awaited through an async resolver hook so SQLite never runs
      synchronously on the event loop.
    * Prior-run historical reuse remains constrained inside the resolver to information available no
      later than the notification's observed time.

    No detector, side normalization, event key, transaction key or replay identity changes here.
    """

    run_key = v3._required(acquisition_run_key, "acquisition_run_key")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("PumpSwap resolver run key does not match persistence run key")

    started = time.perf_counter()
    lifecycle_writes = []
    role_filtered_lifecycle = 0
    async_create = getattr(resolver, "learn_from_create_async_v5", None)

    for event in notification.lifecycle_events:
        if async_create is not None:
            await async_create(event, observed_at=notification.observed_at)
        else:
            # Compatibility fallback keeps the legacy resolver contract but still prevents a
            # synchronous pool-store write from blocking the acquisition event loop.
            await asyncio.to_thread(
                resolver.learn_from_create,
                event,
                observed_at=notification.observed_at,
            )

        role = classify_pumpswap_opportunity_asset(
            base_mint=event.base_mint,
            quote_mint=event.quote_mint,
        )
        if role is None:
            role_filtered_lifecycle += 1
            continue
        lifecycle_writes.append(
            v3._LifecycleWrite(
                event_key=(
                    f"pumpswap-create-normalized:{notification.signature}:{event.event_index}"
                ),
                observation=MarketLifecycleObservation(
                    token_mint=role.opportunity_mint,
                    market_started_at=event.timestamp,
                    observed_at=notification.observed_at,
                    venue="pumpswap",
                ),
            )
        )

    trade_writes = []
    unresolved = 0
    role_filtered = 0
    normalization_resolve = getattr(resolver, "resolve_for_normalization_v5", None)

    for event in notification.trade_events:
        if normalization_resolve is not None:
            mapping = await normalization_resolve(
                event.pool,
                observed_at=notification.observed_at,
            )
        else:
            mapping = await resolver.resolve(event.pool, as_of=notification.observed_at)
        if mapping is None:
            unresolved += 1
            continue

        role = classify_pumpswap_opportunity_asset(
            base_mint=mapping.base_mint,
            quote_mint=mapping.quote_mint,
        )
        if role is None:
            role_filtered += 1
            continue

        effective_observed_at = max(notification.observed_at, mapping.observed_at)
        trade_writes.append(
            v3._TradeWrite(
                event_key=(
                    f"pumpswap-normalized-{event.side}:"
                    f"{notification.signature}:{event.event_index}"
                ),
                observation=MarketTradeObservation(
                    token_mint=role.opportunity_mint,
                    side=role.normalize_event_side(event.side),
                    chain_time=event.timestamp,
                    observed_at=effective_observed_at,
                    wallet_address=event.user,
                    notional_usd=None,
                    price_usd=None,
                    venue="pumpswap",
                    transaction_key=notification.signature,
                ),
            )
        )

    return v3.PreparedPumpSwapPersistenceV3(
        acquisition_run_key=run_key,
        transaction_key=v3._required(notification.signature, "notification.signature"),
        lifecycle_writes=tuple(lifecycle_writes),
        trade_writes=tuple(trade_writes),
        unresolved_trades=unresolved,
        role_filtered_trades=role_filtered,
        role_filtered_lifecycle=role_filtered_lifecycle,
        resolver_and_normalize_seconds=max(0.0, time.perf_counter() - started),
    )
