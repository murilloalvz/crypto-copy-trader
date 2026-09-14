"""Adapter from existing causal Pump protocol facts to direct BUY quote state.

No network call is performed. The adapter only reuses facts already available in the
Market-First research surface at the same ``as_of`` clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_protocol_facts import MarketProtocolFactsV0
from src.pump_bonding_curve_buy_quote_v0 import PumpBondingCurveStateV0


PUMP_QUOTE_STATE_ADAPTER_VERSION = "pump_direct_buy_quote_state_adapter_v0"
STATE_READY = "READY"
STATE_CURVE_COMPLETE = "CURVE_COMPLETE"
STATE_MISSING = "MISSING_CAUSAL_PUMP_STATE"


@dataclass(frozen=True)
class PumpDirectBuyQuoteStateEvidenceV0:
    method_version: str
    status: str
    token_mint: str
    as_of: int
    quote_mint: str | None
    latest_observed_at: int | None
    state: PumpBondingCurveStateV0 | None
    missing_fields: tuple[str, ...]
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def adapt_pump_protocol_facts_to_buy_quote_state_v0(
    facts: MarketProtocolFactsV0,
) -> PumpDirectBuyQuoteStateEvidenceV0:
    if not isinstance(facts, MarketProtocolFactsV0):
        raise TypeError("facts must be MarketProtocolFactsV0")

    if facts.pump_curve_complete is True or facts.canonical_migration_proven:
        return PumpDirectBuyQuoteStateEvidenceV0(
            method_version=PUMP_QUOTE_STATE_ADAPTER_VERSION,
            status=STATE_CURVE_COMPLETE,
            token_mint=facts.token_mint,
            as_of=facts.as_of,
            quote_mint=facts.pump_quote_mint,
            latest_observed_at=facts.pump_latest_observed_at,
            state=None,
            missing_fields=(),
            provenance_keys=facts.provenance_keys,
            data_quality_flags=facts.data_quality_flags,
        )

    required = {
        "pump_curve_complete": facts.pump_curve_complete,
        "pump_virtual_token_reserves": facts.pump_virtual_token_reserves,
        "pump_virtual_quote_reserves": facts.pump_virtual_quote_reserves,
        "pump_real_token_reserves": facts.pump_real_token_reserves,
    }
    missing = tuple(sorted(name for name, value in required.items() if value is None))
    if not facts.pump_activity_observed or missing:
        return PumpDirectBuyQuoteStateEvidenceV0(
            method_version=PUMP_QUOTE_STATE_ADAPTER_VERSION,
            status=STATE_MISSING,
            token_mint=facts.token_mint,
            as_of=facts.as_of,
            quote_mint=facts.pump_quote_mint,
            latest_observed_at=facts.pump_latest_observed_at,
            state=None,
            missing_fields=missing,
            provenance_keys=facts.provenance_keys,
            data_quality_flags=tuple(
                sorted({*facts.data_quality_flags, "direct_pump_quote_state_incomplete"})
            ),
        )

    state = PumpBondingCurveStateV0(
        virtual_token_reserves_raw=int(facts.pump_virtual_token_reserves),
        virtual_quote_reserves_raw=int(facts.pump_virtual_quote_reserves),
        real_token_reserves_raw=int(facts.pump_real_token_reserves),
        complete=False,
    )
    return PumpDirectBuyQuoteStateEvidenceV0(
        method_version=PUMP_QUOTE_STATE_ADAPTER_VERSION,
        status=STATE_READY,
        token_mint=facts.token_mint,
        as_of=facts.as_of,
        quote_mint=facts.pump_quote_mint,
        latest_observed_at=facts.pump_latest_observed_at,
        state=state,
        missing_fields=(),
        provenance_keys=facts.provenance_keys,
        data_quality_flags=facts.data_quality_flags,
    )
