from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.social_features import SocialBurstFeatures, build_social_burst_features
from src.social_intelligence import SocialEvent, causal_event_snapshots


OPPORTUNITY_SOCIAL_EVIDENCE_VERSION = "opportunity_social_evidence_v57_market_first"
V57_CURRENT_WINDOW_SECONDS = 300
V57_BASELINE_WINDOW_SECONDS = 3_600


@dataclass(frozen=True)
class OpportunitySocialEvidenceV57:
    """Causal social evidence for an already-identified market opportunity.

    This envelope is descriptive only. It never opens an episode, selects a token, assigns a
    trading score, or upgrades missing social data into a positive/negative signal.
    """

    method_version: str
    token_mint: str
    as_of: int
    status: str  # AVAILABLE | NO_CAUSAL_EVENTS
    causal_post_count: int
    latest_snapshot_count: int
    current_event_count: int
    current_unique_author_count: int
    prior_baseline_event_count: int
    event_rate_acceleration_ratio: float | None
    current_author_diversity_pct: float | None
    current_original_share_pct: float | None
    current_total_engagement: int | None
    current_engagement_per_event: float | None
    data_quality_flags: tuple[str, ...]


def _validate_identity(*, token_mint: str, as_of: int) -> str:
    mint = str(token_mint).strip()
    if not mint:
        raise ValueError("token_mint cannot be empty")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    return mint


def build_opportunity_social_evidence_v57(
    *,
    events: Iterable[SocialEvent],
    token_mint: str,
    as_of: int,
) -> OpportunitySocialEvidenceV57:
    """Build token-mint anchored social evidence known by ``as_of``.

    Token mint is required deliberately: symbol-only joins are not allowed here because ticker
    collisions/renames could attach unrelated posts to a market episode. The inherited social core
    uses first ``observed_at`` for window membership and the latest snapshot already known at
    ``as_of`` for engagement counters.
    """

    mint = _validate_identity(token_mint=token_mint, as_of=as_of)
    rows = tuple(events)
    causal = causal_event_snapshots(
        rows,
        as_of=as_of,
        token_mint=mint,
    )
    if not causal:
        return OpportunitySocialEvidenceV57(
            method_version=OPPORTUNITY_SOCIAL_EVIDENCE_VERSION,
            token_mint=mint,
            as_of=as_of,
            status="NO_CAUSAL_EVENTS",
            causal_post_count=0,
            latest_snapshot_count=0,
            current_event_count=0,
            current_unique_author_count=0,
            prior_baseline_event_count=0,
            event_rate_acceleration_ratio=None,
            current_author_diversity_pct=None,
            current_original_share_pct=None,
            current_total_engagement=None,
            current_engagement_per_event=None,
            data_quality_flags=("no_social_events_observed_as_of",),
        )

    features: SocialBurstFeatures = build_social_burst_features(
        rows,
        as_of=as_of,
        token_mint=mint,
        current_window_seconds=V57_CURRENT_WINDOW_SECONDS,
        baseline_window_seconds=V57_BASELINE_WINDOW_SECONDS,
    )
    flags: list[str] = []
    if features.current_event_count == 0:
        flags.append("no_posts_first_observed_in_current_window")
    if features.prior_baseline_event_count == 0:
        flags.append("zero_prior_baseline_event_count")
    if features.event_rate_acceleration_ratio is None:
        flags.append("social_acceleration_ratio_unavailable")

    return OpportunitySocialEvidenceV57(
        method_version=OPPORTUNITY_SOCIAL_EVIDENCE_VERSION,
        token_mint=mint,
        as_of=as_of,
        status="AVAILABLE",
        causal_post_count=len(causal),
        latest_snapshot_count=len(causal),
        current_event_count=features.current_event_count,
        current_unique_author_count=features.current_unique_author_count,
        prior_baseline_event_count=features.prior_baseline_event_count,
        event_rate_acceleration_ratio=features.event_rate_acceleration_ratio,
        current_author_diversity_pct=features.current_author_diversity_pct,
        current_original_share_pct=features.current_original_share_pct,
        current_total_engagement=features.current_total_engagement,
        current_engagement_per_event=features.current_engagement_per_event,
        data_quality_flags=tuple(flags),
    )
