"""Read-only Pons V2 bonding-curve quote math V0.

The module reproduces Pons' documented integer-order BUY/SELL quoting without
building, signing, simulating or submitting transactions.  State must already be
causally observed from a deployed curve generation.

Important: a mathematically quotable result is not a landed fill or executable
transaction proof.

Canonical documentation:
  https://docs.ponsfamily.com/v2  (Getting a quote)
Canonical constant-product library:
  ponsdotdev/ponsfamily/contractsV2/src/v2/libraries/PonsV2BondingCurveMath.sol
"""
from __future__ import annotations

from dataclasses import dataclass


BPS = 10_000
PONS_QUOTE_VERSION = "pons_v2_curve_quote_v0"

SNIPE_MODE_LIVE_VIEW = "LIVE_SNIPE_VIEW"
SNIPE_MODE_PROVEN_ABSENT = "PROVEN_NO_SNIPE_VIEW"
_ALLOWED_SNIPE_MODES = frozenset({SNIPE_MODE_LIVE_VIEW, SNIPE_MODE_PROVEN_ABSENT})

STATUS_OK = "OK"
STATUS_CURVE_CLOSED = "CURVE_CLOSED"
STATUS_SELL_CLOSED_READY_TO_GRADUATE = "SELL_CLOSED_READY_TO_GRADUATE"
STATUS_QUOTE_TOO_SMALL = "QUOTE_TOO_SMALL"


