from dataclasses import dataclass


@dataclass(frozen=True)
class SocialEvent:
    source: str
    event_id: str
    author_id: str
    created_at: int
    observed_at: int
    token_mint: str | None = None
    symbol: str | None = None
    event_type: str = "mention"
    is_original: bool = True
    like_count: int = 0
    repost_count: int = 0
    reply_count: int = 0
    quote_count: int = 0


@dataclass(frozen=True)
class SocialWindowStats:
    window_seconds: int
    event_count: int
    unique_author_count: int
    original_post_count: int
    repost_or_quote_count: int
    like_count: int
    repost_count: int
    reply_count: int
    quote_count: int


@dataclass(frozen=True)
class SocialContext:
    token_mint: str | None
    symbol: str | None
    as_of: int
    windows: dict[int, SocialWindowStats]


def _validate_event(event: SocialEvent) -> None:
    if not event.source.strip():
        raise ValueError("social event source cannot be empty")
    if not event.event_id.strip():
        raise ValueError("social event id cannot be empty")
    if event.created_at < 0 or event.observed_at < 0:
        raise ValueError("social event timestamps must be non-negative")
    if event.observed_at < event.created_at:
        raise ValueError("observed_at cannot be earlier than created_at")
    for value in (
        event.like_count,
        event.repost_count,
        event.reply_count,
        event.quote_count,
    ):
        if value < 0:
            raise ValueError("engagement counters cannot be negative")


def _matches_token(
    event: SocialEvent,
    *,
    token_mint: str | None,
    symbol: str | None,
) -> bool:
    if token_mint is not None:
        return event.token_mint == token_mint
    if symbol is not None:
        return (event.symbol or "").upper() == symbol.upper()
    return False


def causal_event_snapshots(
    events: list[SocialEvent] | tuple[SocialEvent, ...],
    *,
    as_of: int,
    token_mint: str | None = None,
    symbol: str | None = None,
) -> list[SocialEvent]:
    """Return the latest observable snapshot per post at ``as_of``.

    The key anti-lookahead rule is based on ``observed_at`` rather than ``created_at``.
    A post that existed earlier but was only discovered later is unavailable to a historical
    decision before the collector actually observed it. Repeated snapshots of the same post
    are useful for engagement growth; only the latest snapshot already observed at ``as_of``
    is eligible.
    """
    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    if token_mint is None and symbol is None:
        raise ValueError("token_mint or symbol is required")

    selected: dict[tuple[str, str], SocialEvent] = {}
    for event in events:
        _validate_event(event)
        if event.observed_at > as_of:
            continue
        if not _matches_token(event, token_mint=token_mint, symbol=symbol):
            continue
        key = (event.source, event.event_id)
        previous = selected.get(key)
        if previous is None or event.observed_at > previous.observed_at:
            selected[key] = event

    return sorted(
        selected.values(),
        key=lambda item: (item.observed_at, item.source, item.event_id),
    )


def build_social_context(
    events: list[SocialEvent] | tuple[SocialEvent, ...],
    *,
    as_of: int,
    token_mint: str | None = None,
    symbol: str | None = None,
    windows: tuple[int, ...] = (300, 900, 3_600),
) -> SocialContext:
    if not windows or any(window <= 0 for window in windows):
        raise ValueError("social windows must be positive")

    snapshots = causal_event_snapshots(
        events,
        as_of=as_of,
        token_mint=token_mint,
        symbol=symbol,
    )
    stats: dict[int, SocialWindowStats] = {}

    for window in sorted(set(windows)):
        lower_bound = as_of - window
        rows = [
            event
            for event in snapshots
            if lower_bound < event.observed_at <= as_of
        ]
        stats[window] = SocialWindowStats(
            window_seconds=window,
            event_count=len(rows),
            unique_author_count=len({event.author_id for event in rows}),
            original_post_count=sum(event.is_original for event in rows),
            repost_or_quote_count=sum(
                (not event.is_original) or event.event_type in {"repost", "quote"}
                for event in rows
            ),
            like_count=sum(event.like_count for event in rows),
            repost_count=sum(event.repost_count for event in rows),
            reply_count=sum(event.reply_count for event in rows),
            quote_count=sum(event.quote_count for event in rows),
        )

    return SocialContext(
        token_mint=token_mint,
        symbol=symbol,
        as_of=as_of,
        windows=stats,
    )
