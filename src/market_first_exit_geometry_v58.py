from __future__ import annotations

from dataclasses import dataclass
import math

from src.causal_quotes import CausalQuoteObservation, validate_causal_quote


MARKET_FIRST_EXIT_GEOMETRY_VERSION = "market_first_exit_geometry_v58"
PATH_POINT_STATUSES = {"AVAILABLE", "UNAVAILABLE", "PROVIDER_ERROR"}


@dataclass(frozen=True)
class MarketFirstExitPathPointV58:
    """One post-decision route-path observation.

    ``return_pct`` is populated only when a route-only SELL quote was actually
    available. Missing provider observations remain explicit and are never
    interpolated or treated as zero returns.
    """

    observation_key: str
    observed_at: int
    status: str
    return_pct: float | None = None
    quote_key: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class MarketFirstExitGeometryV58:
    method_version: str
    decision_as_of: int
    scheduled_points: int
    available_points: int
    unavailable_or_error_points: int
    coverage_pct: float
    first_available_offset_seconds: int | None
    last_available_offset_seconds: int | None
    mfe_pct: float | None
    mae_pct: float | None
    time_to_mfe_seconds: int | None
    time_to_mae_seconds: int | None
    last_observed_return_pct: float | None
    peak_to_last_giveback_pct_points: float | None
    last_observed_mfe_capture_pct: float | None
    max_available_gap_seconds: int | None
    classification: str


def route_only_return_from_quotes_v58(
    *,
    entry_quote: CausalQuoteObservation,
    exit_quote: CausalQuoteObservation,
    decision_as_of: int,
) -> float:
    """Compute the same route-only return surface used by current route research.

    This helper is deliberately stricter than a generic price comparison: entry
    must be a non-executable BUY known by the decision clock, exit must be a
    later non-executable SELL for the same token, and when raw route amounts are
    present the SELL must dispose of the exact raw token amount produced by BUY.
    """

    validate_causal_quote(entry_quote)
    validate_causal_quote(exit_quote)
    cutoff = int(decision_as_of)
    if cutoff < 0:
        raise ValueError("decision_as_of must be non-negative")
    if entry_quote.token_mint != exit_quote.token_mint:
        raise ValueError("entry/exit token mismatch")
    if entry_quote.side != "buy" or exit_quote.side != "sell":
        raise ValueError("route geometry requires BUY entry and SELL exit")
    if entry_quote.executable or exit_quote.executable:
        raise ValueError("v58 geometry accepts route-only non-executable quotes")
    if entry_quote.observed_at > cutoff:
        raise ValueError("entry quote was not known by decision_as_of")
    if exit_quote.observed_at <= cutoff:
        raise ValueError("exit quote must be observed strictly after decision_as_of")

    if entry_quote.output_mint is not None and entry_quote.output_mint != entry_quote.token_mint:
        raise ValueError("BUY output mint does not match researched token")
    if exit_quote.input_mint is not None and exit_quote.input_mint != exit_quote.token_mint:
        raise ValueError("SELL input mint does not match researched token")

    entry_token_raw = entry_quote.output_amount_raw
    exit_token_raw = exit_quote.input_amount_raw
    if (entry_token_raw is None) != (exit_token_raw is None):
        raise ValueError("raw token amount lineage is incomplete")
    if entry_token_raw is not None and str(entry_token_raw) != str(exit_token_raw):
        raise ValueError("SELL does not use exact raw BUY token output")

    value = 100.0 * (exit_quote.price_usd / entry_quote.price_usd - 1.0)
    if not math.isfinite(value):
        raise ValueError("route-only return is non-finite")
    return value


def available_path_point_from_quotes_v58(
    *,
    observation_key: str,
    quote_key: str,
    entry_quote: CausalQuoteObservation,
    exit_quote: CausalQuoteObservation,
    decision_as_of: int,
) -> MarketFirstExitPathPointV58:
    observation = str(observation_key).strip()
    artifact = str(quote_key).strip()
    if not observation or not artifact:
        raise ValueError("observation_key and quote_key are required")
    value = route_only_return_from_quotes_v58(
        entry_quote=entry_quote,
        exit_quote=exit_quote,
        decision_as_of=decision_as_of,
    )
    return MarketFirstExitPathPointV58(
        observation_key=observation,
        observed_at=int(exit_quote.observed_at),
        status="AVAILABLE",
        return_pct=value,
        quote_key=artifact,
    )


def validate_path_point_v58(
    point: MarketFirstExitPathPointV58,
    *,
    decision_as_of: int,
) -> None:
    if not point.observation_key.strip():
        raise ValueError("observation_key cannot be empty")
    if point.status not in PATH_POINT_STATUSES:
        raise ValueError("unsupported path point status")
    if int(point.observed_at) <= int(decision_as_of):
        raise ValueError("path point must be observed strictly after decision_as_of")

    if point.status == "AVAILABLE":
        if point.return_pct is None or not math.isfinite(float(point.return_pct)):
            raise ValueError("AVAILABLE path point requires finite return_pct")
        if point.quote_key is None or not str(point.quote_key).strip():
            raise ValueError("AVAILABLE path point requires quote_key")
        if point.error_type is not None:
            raise ValueError("AVAILABLE path point cannot carry error_type")
    else:
        if point.return_pct is not None:
            raise ValueError("missing route point cannot synthesize return_pct")
        if point.quote_key is not None:
            raise ValueError("missing route point cannot reference a quote artifact")


