"""Read-only Pump bonding-curve BUY quote math V0.

Scope is intentionally narrow: this module implements the current Pump public-docs
`buy_exact_quote_in_v2` forward quote and its documented reverse quote. It does not
fetch chain state, derive fee tiers, build instructions, sign, submit, simulate fills,
or implement SELL quoting.

The fee rates are explicit inputs because Pump's current fee schedule can be tiered.
Callers must obtain protocol/creator fee bps causally from the relevant on-chain/config
evidence before using the quote as execution evidence.

Official formula source:
  pump-fun/pump-public-docs, idl/pump.{json,ts}, buy_exact_quote_in_v2 docs.
"""

from __future__ import annotations

from dataclasses import dataclass


PUMP_BUY_QUOTE_VERSION = "pump_bonding_curve_buy_quote_v0_official_exact_quote_in"
BPS_DENOMINATOR = 10_000

STATUS_OK = "OK"
STATUS_CURVE_COMPLETE = "CURVE_COMPLETE"
STATUS_REAL_TOKEN_RESERVE_LIMIT = "REAL_TOKEN_RESERVE_LIMIT"
STATUS_NET_QUOTE_TOO_SMALL = "NET_QUOTE_TOO_SMALL"


def _u64ish(value: int, name: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 0 or (positive and value <= 0):
        requirement = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {requirement}")
    return value


def _bps(value: int, name: str) -> int:
    value = _u64ish(value, name)
    if value > BPS_DENOMINATOR:
        raise ValueError(f"{name} must be <= {BPS_DENOMINATOR}")
    return value


def ceil_div(numerator: int, denominator: int) -> int:
    _u64ish(numerator, "numerator")
    _u64ish(denominator, "denominator", positive=True)
    return (numerator + denominator - 1) // denominator


@dataclass(frozen=True)
class PumpBondingCurveStateV0:
    virtual_token_reserves_raw: int
    virtual_quote_reserves_raw: int
    real_token_reserves_raw: int
    complete: bool

    def __post_init__(self) -> None:
        _u64ish(self.virtual_token_reserves_raw, "virtual_token_reserves_raw", positive=True)
        _u64ish(self.virtual_quote_reserves_raw, "virtual_quote_reserves_raw", positive=True)
        _u64ish(self.real_token_reserves_raw, "real_token_reserves_raw")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be bool")


@dataclass(frozen=True)
class PumpFeeBpsV0:
    protocol_fee_bps: int
    creator_fee_bps: int

    def __post_init__(self) -> None:
        _bps(self.protocol_fee_bps, "protocol_fee_bps")
        _bps(self.creator_fee_bps, "creator_fee_bps")
        if self.total_fee_bps > BPS_DENOMINATOR:
            raise ValueError("total fee bps must be <= 10_000")

    @property
    def total_fee_bps(self) -> int:
        return self.protocol_fee_bps + self.creator_fee_bps


@dataclass(frozen=True)
class PumpBuyExactQuoteInV0:
    method_version: str
    status: str
    spendable_quote_raw: int
    net_quote_raw: int | None
    protocol_fee_raw: int | None
    creator_fee_raw: int | None
    total_fee_raw: int | None
    curve_tokens_out_raw: int | None
    real_token_reserves_raw: int
    fits_real_token_reserves: bool | None
    executable_amount_claimed: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class PumpBuyDesiredTokensQuoteV0:
    method_version: str
    status: str
    desired_tokens_raw: int
    net_quote_raw: int | None
    documented_spendable_quote_raw: int | None
    protocol_fee_raw: int | None
    creator_fee_raw: int | None
    computed_total_quote_raw: int | None
    fits_real_token_reserves: bool
    executable_amount_claimed: bool
    notes: tuple[str, ...]


def _fees_for_net_quote(net_quote_raw: int, fee_bps: PumpFeeBpsV0) -> tuple[int, int]:
    protocol = ceil_div(net_quote_raw * fee_bps.protocol_fee_bps, BPS_DENOMINATOR)
    creator = ceil_div(net_quote_raw * fee_bps.creator_fee_bps, BPS_DENOMINATOR)
    return protocol, creator


def quote_buy_exact_quote_in_v0(
    *,
    state: PumpBondingCurveStateV0,
    fee_bps: PumpFeeBpsV0,
    spendable_quote_raw: int,
) -> PumpBuyExactQuoteInV0:
    """Apply Pump's documented exact-quote-in BUY formula with integer rounding.

    Pump public docs specify:
      1. net = floor(spendable * 10_000 / (10_000 + total_fee_bps))
      2. fees = ceil(net*protocol/10_000) + ceil(net*creator/10_000)
      3. if net+fees > spendable, reduce net by the overrun
      4. tokens = floor((net-1)*v_token / (v_quote+net-1))

    We conservatively refuse to call the result executable when the curve formula would
    return more than the observed real token reserves. This module does not invent a
    partial-spend/completion rule that is not specified by the quoted formula.
    """

    spendable = _u64ish(spendable_quote_raw, "spendable_quote_raw", positive=True)
    if state.complete:
        return PumpBuyExactQuoteInV0(
            method_version=PUMP_BUY_QUOTE_VERSION,
            status=STATUS_CURVE_COMPLETE,
            spendable_quote_raw=spendable,
            net_quote_raw=None,
            protocol_fee_raw=None,
            creator_fee_raw=None,
            total_fee_raw=None,
            curve_tokens_out_raw=None,
            real_token_reserves_raw=state.real_token_reserves_raw,
            fits_real_token_reserves=None,
            executable_amount_claimed=False,
            notes=("bonding_curve_complete_no_buy_quote",),
        )

    net = (spendable * BPS_DENOMINATOR) // (BPS_DENOMINATOR + fee_bps.total_fee_bps)
    protocol_fee, creator_fee = _fees_for_net_quote(net, fee_bps)
    fees = protocol_fee + creator_fee
    if net + fees > spendable:
        net -= net + fees - spendable
        if net < 0:
            net = 0
        protocol_fee, creator_fee = _fees_for_net_quote(net, fee_bps)
        fees = protocol_fee + creator_fee

    if net <= 1:
        return PumpBuyExactQuoteInV0(
            method_version=PUMP_BUY_QUOTE_VERSION,
            status=STATUS_NET_QUOTE_TOO_SMALL,
            spendable_quote_raw=spendable,
            net_quote_raw=net,
            protocol_fee_raw=protocol_fee,
            creator_fee_raw=creator_fee,
            total_fee_raw=fees,
            curve_tokens_out_raw=0,
            real_token_reserves_raw=state.real_token_reserves_raw,
            fits_real_token_reserves=True,
            executable_amount_claimed=False,
            notes=("documented_formula_requires_net_quote_minus_one",),
        )

    effective_net = net - 1
    tokens_out = (
        effective_net * state.virtual_token_reserves_raw
    ) // (state.virtual_quote_reserves_raw + effective_net)
    fits = tokens_out <= state.real_token_reserves_raw
    status = STATUS_OK if fits else STATUS_REAL_TOKEN_RESERVE_LIMIT
    notes: list[str] = [
        "read_only_quote_not_fill",
        "fee_bps_are_explicit_causal_inputs_not_derived_here",
    ]
    if not fits:
        notes.append("curve_output_exceeds_observed_real_token_reserves")

    return PumpBuyExactQuoteInV0(
        method_version=PUMP_BUY_QUOTE_VERSION,
        status=status,
        spendable_quote_raw=spendable,
        net_quote_raw=net,
        protocol_fee_raw=protocol_fee,
        creator_fee_raw=creator_fee,
        total_fee_raw=fees,
        curve_tokens_out_raw=tokens_out,
        real_token_reserves_raw=state.real_token_reserves_raw,
        fits_real_token_reserves=fits,
        executable_amount_claimed=(status == STATUS_OK and tokens_out > 0),
        notes=tuple(notes),
    )


def quote_buy_desired_tokens_v0(
    *,
    state: PumpBondingCurveStateV0,
    fee_bps: PumpFeeBpsV0,
    desired_tokens_raw: int,
) -> PumpBuyDesiredTokensQuoteV0:
    """Apply Pump's documented reverse quote for desired tokens -> spendable quote.

    Official docs specify:
      net = ceil(tokens*v_quote/(v_token-tokens)) + 1
      spendable = ceil(net*(10_000+total_fee_bps)/10_000)
    """

    tokens = _u64ish(desired_tokens_raw, "desired_tokens_raw", positive=True)
    fits = tokens <= state.real_token_reserves_raw
    if state.complete:
        return PumpBuyDesiredTokensQuoteV0(
            method_version=PUMP_BUY_QUOTE_VERSION,
            status=STATUS_CURVE_COMPLETE,
            desired_tokens_raw=tokens,
            net_quote_raw=None,
            documented_spendable_quote_raw=None,
            protocol_fee_raw=None,
            creator_fee_raw=None,
            computed_total_quote_raw=None,
            fits_real_token_reserves=fits,
            executable_amount_claimed=False,
            notes=("bonding_curve_complete_no_buy_quote",),
        )
    if tokens >= state.virtual_token_reserves_raw or not fits:
        return PumpBuyDesiredTokensQuoteV0(
            method_version=PUMP_BUY_QUOTE_VERSION,
            status=STATUS_REAL_TOKEN_RESERVE_LIMIT,
            desired_tokens_raw=tokens,
            net_quote_raw=None,
            documented_spendable_quote_raw=None,
            protocol_fee_raw=None,
            creator_fee_raw=None,
            computed_total_quote_raw=None,
            fits_real_token_reserves=fits,
            executable_amount_claimed=False,
            notes=("desired_tokens_exceed_curve_or_real_token_reserve_limit",),
        )

    denominator = state.virtual_token_reserves_raw - tokens
    net = ceil_div(tokens * state.virtual_quote_reserves_raw, denominator) + 1
    spendable = ceil_div(
        net * (BPS_DENOMINATOR + fee_bps.total_fee_bps), BPS_DENOMINATOR
    )
    protocol_fee, creator_fee = _fees_for_net_quote(net, fee_bps)
    computed_total = net + protocol_fee + creator_fee

    return PumpBuyDesiredTokensQuoteV0(
        method_version=PUMP_BUY_QUOTE_VERSION,
        status=STATUS_OK,
        desired_tokens_raw=tokens,
        net_quote_raw=net,
        documented_spendable_quote_raw=spendable,
        protocol_fee_raw=protocol_fee,
        creator_fee_raw=creator_fee,
        computed_total_quote_raw=computed_total,
        fits_real_token_reserves=True,
        executable_amount_claimed=True,
        notes=(
            "read_only_quote_not_fill",
            "documented_spendable_quote_uses_total_fee_bps_reverse_formula",
        ),
    )