def _uint(value: int, name: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 0 or (positive and value <= 0):
        condition = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {condition}")
    return value


def _bps(value: int, name: str) -> int:
    value = _uint(value, name)
    if value > BPS:
        raise ValueError(f"{name} must be <= {BPS}")
    return value


def ceil_div(numerator: int, denominator: int) -> int:
    _uint(numerator, "numerator")
    _uint(denominator, "denominator", positive=True)
    return (numerator + denominator - 1) // denominator


def amount_out_v0(amount_in: int, reserve_in: int, reserve_out: int) -> int:
    """Pons constant-product output with no fee inside the curve step."""
    amount_in = _uint(amount_in, "amount_in", positive=True)
    reserve_in = _uint(reserve_in, "reserve_in", positive=True)
    reserve_out = _uint(reserve_out, "reserve_out", positive=True)
    return (amount_in * reserve_out) // (reserve_in + amount_in)


def amount_in_v0(amount_out: int, reserve_in: int, reserve_out: int) -> int:
    """Pons exact-output input, including the documented +1 raw-unit rounding."""
    amount_out = _uint(amount_out, "amount_out", positive=True)
    reserve_in = _uint(reserve_in, "reserve_in", positive=True)
    reserve_out = _uint(reserve_out, "reserve_out", positive=True)
    if amount_out >= reserve_out:
        raise ValueError("amount_out must be smaller than reserve_out")
    return (amount_out * reserve_in) // (reserve_out - amount_out) + 1


@dataclass(frozen=True)
class PonsCurveQuoteStateV0:
    quote_reserve_raw: int
    token_reserve_raw: int
    sellable_tokens_raw: int
    fee_bps: int
    creator_tax_bps: int
    snipe_mode: str
    current_snipe_tax_bps: int | None
    ready_to_graduate: bool
    graduated: bool
    observed_at_ns: int
    protocol_generation_key: str
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _uint(self.quote_reserve_raw, "quote_reserve_raw", positive=True)
        _uint(self.token_reserve_raw, "token_reserve_raw", positive=True)
        _uint(self.sellable_tokens_raw, "sellable_tokens_raw")
        if self.sellable_tokens_raw > self.token_reserve_raw:
            raise ValueError("sellable_tokens_raw cannot exceed token_reserve_raw")
        fee = _bps(self.fee_bps, "fee_bps")
        tax = _bps(self.creator_tax_bps, "creator_tax_bps")
        # Pons V2 currently caps each ordinary leg at 10% and the combined
        # ordinary trade charge at 20%. Keep this as a protocol-state guard.
        if fee > 1_000 or tax > 1_000 or fee + tax > 2_000:
            raise ValueError("Pons V2 base fee / creator tax exceeds documented bounds")
        if self.snipe_mode not in _ALLOWED_SNIPE_MODES:
            raise ValueError(f"unsupported snipe_mode: {self.snipe_mode}")
        if self.snipe_mode == SNIPE_MODE_LIVE_VIEW:
            if self.current_snipe_tax_bps is None:
                raise ValueError("LIVE_SNIPE_VIEW requires causal current_snipe_tax_bps")
            _bps(self.current_snipe_tax_bps, "current_snipe_tax_bps")
        else:
            if self.current_snipe_tax_bps not in (None, 0):
                raise ValueError("PROVEN_NO_SNIPE_VIEW cannot carry a nonzero snipe tax")
        if not isinstance(self.ready_to_graduate, bool):
            raise TypeError("ready_to_graduate must be bool")
        if not isinstance(self.graduated, bool):
            raise TypeError("graduated must be bool")
        _uint(self.observed_at_ns, "observed_at_ns")
        if not isinstance(self.protocol_generation_key, str) or not self.protocol_generation_key.strip():
            raise ValueError("protocol_generation_key must be non-empty")
        for item in self.provenance:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("provenance entries must be non-empty strings")

    @property
    def applied_snipe_tax_bps(self) -> int:
        if self.snipe_mode == SNIPE_MODE_PROVEN_ABSENT:
            return 0
        raw = int(self.current_snipe_tax_bps or 0)
        if raw == 0:
            return 0
        # Official quote docs cap the opening tax so the buyer always retains
        # at least 1% of spend after base fee + creator tax + snipe tax.
        max_snipe = BPS - self.fee_bps - self.creator_tax_bps - 100
        if max_snipe < 0:
            raise ValueError("ordinary charges leave no room for the documented 1% net floor")
        return min(raw, max_snipe)


@dataclass(frozen=True)
class PonsBuyQuoteV0:
    method_version: str
    status: str
    requested_quote_raw: int
    spent_quote_raw: int
    refund_quote_raw: int
    net_curve_input_raw: int
    fee_raw: int
    creator_tax_raw: int
    snipe_tax_raw: int
    applied_snipe_tax_bps: int
    tokens_out_raw: int
    partial_fill: bool
    mathematically_quotable: bool
    fill_claimed: bool
    state_observed_at_ns: int
    protocol_generation_key: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class PonsSellQuoteV0:
    method_version: str
    status: str
    tokens_in_raw: int
    gross_quote_out_raw: int
    fee_raw: int
    creator_tax_raw: int
    quote_out_raw: int
    mathematically_quotable: bool
    fill_claimed: bool
    state_observed_at_ns: int
    protocol_generation_key: str
    notes: tuple[str, ...]


def _buy_charges(spent: int, state: PonsCurveQuoteStateV0) -> tuple[int, int, int, int]:
    fee = (spent * state.fee_bps) // BPS
    creator_tax = (spent * state.creator_tax_bps) // BPS
    snipe_tax = (spent * state.applied_snipe_tax_bps) // BPS
    net = spent - fee - creator_tax - snipe_tax
    return fee, creator_tax, snipe_tax, net


def quote_buy_v0(*, state: PonsCurveQuoteStateV0, quote_in_raw: int) -> PonsBuyQuoteV0:
    requested = _uint(quote_in_raw, "quote_in_raw", positive=True)
    common_notes = (
        "read_only_math_not_fill",
        "state_must_be_causally_observed_from_the_target_curve",
        "recipient_specific_snipe_state_is_explicit_input_when_supported",
    )
    if state.graduated or state.sellable_tokens_raw == 0:
        return PonsBuyQuoteV0(
            PONS_QUOTE_VERSION, STATUS_CURVE_CLOSED, requested, 0, requested, 0,
            0, 0, 0, state.applied_snipe_tax_bps, 0, False, False, False,
            state.observed_at_ns, state.protocol_generation_key,
            common_notes + ("buy_closed_when_sellable_tokens_is_zero_or_curve_graduated",),
        )

    spent = requested
    fee, creator_tax, snipe_tax, net = _buy_charges(spent, state)
    if net <= 0:
        return PonsBuyQuoteV0(
            PONS_QUOTE_VERSION, STATUS_QUOTE_TOO_SMALL, requested, spent, 0, net,
            fee, creator_tax, snipe_tax, state.applied_snipe_tax_bps, 0, False,
            False, False, state.observed_at_ns, state.protocol_generation_key,
            common_notes + ("net_curve_input_is_zero",),
        )

    tokens_out = amount_out_v0(net, state.quote_reserve_raw, state.token_reserve_raw)
    partial = tokens_out > state.sellable_tokens_raw
    if partial:
        tokens_out = state.sellable_tokens_raw
        # sellable > 0 here.  Because Pons reserves a pool allocation,
        # sellable is normally strictly below token_reserve.  Validate rather
        # than invent a drain-to-zero rule if an impossible state is supplied.
        net_required = amount_in_v0(
            tokens_out, state.quote_reserve_raw, state.token_reserve_raw
        )
        denominator = BPS - state.fee_bps - state.creator_tax_bps - state.applied_snipe_tax_bps
        if denominator <= 0:
            raise ValueError("invalid gross-up denominator for partial Pons buy")
        grossed = ceil_div(net_required * BPS, denominator)
        spent = min(grossed, requested)
        fee, creator_tax, snipe_tax, net = _buy_charges(spent, state)

    if tokens_out <= 0:
        return PonsBuyQuoteV0(
            PONS_QUOTE_VERSION, STATUS_QUOTE_TOO_SMALL, requested, spent,
            requested - spent, net, fee, creator_tax, snipe_tax,
            state.applied_snipe_tax_bps, 0, partial, False, False,
            state.observed_at_ns, state.protocol_generation_key,
            common_notes + ("integer_curve_output_is_zero",),
        )

    return PonsBuyQuoteV0(
        PONS_QUOTE_VERSION, STATUS_OK, requested, spent, requested - spent, net,
        fee, creator_tax, snipe_tax, state.applied_snipe_tax_bps, tokens_out,
        partial, True, False, state.observed_at_ns, state.protocol_generation_key,
        common_notes + (
            "partial_fill_reprices_from_token_side_and_refunds_remainder"
            if partial else "full_requested_quote_is_spent",
        ),
    )


def quote_sell_v0(*, state: PonsCurveQuoteStateV0, tokens_in_raw: int) -> PonsSellQuoteV0:
    tokens_in = _uint(tokens_in_raw, "tokens_in_raw", positive=True)
    notes = (
        "read_only_math_not_fill",
        "sell_has_no_snipe_tax",
        "state_must_be_causally_observed_from_the_target_curve",
    )
    if state.graduated:
        return PonsSellQuoteV0(
            PONS_QUOTE_VERSION, STATUS_CURVE_CLOSED, tokens_in, 0, 0, 0, 0,
            False, False, state.observed_at_ns, state.protocol_generation_key,
            notes + ("graduated_curve_routes_to_uniswap_v4",),
        )
    if state.ready_to_graduate:
        return PonsSellQuoteV0(
            PONS_QUOTE_VERSION, STATUS_SELL_CLOSED_READY_TO_GRADUATE,
            tokens_in, 0, 0, 0, 0, False, False, state.observed_at_ns,
            state.protocol_generation_key,
            notes + ("sell_closes_as_soon_as_ready_to_graduate_is_true",),
        )

    gross = amount_out_v0(tokens_in, state.token_reserve_raw, state.quote_reserve_raw)
    fee = (gross * state.fee_bps) // BPS
    creator_tax = (gross * state.creator_tax_bps) // BPS
    quote_out = gross - fee - creator_tax
    if quote_out <= 0:
        return PonsSellQuoteV0(
            PONS_QUOTE_VERSION, STATUS_QUOTE_TOO_SMALL, tokens_in, gross, fee,
            creator_tax, quote_out, False, False, state.observed_at_ns,
            state.protocol_generation_key, notes + ("integer_quote_output_is_zero",),
        )
    return PonsSellQuoteV0(
        PONS_QUOTE_VERSION, STATUS_OK, tokens_in, gross, fee, creator_tax,
        quote_out, True, False, state.observed_at_ns, state.protocol_generation_key,
        notes,
    )
