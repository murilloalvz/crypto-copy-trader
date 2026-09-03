from dataclasses import dataclass

from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPoolResolver


@dataclass(frozen=True)
class PumpSwapNormalizedPersistResult:
    newly_persisted_trades: int
    duplicate_or_replayed_trades: int
    unresolved_trades: int
    role_filtered_trades: int
    newly_persisted_lifecycle: int
    role_filtered_lifecycle: int
    affected_tokens: tuple[str, ...] = ()


async def persist_pumpswap_notification_normalized(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
) -> PumpSwapNormalizedPersistResult:
    """Persist PumpSwap observations in opportunity-token semantics.

    Raw pool identity remains ``base_mint/quote_mint`` in the pool store. Market observations are
    normalized to the single non-reference asset when the pair contains exactly one v1 reference
    asset. If the opportunity token is the quote side, PumpSwap base-relative buy/sell semantics
    are inverted before persistence. Conflicting replays are audited by the shared market store;
    they do not overwrite a causally earlier observation or crash acquisition.

    ``affected_tokens`` is loaded back from the canonical transaction view after persistence. This
    is intentionally based on the stored canonical identity, not the incoming decoded identity, so
    downstream per-asset ordering cannot be confused by a replay conflict whose incoming token was
    rejected in favor of an earlier observation.
    """

    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("PumpSwap resolver run key does not match persistence run key")

    newly_persisted_lifecycle = 0
    role_filtered_lifecycle = 0
    for event in notification.lifecycle_events:
        resolver.learn_from_create(event, observed_at=notification.observed_at)
        role = classify_pumpswap_opportunity_asset(
            base_mint=event.base_mint,
            quote_mint=event.quote_mint,
        )
        if role is None:
            role_filtered_lifecycle += 1
            continue
        if record_market_lifecycle(
            acquisition_run_key=run_key,
            event_key=f"pumpswap-create-normalized:{notification.signature}:{event.event_index}",
            source_provider="solana_logs_subscribe",
            observation=MarketLifecycleObservation(
                token_mint=role.opportunity_mint,
                market_started_at=event.timestamp,
                observed_at=notification.observed_at,
                venue="pumpswap",
            ),
        ):
            newly_persisted_lifecycle += 1

    inserted = 0
    duplicates = 0
    unresolved = 0
    role_filtered = 0
    for event in notification.trade_events:
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
        normalized_side = role.normalize_event_side(event.side)
        observation = MarketTradeObservation(
            token_mint=role.opportunity_mint,
            side=normalized_side,
            chain_time=event.timestamp,
            observed_at=effective_observed_at,
            wallet_address=event.user,
            notional_usd=None,
            price_usd=None,
            venue="pumpswap",
            transaction_key=notification.signature,
        )
        if record_market_trade(
            acquisition_run_key=run_key,
            event_key=f"pumpswap-normalized-{event.side}:{notification.signature}:{event.event_index}",
            source_provider="solana_logs_subscribe",
            observation=observation,
        ):
            inserted += 1
        else:
            duplicates += 1

    canonical_rows = load_market_trades_by_transaction(
        acquisition_run_key=run_key,
        transaction_key=notification.signature,
    )
    affected_tokens = tuple(
        sorted(
            {
                item.observation.token_mint
                for item in canonical_rows
                if item.observation.venue == "pumpswap"
            }
        )
    )

    return PumpSwapNormalizedPersistResult(
        newly_persisted_trades=inserted,
        duplicate_or_replayed_trades=duplicates,
        unresolved_trades=unresolved,
        role_filtered_trades=role_filtered,
        newly_persisted_lifecycle=newly_persisted_lifecycle,
        role_filtered_lifecycle=role_filtered_lifecycle,
        affected_tokens=affected_tokens,
    )
