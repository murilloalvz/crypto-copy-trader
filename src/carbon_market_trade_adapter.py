"""Narrow causal adapter from validated Carbon matched-unit events to the signal kernel.

This module deliberately does not perform decoding, Pool identity lookup, USD conversion,
price inference, persistence, or external enrichment. PumpSwap events become token-keyed
market observations only after the existing matched-unit adapter has resolved exact causal
Pool identity. Missing context remains missing and is never backfilled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.carbon_matched_unit_adapter import (
    ADAPTED,
    CONFLICTING_CONTEXT,
    INVALID_EVENT,
    MISSING_CONTEXT,
    UNSUPPORTED_EVENT,
    CarbonMatchedUnitAdaptationResultV0,
)
from src.market_opportunity_radar import MarketTradeObservation


CARBON_MARKET_TRADE_ADAPTER_VERSION = "carbon_market_trade_adapter_v0"
_VALID_EVENT_TYPES = frozenset({"pump_trade", "pumpswap_buy", "pumpswap_sell"})


@dataclass(frozen=True)
class CarbonMarketTradeAdaptationResultV0:
    method_version: str
    event_key: str | None
    status: str
    observation: MarketTradeObservation | None
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _text(row: Mapping[str, Any], name: str) -> str | None:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _result(
    *,
    event_key: str | None,
    status: str,
    observation: MarketTradeObservation | None = None,
    provenance_keys: tuple[str, ...] = (),
    flags: tuple[str, ...] = (),
) -> CarbonMarketTradeAdaptationResultV0:
    return CarbonMarketTradeAdaptationResultV0(
        method_version=CARBON_MARKET_TRADE_ADAPTER_VERSION,
        event_key=event_key,
        status=status,
        observation=observation,
        provenance_keys=provenance_keys,
        data_quality_flags=tuple(sorted(set(flags))),
    )


def adapt_carbon_matched_unit_to_market_trade_v0(
    row: Mapping[str, Any],
    matched_unit: CarbonMatchedUnitAdaptationResultV0,
) -> CarbonMarketTradeAdaptationResultV0:
    """Adapt one already-causal matched-unit trade into the indexed kernel contract."""

    event_key = _text(row, "event_key")
    if row.get("type") != "carbon_canonical_event" or row.get("status") != "decoded":
        return _result(
            event_key=event_key,
            status=UNSUPPORTED_EVENT,
            flags=("carbon_row_not_decoded_canonical_event",),
        )

    event_type = _text(row, "event_type")
    if event_type not in _VALID_EVENT_TYPES:
        return _result(
            event_key=event_key,
            status=UNSUPPORTED_EVENT,
            flags=("carbon_event_not_supported_market_trade",),
        )

    if matched_unit.status != ADAPTED or matched_unit.observation is None:
        propagated_status = (
            matched_unit.status
            if matched_unit.status
            in {MISSING_CONTEXT, CONFLICTING_CONTEXT, INVALID_EVENT, UNSUPPORTED_EVENT}
            else INVALID_EVENT
        )
        return _result(
            event_key=event_key,
            status=propagated_status,
            provenance_keys=matched_unit.provenance_keys,
            flags=matched_unit.data_quality_flags
            + ("matched_unit_observation_unavailable",),
        )

    source = matched_unit.observation
    if event_key is None or matched_unit.event_key != event_key or source.evidence_key != event_key:
        return _result(
            event_key=event_key,
            status=INVALID_EVENT,
            provenance_keys=matched_unit.provenance_keys,
            flags=("carbon_matched_unit_event_key_mismatch",),
        )

    row_side = _text(row, "side")
    row_timestamp = row.get("timestamp")
    if (
        row_side != source.side
        or not isinstance(row_timestamp, int)
        or isinstance(row_timestamp, bool)
        or row_timestamp != source.chain_time
    ):
        return _result(
            event_key=event_key,
            status=INVALID_EVENT,
            provenance_keys=matched_unit.provenance_keys,
            flags=("carbon_matched_unit_trade_semantics_mismatch",),
        )

    if event_type == "pump_trade":
        row_mint = _text(row, "mint")
        if row_mint != source.token_mint or source.venue != "pump":
            return _result(
                event_key=event_key,
                status=INVALID_EVENT,
                provenance_keys=matched_unit.provenance_keys,
                flags=("pump_trade_identity_mismatch",),
            )
        wallet = _text(row, "wallet")
    else:
        if source.venue != "pumpswap":
            return _result(
                event_key=event_key,
                status=INVALID_EVENT,
                provenance_keys=matched_unit.provenance_keys,
                flags=("pumpswap_trade_venue_mismatch",),
            )
        wallet = _text(row, "user")

    signature = _text(row, "signature")
    flags = list(matched_unit.data_quality_flags)
    if wallet is None:
        flags.append("wallet_identity_missing")
    if signature is None:
        flags.append("transaction_identity_missing")

    observation = MarketTradeObservation(
        token_mint=source.token_mint,
        side=source.side,
        chain_time=source.chain_time,
        observed_at=source.observed_at,
        wallet_address=wallet,
        notional_usd=None,
        price_usd=None,
        venue=source.venue,
        transaction_key=signature,
    )
    return _result(
        event_key=event_key,
        status=ADAPTED,
        observation=observation,
        provenance_keys=tuple(sorted(set(matched_unit.provenance_keys + (event_key,)))),
        flags=tuple(flags) + ("usd_notional_not_inferred", "usd_price_not_inferred"),
    )
