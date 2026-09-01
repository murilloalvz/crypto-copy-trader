import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CausalQuoteObservation:
    """One normalized market quote with real availability time.

    ``token_mint`` is the researched asset. ``side`` is from our perspective: a buy quote
    acquires the researched token and a sell quote disposes of it. Executable quotes must
    retain route direction so a sell route can never satisfy a buy replay (or vice versa).

    Provider metadata is optional and observational. For Jupiter, price impact/slippage/router
    help characterize whether the route itself degrades as copy latency grows. They are not a
    substitute for landing/fill telemetry.
    """

    token_mint: str
    side: str
    market_time: int
    observed_at: int
    price_usd: float
    source: str
    executable: bool
    resolution_seconds: int = 1
    liquidity_usd: float | None = None
    input_mint: str | None = None
    output_mint: str | None = None
    input_amount_raw: str | None = None
    output_amount_raw: str | None = None
    route_id: str | None = None
    provider_router: str | None = None
    provider_slippage_bps: int | None = None
    provider_price_impact_pct_points: float | None = None
    provider_swap_usd_value: float | None = None


@dataclass(frozen=True)
class CausalQuoteSelection:
    quote: CausalQuoteObservation | None
    reason: str | None


def validate_causal_quote(quote: CausalQuoteObservation) -> None:
    if not quote.token_mint.strip():
        raise ValueError("quote token_mint cannot be empty")
    if quote.side not in {"buy", "sell"}:
        raise ValueError("quote side must be buy or sell")
    if not quote.source.strip():
        raise ValueError("quote source cannot be empty")
    if quote.market_time < 0 or quote.observed_at < 0:
        raise ValueError("quote timestamps must be non-negative")
    if quote.observed_at < quote.market_time:
        raise ValueError("quote observed_at cannot be earlier than market_time")
    if quote.price_usd <= 0 or not math.isfinite(quote.price_usd):
        raise ValueError("quote price_usd must be positive and finite")
    if quote.resolution_seconds < 1:
        raise ValueError("quote resolution_seconds must be >= 1")
    if quote.liquidity_usd is not None and (
        quote.liquidity_usd < 0 or not math.isfinite(quote.liquidity_usd)
    ):
        raise ValueError("quote liquidity_usd must be non-negative and finite")
    if quote.provider_router is not None and not quote.provider_router.strip():
        raise ValueError("provider_router cannot be blank")
    if quote.provider_slippage_bps is not None and not 0 <= quote.provider_slippage_bps <= 10_000:
        raise ValueError("provider_slippage_bps must be between 0 and 10000")
    if quote.provider_price_impact_pct_points is not None and not math.isfinite(
        quote.provider_price_impact_pct_points
    ):
        raise ValueError("provider_price_impact_pct_points must be finite")
    if quote.provider_swap_usd_value is not None and (
        quote.provider_swap_usd_value <= 0
        or not math.isfinite(quote.provider_swap_usd_value)
    ):
        raise ValueError("provider_swap_usd_value must be positive and finite")

    if quote.executable:
        if not quote.input_mint or not quote.input_mint.strip():
            raise ValueError("executable quote requires input_mint")
        if not quote.output_mint or not quote.output_mint.strip():
            raise ValueError("executable quote requires output_mint")
        if quote.side == "buy" and quote.output_mint != quote.token_mint:
            raise ValueError("buy quote must output the researched token")
        if quote.side == "sell" and quote.input_mint != quote.token_mint:
            raise ValueError("sell quote must input the researched token")


def select_first_causal_quote(
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *,
    token_mint: str,
    side: str,
    ready_at: int,
    max_quote_age_seconds: int,
    max_quote_wait_seconds: int,
    require_executable: bool = True,
) -> CausalQuoteSelection:
    """Select the first quote that could really have been used after ``ready_at``."""

    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if ready_at < 0:
        raise ValueError("ready_at must be non-negative")
    if max_quote_age_seconds < 0:
        raise ValueError("max_quote_age_seconds must be non-negative")
    if max_quote_wait_seconds < 0:
        raise ValueError("max_quote_wait_seconds must be non-negative")

    matching_quotes: list[CausalQuoteObservation] = []
    token_quotes_seen = False
    for quote in quotes:
        validate_causal_quote(quote)
        if quote.token_mint != token_mint:
            continue
        token_quotes_seen = True
        if quote.side == side:
            matching_quotes.append(quote)

    if not token_quotes_seen:
        return CausalQuoteSelection(None, "no_quotes_for_token")
    if not matching_quotes:
        return CausalQuoteSelection(None, "no_quote_for_side")

    saw_after_ready = False
    saw_in_window = False
    saw_executable = False
    saw_fresh = False
    deadline = ready_at + max_quote_wait_seconds

    for quote in sorted(matching_quotes, key=lambda item: (item.observed_at, item.market_time)):
        if quote.observed_at < ready_at:
            continue
        saw_after_ready = True
        if quote.observed_at > deadline:
            break
        saw_in_window = True
        if require_executable and not quote.executable:
            continue
        saw_executable = True
        quote_age = quote.observed_at - quote.market_time
        if quote_age > max_quote_age_seconds:
            continue
        saw_fresh = True
        return CausalQuoteSelection(quote, None)

    if not saw_after_ready:
        return CausalQuoteSelection(None, "no_quote_after_decision")
    if not saw_in_window:
        return CausalQuoteSelection(None, "no_quote_within_wait_window")
    if require_executable and not saw_executable:
        return CausalQuoteSelection(None, "no_executable_quote_in_window")
    if not saw_fresh:
        return CausalQuoteSelection(None, "no_fresh_quote_in_window")
    return CausalQuoteSelection(None, "no_eligible_quote")
