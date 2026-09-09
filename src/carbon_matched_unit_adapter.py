"""Causal adapters from Carbon canonical event rows to matched-unit flow facts.

Pump TradeEvent carries its quote mint, quote amount and virtual quote reserves directly,
so it can be adapted without external context. PumpSwap Buy/Sell events carry quote
amount/reserves but not the quote mint; they are adapted only when an exact pool context
was already causally available by the event's observation time. Missing context remains
missing and is never backfilled or assumed to be SOL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.market_protocol_facts import PumpSwapPoolObservation
from src.matched_unit_flow import MatchedUnitFlowObservation


CARBON_MATCHED_UNIT_ADAPTER_VERSION = "carbon_matched_unit_adapter_v0"
ADAPTED = "ADAPTED"
MISSING_CONTEXT = "MISSING_CONTEXT"
CONFLICTING_CONTEXT = "CONFLICTING_CONTEXT"
UNSUPPORTED_EVENT = "UNSUPPORTED_EVENT"
INVALID_EVENT = "INVALID_EVENT"


@dataclass(frozen=True)
class CarbonMatchedUnitAdaptationResultV0:
    method_version: str
    event_key: str | None
    status: str
    observation: MatchedUnitFlowObservation | None
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _text(row: Mapping[str, Any], name: str) -> str | None:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _nonnegative_int(row: Mapping[str, Any], name: str) -> int | None:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _positive_int(row: Mapping[str, Any], name: str) -> int | None:
    value = _nonnegative_int(row, name)
    return value if value is not None and value > 0 else None


def _result(
    *,
    event_key: str | None,
    status: str,
    observation: MatchedUnitFlowObservation | None = None,
    provenance_keys: tuple[str, ...] = (),
    flags: tuple[str, ...] = (),
) -> CarbonMatchedUnitAdaptationResultV0:
    return CarbonMatchedUnitAdaptationResultV0(
        method_version=CARBON_MATCHED_UNIT_ADAPTER_VERSION,
        event_key=event_key,
        status=status,
        observation=observation,
        provenance_keys=provenance_keys,
        data_quality_flags=tuple(sorted(set(flags))),
    )


def adapt_carbon_pump_trade_v0(
    row: Mapping[str, Any], *, observed_at: int
) -> CarbonMatchedUnitAdaptationResultV0:
    """Adapt one decoded Carbon Pump TradeEvent using event-native quote evidence."""

    event_key = _text(row, "event_key")
    if row.get("status") != "decoded" or row.get("event_type") != "pump_trade":
        return _result(
            event_key=event_key,
            status=UNSUPPORTED_EVENT,
            flags=("carbon_row_not_decoded_pump_trade",),
        )

    if not isinstance(observed_at, int) or isinstance(observed_at, bool) or observed_at < 0:
        raise ValueError("observed_at must be a non-negative integer")

    mint = _text(row, "mint")
    side = _text(row, "side")
    quote_mint = _text(row, "quote_mint")
    chain_time = _nonnegative_int(row, "timestamp")
    quote_amount = _positive_int(row, "quote_amount_raw")
    quote_reserve = _positive_int(row, "virtual_quote_reserves_raw")
    if (
        event_key is None
        or mint is None
        or side not in {"buy", "sell"}
        or quote_mint is None
        or chain_time is None
        or quote_amount is None
        or quote_reserve is None
        or observed_at < chain_time
    ):
        return _result(
            event_key=event_key,
            status=INVALID_EVENT,
            flags=("pump_trade_missing_or_invalid_matched_unit_fields",),
        )

    observation = MatchedUnitFlowObservation(
        token_mint=mint,
        side=side,
        chain_time=chain_time,
        observed_at=observed_at,
        venue="pump",
        market_surface_key=f"pump:{mint}",
        quote_asset_key=quote_mint,
        quote_amount_raw=quote_amount,
        quote_reserve_raw=quote_reserve,
        reserve_kind="pump_virtual_quote_event",
        evidence_key=event_key,
    )
    return _result(
        event_key=event_key,
        status=ADAPTED,
        observation=observation,
        provenance_keys=(event_key,),
    )


def _causal_pool_context(
    *,
    pool: str,
    event_chain_time: int,
    event_observed_at: int,
    pool_observations: Sequence[PumpSwapPoolObservation],
) -> tuple[PumpSwapPoolObservation | None, str | None]:
    eligible = [
        item
        for item in pool_observations
        if item.pool == pool
        and item.chain_time <= event_chain_time
        and item.observed_at <= event_observed_at
        and item.quote_mint is not None
    ]
    if not eligible:
        return None, MISSING_CONTEXT

    best_clock = max((item.chain_time, item.observed_at) for item in eligible)
    best = [
        item
        for item in eligible
        if (item.chain_time, item.observed_at) == best_clock
    ]
    identities = {(item.token_mint, item.quote_mint) for item in best}
    if len(identities) != 1:
        return None, CONFLICTING_CONTEXT
    canonical = min(best, key=lambda item: item.evidence_key)
    return canonical, None


def adapt_carbon_pumpswap_trade_v0(
    row: Mapping[str, Any],
    *,
    observed_at: int,
    pool_observations: Sequence[PumpSwapPoolObservation],
) -> CarbonMatchedUnitAdaptationResultV0:
    """Adapt one PumpSwap Buy/Sell only with causal exact-pool quote-mint context."""

    event_key = _text(row, "event_key")
    event_type = row.get("event_type")
    if row.get("status") != "decoded" or event_type not in {
        "pumpswap_buy",
        "pumpswap_sell",
    }:
        return _result(
            event_key=event_key,
            status=UNSUPPORTED_EVENT,
            flags=("carbon_row_not_decoded_pumpswap_trade",),
        )
    if not isinstance(observed_at, int) or isinstance(observed_at, bool) or observed_at < 0:
        raise ValueError("observed_at must be a non-negative integer")

    pool = _text(row, "pool")
    side = _text(row, "side")
    chain_time = _nonnegative_int(row, "timestamp")
    quote_amount = _positive_int(row, "quote_amount_raw")
    quote_reserve = _positive_int(row, "pool_quote_token_reserves_raw")
    if (
        event_key is None
        or pool is None
        or side not in {"buy", "sell"}
        or chain_time is None
        or quote_amount is None
        or quote_reserve is None
        or observed_at < chain_time
    ):
        return _result(
            event_key=event_key,
            status=INVALID_EVENT,
            flags=("pumpswap_trade_missing_or_invalid_matched_unit_fields",),
        )

    context, context_error = _causal_pool_context(
        pool=pool,
        event_chain_time=chain_time,
        event_observed_at=observed_at,
        pool_observations=pool_observations,
    )
    if context is None:
        flag = (
            "pumpswap_pool_quote_context_conflict"
            if context_error == CONFLICTING_CONTEXT
            else "pumpswap_pool_quote_context_missing_at_t0"
        )
        return _result(
            event_key=event_key,
            status=context_error or MISSING_CONTEXT,
            flags=(flag,),
        )

    assert context.quote_mint is not None
    observation = MatchedUnitFlowObservation(
        token_mint=context.token_mint,
        side=side,
        chain_time=chain_time,
        observed_at=observed_at,
        venue="pumpswap",
        market_surface_key=f"pumpswap:{pool}",
        quote_asset_key=context.quote_mint,
        quote_amount_raw=quote_amount,
        quote_reserve_raw=quote_reserve,
        reserve_kind="pumpswap_pool_quote_event",
        evidence_key=event_key,
    )
    return _result(
        event_key=event_key,
        status=ADAPTED,
        observation=observation,
        provenance_keys=(event_key, context.evidence_key),
    )
