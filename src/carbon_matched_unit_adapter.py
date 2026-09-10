"""Causal adapters from Carbon canonical event rows to matched-unit flow facts.

Pump TradeEvent carries its quote mint, quote amount and virtual quote reserves directly,
so it can be adapted without external context. PumpSwap Buy/Sell events carry quote
amount/reserves but not quote identity; they are adapted only when exact pool identity
was already causally available by the event's local observation time. Missing context
remains missing and is never backfilled or assumed to be SOL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.market_protocol_facts import PumpSwapPoolObservation
from src.matched_unit_flow import MatchedUnitFlowObservation
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


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


@dataclass(frozen=True)
class _PoolIdentityContext:
    token_mint: str
    quote_mint: str
    evidence_key: str


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


def _causal_pool_state_context(
    *,
    pool: str,
    event_chain_time: int,
    event_observed_at: int,
    pool_observations: Sequence[PumpSwapPoolObservation],
) -> tuple[_PoolIdentityContext | None, str | None]:
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
    assert canonical.quote_mint is not None
    return _PoolIdentityContext(
        token_mint=canonical.token_mint,
        quote_mint=canonical.quote_mint,
        evidence_key=canonical.evidence_key,
    ), None


def _causal_pool_identity_context(
    *,
    pool: str,
    event_observed_at: int,
    event_observed_wall_ns: int | None,
    pool_identity_observations: Sequence[PumpSwapPoolIdentityObservation],
) -> tuple[_PoolIdentityContext | None, str | None]:
    eligible: list[PumpSwapPoolIdentityObservation] = []
    for item in pool_identity_observations:
        if item.pool != pool:
            continue
        if event_observed_wall_ns is not None:
            if item.observed_wall_ns > event_observed_wall_ns:
                continue
        elif item.observed_at > event_observed_at:
            continue
        eligible.append(item)

    if not eligible:
        return None, MISSING_CONTEXT

    identities = {(item.base_mint, item.quote_mint) for item in eligible}
    if len(identities) != 1:
        return None, CONFLICTING_CONTEXT
    canonical = max(
        eligible,
        key=lambda item: (item.observed_wall_ns, item.observed_slot, item.evidence_key),
    )
    return _PoolIdentityContext(
        token_mint=canonical.base_mint,
        quote_mint=canonical.quote_mint,
        evidence_key=canonical.evidence_key,
    ), None


def _causal_pool_context(
    *,
    pool: str,
    event_chain_time: int,
    event_observed_at: int,
    event_observed_wall_ns: int | None,
    pool_observations: Sequence[PumpSwapPoolObservation],
    pool_identity_observations: Sequence[PumpSwapPoolIdentityObservation],
) -> tuple[_PoolIdentityContext | None, str | None]:
    state_context, state_error = _causal_pool_state_context(
        pool=pool,
        event_chain_time=event_chain_time,
        event_observed_at=event_observed_at,
        pool_observations=pool_observations,
    )
    identity_context, identity_error = _causal_pool_identity_context(
        pool=pool,
        event_observed_at=event_observed_at,
        event_observed_wall_ns=event_observed_wall_ns,
        pool_identity_observations=pool_identity_observations,
    )

    if state_error == CONFLICTING_CONTEXT or identity_error == CONFLICTING_CONTEXT:
        return None, CONFLICTING_CONTEXT
    if state_context is not None and identity_context is not None:
        if (
            state_context.token_mint != identity_context.token_mint
            or state_context.quote_mint != identity_context.quote_mint
        ):
            return None, CONFLICTING_CONTEXT
        return state_context, None
    if state_context is not None:
        return state_context, None
    if identity_context is not None:
        return identity_context, None
    return None, MISSING_CONTEXT


def adapt_carbon_pumpswap_trade_v0(
    row: Mapping[str, Any],
    *,
    observed_at: int,
    pool_observations: Sequence[PumpSwapPoolObservation],
    pool_identity_observations: Sequence[PumpSwapPoolIdentityObservation] = (),
    observed_wall_ns: int | None = None,
) -> CarbonMatchedUnitAdaptationResultV0:
    """Adapt PumpSwap Buy/Sell with exact pool identity available before the event."""

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
    if observed_wall_ns is not None and (
        not isinstance(observed_wall_ns, int)
        or isinstance(observed_wall_ns, bool)
        or observed_wall_ns < 0
    ):
        raise ValueError("observed_wall_ns must be a non-negative integer when present")

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
        event_observed_wall_ns=observed_wall_ns,
        pool_observations=pool_observations,
        pool_identity_observations=pool_identity_observations,
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
