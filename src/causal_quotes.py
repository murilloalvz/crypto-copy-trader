from dataclasses import dataclass


@dataclass(frozen=True)
class CausalQuoteObservation:
    """One market quote with both market time and real observation time.

    ``market_time`` describes when the quoted market state applies. ``observed_at`` is when
    our system actually had the quote available. Keeping both timestamps prevents a replay
    from treating historical data as if it had been known earlier.
    """

    token_mint: str
    market_time: int
    observed_at: int
    price_usd: float
    source: str
    executable: bool
    resolution_seconds: int = 1
    liquidity_usd: float | None = None


@dataclass(frozen=True)
class CausalQuoteSelection:
    quote: CausalQuoteObservation | None
    reason: str | None


def validate_causal_quote(quote: CausalQuoteObservation) -> None:
    if not quote.token_mint.strip():
        raise ValueError("quote token_mint cannot be empty")
    if not quote.source.strip():
        raise ValueError("quote source cannot be empty")
    if quote.market_time < 0 or quote.observed_at < 0:
        raise ValueError("quote timestamps must be non-negative")
    if quote.observed_at < quote.market_time:
        raise ValueError("quote observed_at cannot be earlier than market_time")
    if quote.price_usd <= 0:
        raise ValueError("quote price_usd must be positive")
    if quote.resolution_seconds < 1:
        raise ValueError("quote resolution_seconds must be >= 1")
    if quote.liquidity_usd is not None and quote.liquidity_usd < 0:
        raise ValueError("quote liquidity_usd cannot be negative")


def select_first_causal_quote(
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *,
    token_mint: str,
    ready_at: int,
    max_quote_age_seconds: int,
    max_quote_wait_seconds: int,
    require_executable: bool = True,
) -> CausalQuoteSelection:
    """Select the first quote that could really have been used after ``ready_at``.

    This intentionally selects by ``observed_at``, never by market timestamp alone. A quote
    only becomes eligible after our system observed it. Quotes that are too stale, arrive too
    late or are proxy/non-executable are not silently upgraded into executable evidence.
    """

    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if ready_at < 0:
        raise ValueError("ready_at must be non-negative")
    if max_quote_age_seconds < 0:
        raise ValueError("max_quote_age_seconds must be non-negative")
    if max_quote_wait_seconds < 0:
        raise ValueError("max_quote_wait_seconds must be non-negative")

    token_quotes: list[CausalQuoteObservation] = []
    for quote in quotes:
        validate_causal_quote(quote)
        if quote.token_mint == token_mint:
            token_quotes.append(quote)

    if not token_quotes:
        return CausalQuoteSelection(None, "no_quotes_for_token")

    saw_after_ready = False
    saw_in_window = False
    saw_executable = False
    saw_fresh = False
    deadline = ready_at + max_quote_wait_seconds

    for quote in sorted(token_quotes, key=lambda item: (item.observed_at, item.market_time)):
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
