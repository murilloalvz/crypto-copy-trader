from dataclasses import dataclass

from src.social_intelligence import SocialEvent, build_social_context


@dataclass(frozen=True)
class SocialBurstFeatures:
    token_mint: str | None
    symbol: str | None
    as_of: int
    current_window_seconds: int
    baseline_window_seconds: int
    current_event_count: int
    current_unique_author_count: int
    prior_baseline_event_count: int
    current_event_rate_per_minute: float
    prior_baseline_event_rate_per_minute: float
    event_rate_acceleration_ratio: float | None
    current_author_diversity_pct: float
    current_original_share_pct: float
    current_total_engagement: int
    current_engagement_per_event: float | None


def build_social_burst_features(
    events: list[SocialEvent] | tuple[SocialEvent, ...],
    *,
    as_of: int,
    token_mint: str | None = None,
    symbol: str | None = None,
    current_window_seconds: int = 300,
    baseline_window_seconds: int = 3_600,
) -> SocialBurstFeatures:
    """Measure social acceleration without deciding whether it is a trading signal.

    The current window is compared with the non-overlapping portion of the larger baseline
    window. Window membership comes from ``build_social_context`` and therefore uses the
    collector's first observation time rather than post creation time or a later engagement
    refresh. No threshold here labels a token as bullish, viral or tradeable.
    """
    if current_window_seconds <= 0:
        raise ValueError("current_window_seconds must be positive")
    if baseline_window_seconds <= current_window_seconds:
        raise ValueError("baseline_window_seconds must exceed current_window_seconds")

    context = build_social_context(
        events,
        as_of=as_of,
        token_mint=token_mint,
        symbol=symbol,
        windows=(current_window_seconds, baseline_window_seconds),
    )
    current = context.windows[current_window_seconds]
    baseline = context.windows[baseline_window_seconds]

    prior_count = max(0, baseline.event_count - current.event_count)
    current_minutes = current_window_seconds / 60.0
    prior_minutes = (baseline_window_seconds - current_window_seconds) / 60.0
    current_rate = current.event_count / current_minutes
    prior_rate = prior_count / prior_minutes
    acceleration = current_rate / prior_rate if prior_rate > 0 else None

    diversity = (
        100.0 * current.unique_author_count / current.event_count
        if current.event_count
        else 0.0
    )
    original_share = (
        100.0 * current.original_post_count / current.event_count
        if current.event_count
        else 0.0
    )
    engagement = (
        current.like_count
        + current.repost_count
        + current.reply_count
        + current.quote_count
    )
    engagement_per_event = engagement / current.event_count if current.event_count else None

    return SocialBurstFeatures(
        token_mint=token_mint,
        symbol=symbol,
        as_of=as_of,
        current_window_seconds=current_window_seconds,
        baseline_window_seconds=baseline_window_seconds,
        current_event_count=current.event_count,
        current_unique_author_count=current.unique_author_count,
        prior_baseline_event_count=prior_count,
        current_event_rate_per_minute=current_rate,
        prior_baseline_event_rate_per_minute=prior_rate,
        event_rate_acceleration_ratio=acceleration,
        current_author_diversity_pct=diversity,
        current_original_share_pct=original_share,
        current_total_engagement=engagement,
        current_engagement_per_event=engagement_per_event,
    )
