"""Causal same-unit flow/reserve facts for Market-First research.

The generic market flow snapshot intentionally carries USD notionals while protocol
liquidity can be expressed in raw quote-token units. This module closes that
dimensional gap without manufacturing a price conversion: each observation pairs a
raw quote amount with a reserve reported in the *same quote asset and raw unit*.

Surfaces are never blended implicitly. Pump bonding-curve liquidity, PumpSwap pools,
and any future venues remain separate by ``venue + market_surface_key +
quote_asset_key + reserve_kind``. The output is descriptive research evidence only;
it has no score, confidence, recommendation, or trading action.
"""

from __future__ import annotations

from dataclasses import dataclass


MATCHED_UNIT_FLOW_VERSION = "matched_unit_flow_v0"
DEFAULT_MATCHED_UNIT_WINDOWS_SECONDS = (10, 30, 60, 300)
_VALID_SIDES = frozenset({"buy", "sell"})


@dataclass(frozen=True)
class MatchedUnitFlowObservation:
    token_mint: str
    side: str
    chain_time: int
    observed_at: int
    venue: str
    market_surface_key: str
    quote_asset_key: str
    quote_amount_raw: int
    quote_reserve_raw: int
    reserve_kind: str
    evidence_key: str


@dataclass(frozen=True)
class MatchedUnitFlowSurfaceWindowV0:
    window_seconds: int
    venue: str
    market_surface_key: str
    quote_asset_key: str
    reserve_kind: str
    event_count: int
    buy_count: int
    sell_count: int
    signed_quote_amount_raw: int
    gross_quote_amount_raw: int
    first_quote_reserve_raw: int
    last_quote_reserve_raw: int
    signed_quote_over_first_reserve_pct: float
    gross_quote_turnover_over_first_reserve_pct: float
    cumulative_signed_event_reserve_fraction_pct: float
    cumulative_gross_event_reserve_fraction_pct: float
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class MatchedUnitFlowFactsV0:
    method_version: str
    token_mint: str
    as_of: int
    windows_seconds: tuple[int, ...]
    surface_windows: tuple[MatchedUnitFlowSurfaceWindowV0, ...]
    available: bool
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _require_nonnegative_int(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_positive_int(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_matched_unit_flow_observation(item: MatchedUnitFlowObservation) -> None:
    _require_text("token_mint", item.token_mint)
    _require_text("venue", item.venue)
    _require_text("market_surface_key", item.market_surface_key)
    _require_text("quote_asset_key", item.quote_asset_key)
    _require_text("reserve_kind", item.reserve_kind)
    _require_text("evidence_key", item.evidence_key)
    if item.side not in _VALID_SIDES:
        raise ValueError("side must be 'buy' or 'sell'")
    _require_nonnegative_int("chain_time", item.chain_time)
    _require_nonnegative_int("observed_at", item.observed_at)
    if item.observed_at < item.chain_time:
        raise ValueError("observed_at cannot precede chain_time")
    _require_positive_int("quote_amount_raw", item.quote_amount_raw)
    _require_positive_int("quote_reserve_raw", item.quote_reserve_raw)


def _canonicalize_eligible(
    observations: tuple[MatchedUnitFlowObservation, ...],
    *,
    token_mint: str,
    as_of: int,
) -> tuple[MatchedUnitFlowObservation, ...]:
    by_evidence: dict[str, MatchedUnitFlowObservation] = {}
    for item in observations:
        validate_matched_unit_flow_observation(item)
        if item.token_mint != token_mint or item.observed_at > as_of:
            continue
        previous = by_evidence.get(item.evidence_key)
        if previous is None:
            by_evidence[item.evidence_key] = item
            continue
        if previous != item:
            raise ValueError(
                "conflicting matched-unit evidence for evidence_key="
                f"{item.evidence_key!r}"
            )
    return tuple(
        sorted(
            by_evidence.values(),
            key=lambda item: (item.chain_time, item.observed_at, item.evidence_key),
        )
    )


def _surface_key(item: MatchedUnitFlowObservation) -> tuple[str, str, str, str]:
    return (
        item.venue,
        item.market_surface_key,
        item.quote_asset_key,
        item.reserve_kind,
    )


def _build_surface_window(
    rows: tuple[MatchedUnitFlowObservation, ...],
    *,
    window_seconds: int,
) -> MatchedUnitFlowSurfaceWindowV0:
    first = rows[0]
    buy_count = sum(1 for item in rows if item.side == "buy")
    sell_count = len(rows) - buy_count
    signed_quote = sum(
        item.quote_amount_raw if item.side == "buy" else -item.quote_amount_raw
        for item in rows
    )
    gross_quote = sum(item.quote_amount_raw for item in rows)
    first_reserve = first.quote_reserve_raw
    last_reserve = rows[-1].quote_reserve_raw
    signed_event_fraction = sum(
        (1.0 if item.side == "buy" else -1.0)
        * (float(item.quote_amount_raw) / float(item.quote_reserve_raw))
        for item in rows
    )
    gross_event_fraction = sum(
        float(item.quote_amount_raw) / float(item.quote_reserve_raw) for item in rows
    )

    quality: set[str] = set()
    if any(item.quote_reserve_raw != first_reserve for item in rows[1:]):
        quality.add("event_reported_quote_reserve_changed_within_window")

    return MatchedUnitFlowSurfaceWindowV0(
        window_seconds=window_seconds,
        venue=first.venue,
        market_surface_key=first.market_surface_key,
        quote_asset_key=first.quote_asset_key,
        reserve_kind=first.reserve_kind,
        event_count=len(rows),
        buy_count=buy_count,
        sell_count=sell_count,
        signed_quote_amount_raw=signed_quote,
        gross_quote_amount_raw=gross_quote,
        first_quote_reserve_raw=first_reserve,
        last_quote_reserve_raw=last_reserve,
        signed_quote_over_first_reserve_pct=(
            100.0 * float(signed_quote) / float(first_reserve)
        ),
        gross_quote_turnover_over_first_reserve_pct=(
            100.0 * float(gross_quote) / float(first_reserve)
        ),
        cumulative_signed_event_reserve_fraction_pct=100.0 * signed_event_fraction,
        cumulative_gross_event_reserve_fraction_pct=100.0 * gross_event_fraction,
        provenance_keys=tuple(item.evidence_key for item in rows),
        data_quality_flags=tuple(sorted(quality)),
    )


def build_matched_unit_flow_facts_v0(
    *,
    token_mint: str,
    as_of: int,
    observations: tuple[MatchedUnitFlowObservation, ...]
    | list[MatchedUnitFlowObservation] = (),
    windows_seconds: tuple[int, ...] = DEFAULT_MATCHED_UNIT_WINDOWS_SECONDS,
) -> MatchedUnitFlowFactsV0:
    """Build causal dimensionless flow/liquidity facts at ``as_of``.

    Availability uses the same dual-clock rule as the generic flow snapshot: an event
    must have happened inside the chain-time window *and* have been observed by T0.
    Evidence arriving after T0 is invisible. Duplicate identical evidence is idempotent;
    conflicting evidence visible by T0 fails closed.
    """

    token_mint = _require_text("token_mint", token_mint)
    _require_nonnegative_int("as_of", as_of)
    if not windows_seconds:
        raise ValueError("windows_seconds must contain positive values")
    normalized_windows: list[int] = []
    for item in windows_seconds:
        normalized_windows.append(_require_positive_int("window_seconds", item))
    if len(set(normalized_windows)) != len(normalized_windows):
        raise ValueError("windows_seconds must be unique")
    windows = tuple(sorted(normalized_windows))

    eligible = _canonicalize_eligible(
        tuple(observations), token_mint=token_mint, as_of=as_of
    )

    output: list[MatchedUnitFlowSurfaceWindowV0] = []
    for window_seconds in windows:
        lower_bound = as_of - window_seconds
        in_window = tuple(
            item for item in eligible if lower_bound < item.chain_time <= as_of
        )
        grouped: dict[
            tuple[str, str, str, str], list[MatchedUnitFlowObservation]
        ] = {}
        for item in in_window:
            grouped.setdefault(_surface_key(item), []).append(item)
        for key in sorted(grouped):
            rows = tuple(
                sorted(
                    grouped[key],
                    key=lambda item: (
                        item.chain_time,
                        item.observed_at,
                        item.evidence_key,
                    ),
                )
            )
            output.append(
                _build_surface_window(rows, window_seconds=window_seconds)
            )

    quality: set[str] = set()
    if not output:
        quality.add("matched_unit_flow_unavailable")

    provenance = tuple(item.evidence_key for item in eligible)
    return MatchedUnitFlowFactsV0(
        method_version=MATCHED_UNIT_FLOW_VERSION,
        token_mint=token_mint,
        as_of=as_of,
        windows_seconds=windows,
        surface_windows=tuple(output),
        available=bool(output),
        provenance_keys=provenance,
        data_quality_flags=tuple(sorted(quality)),
    )
