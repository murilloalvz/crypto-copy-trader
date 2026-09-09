"""Causal protocol-state adapters for decoded Carbon events.

This module intentionally handles only protocol facts that are explicitly present in
decoded events. It does not infer pool identity, token orientation, migration, or
liquidity state from later trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.market_protocol_facts import PumpSwapPoolObservation


CARBON_PROTOCOL_ADAPTER_VERSION = "carbon_protocol_adapter_v0"
ADAPTED = "ADAPTED"
UNSUPPORTED_EVENT = "UNSUPPORTED_EVENT"
INVALID_EVENT = "INVALID_EVENT"


@dataclass(frozen=True)
class CarbonProtocolAdaptationResultV0:
    method_version: str
    event_key: str | None
    status: str
    pool_observation: PumpSwapPoolObservation | None
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


def adapt_carbon_pumpswap_create_pool_v0(
    row: Mapping[str, Any], *, observed_at: int
) -> CarbonProtocolAdaptationResultV0:
    event_key = _text(row, "event_key")
    if row.get("status") != "decoded" or row.get("event_type") != "pumpswap_create_pool":
        return CarbonProtocolAdaptationResultV0(
            method_version=CARBON_PROTOCOL_ADAPTER_VERSION,
            event_key=event_key,
            status=UNSUPPORTED_EVENT,
            pool_observation=None,
            provenance_keys=(),
            data_quality_flags=("carbon_row_not_decoded_pumpswap_create_pool",),
        )
    if not isinstance(observed_at, int) or isinstance(observed_at, bool) or observed_at < 0:
        raise ValueError("observed_at must be a non-negative integer")

    pool = _text(row, "pool")
    base_mint = _text(row, "base_mint")
    quote_mint = _text(row, "quote_mint")
    chain_time = _nonnegative_int(row, "timestamp")
    if (
        event_key is None
        or pool is None
        or base_mint is None
        or quote_mint is None
        or chain_time is None
        or observed_at < chain_time
    ):
        return CarbonProtocolAdaptationResultV0(
            method_version=CARBON_PROTOCOL_ADAPTER_VERSION,
            event_key=event_key,
            status=INVALID_EVENT,
            pool_observation=None,
            provenance_keys=(),
            data_quality_flags=("pumpswap_create_pool_missing_or_invalid_identity_fields",),
        )

    observation = PumpSwapPoolObservation(
        token_mint=base_mint,
        pool=pool,
        chain_time=chain_time,
        observed_at=observed_at,
        evidence_key=event_key,
        source="carbon_pumpswap_create_pool_event",
        base_mint=base_mint,
        quote_mint=quote_mint,
    )
    return CarbonProtocolAdaptationResultV0(
        method_version=CARBON_PROTOCOL_ADAPTER_VERSION,
        event_key=event_key,
        status=ADAPTED,
        pool_observation=observation,
        provenance_keys=(event_key,),
        data_quality_flags=(),
    )