def build_market_first_exit_geometry_v58(
    *,
    decision_as_of: int,
    points: tuple[MarketFirstExitPathPointV58, ...] | list[MarketFirstExitPathPointV58],
) -> MarketFirstExitGeometryV58:
    """Summarize route-path geometry without choosing or simulating an exit policy.

    The entry reference is return 0 at ``decision_as_of``. Therefore MFE cannot
    be below zero and MAE cannot be above zero. Missing observations remain in
    the denominator for coverage, and no price/return interpolation is performed.
    """

    cutoff = int(decision_as_of)
    if cutoff < 0:
        raise ValueError("decision_as_of must be non-negative")

    ordered = sorted(tuple(points), key=lambda item: (int(item.observed_at), item.observation_key))
    keys: set[str] = set()
    clocks: set[int] = set()
    for point in ordered:
        validate_path_point_v58(point, decision_as_of=cutoff)
        if point.observation_key in keys:
            raise ValueError("duplicate observation_key")
        if int(point.observed_at) in clocks:
            raise ValueError("duplicate observed_at is ambiguous at second resolution")
        keys.add(point.observation_key)
        clocks.add(int(point.observed_at))

    scheduled = len(ordered)
    available = [item for item in ordered if item.status == "AVAILABLE"]
    available_count = len(available)
    missing_count = scheduled - available_count
    coverage = 100.0 * available_count / scheduled if scheduled else 0.0

    if not scheduled:
        return MarketFirstExitGeometryV58(
            method_version=MARKET_FIRST_EXIT_GEOMETRY_VERSION,
            decision_as_of=cutoff,
            scheduled_points=0,
            available_points=0,
            unavailable_or_error_points=0,
            coverage_pct=0.0,
            first_available_offset_seconds=None,
            last_available_offset_seconds=None,
            mfe_pct=None,
            mae_pct=None,
            time_to_mfe_seconds=None,
            time_to_mae_seconds=None,
            last_observed_return_pct=None,
            peak_to_last_giveback_pct_points=None,
            last_observed_mfe_capture_pct=None,
            max_available_gap_seconds=None,
            classification="NO_PATH_OBSERVATIONS",
        )

    if not available:
        return MarketFirstExitGeometryV58(
            method_version=MARKET_FIRST_EXIT_GEOMETRY_VERSION,
            decision_as_of=cutoff,
            scheduled_points=scheduled,
            available_points=0,
            unavailable_or_error_points=missing_count,
            coverage_pct=coverage,
            first_available_offset_seconds=None,
            last_available_offset_seconds=None,
            mfe_pct=None,
            mae_pct=None,
            time_to_mfe_seconds=None,
            time_to_mae_seconds=None,
            last_observed_return_pct=None,
            peak_to_last_giveback_pct_points=None,
            last_observed_mfe_capture_pct=None,
            max_available_gap_seconds=None,
            classification="NO_AVAILABLE_ROUTE_PATH",
        )

    values = [(int(item.observed_at), float(item.return_pct)) for item in available]
    mfe = max(0.0, max(value for _clock, value in values))
    mae = min(0.0, min(value for _clock, value in values))

    if mfe == 0.0:
        time_to_mfe = 0
    else:
        mfe_clock = min(clock for clock, value in values if value == mfe)
        time_to_mfe = mfe_clock - cutoff

    if mae == 0.0:
        time_to_mae = 0
    else:
        mae_clock = min(clock for clock, value in values if value == mae)
        time_to_mae = mae_clock - cutoff

    last_clock, last_return = values[-1]
    giveback = mfe - last_return
    capture = 100.0 * last_return / mfe if mfe > 0 else None
    gaps = [
        values[index][0] - values[index - 1][0]
        for index in range(1, len(values))
    ]

    return MarketFirstExitGeometryV58(
        method_version=MARKET_FIRST_EXIT_GEOMETRY_VERSION,
        decision_as_of=cutoff,
        scheduled_points=scheduled,
        available_points=available_count,
        unavailable_or_error_points=missing_count,
        coverage_pct=coverage,
        first_available_offset_seconds=values[0][0] - cutoff,
        last_available_offset_seconds=last_clock - cutoff,
        mfe_pct=mfe,
        mae_pct=mae,
        time_to_mfe_seconds=time_to_mfe,
        time_to_mae_seconds=time_to_mae,
        last_observed_return_pct=last_return,
        peak_to_last_giveback_pct_points=giveback,
        last_observed_mfe_capture_pct=capture,
        max_available_gap_seconds=max(gaps) if gaps else None,
        classification=(
            "COMPLETE_ROUTE_PATH" if missing_count == 0 else "PARTIAL_ROUTE_PATH"
        ),
    )
