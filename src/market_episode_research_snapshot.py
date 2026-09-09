"""Immutable causal MarketEpisode research snapshot.

This module creates the unit that future outcome research can join against without
reconstructing features after the fact.  It composes only evidence available at the
frozen episode `decision_as_of` and keeps Market-First evidence independent from any
Social/Event-First track.

No outcome, opportunity score, recommendation, confidence, or TAKE/SKIP label belongs
in this object.
"""

from dataclasses import dataclass

from src.market_intelligence_baseline import MarketIntelligenceBaselineV0
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.pump_creation_mode_facts import PumpCreationModeFactsV0


MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION = "market_episode_research_snapshot_v0"


@dataclass(frozen=True)
class MarketRegimeResearchFactsV0:
    """Detector-agnostic descriptive regime evidence frozen at T0."""

    method_version: str
    detector: str
    metric: str
    detection_count: int
    latest_detection_chain_time: int | None
    observed_bins_consumed: int
    missing_bins_skipped: int
    detector_resets_due_to_missing: int
    contiguous_segments: int
    data_quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.method_version.strip() or not self.detector.strip() or not self.metric.strip():
            raise ValueError("regime method_version, detector and metric cannot be empty")
        if self.detection_count < 0:
            raise ValueError("detection_count must be non-negative")
        if self.latest_detection_chain_time is not None and self.latest_detection_chain_time < 0:
            raise ValueError("latest_detection_chain_time must be non-negative")
        for value in (
            self.observed_bins_consumed,
            self.missing_bins_skipped,
            self.detector_resets_due_to_missing,
            self.contiguous_segments,
        ):
            if value < 0:
                raise ValueError("regime counters must be non-negative")
        if self.detection_count == 0 and self.latest_detection_chain_time is not None:
            raise ValueError("latest detection cannot exist when detection_count is zero")
        if self.detection_count > 0 and self.latest_detection_chain_time is None:
            raise ValueError("latest detection is required when detections exist")


@dataclass(frozen=True)
class MarketEpisodeResearchSnapshotV0:
    method_version: str
    episode_key: str
    acquisition_run_key: str
    token_mint: str
    decision_as_of: int
    first_trigger_key: str
    first_trigger_kind: str
    first_trigger_direction: str
    first_trigger_chain_time: int
    first_trigger_observed_at: int
    market_intelligence: MarketIntelligenceBaselineV0
    pump_creation_mode: PumpCreationModeFactsV0
    regime: MarketRegimeResearchFactsV0 | None
    data_quality_flags: tuple[str, ...]


def build_market_episode_research_snapshot_v0(
    *,
    episode: MarketOpportunityEpisode,
    market_intelligence: MarketIntelligenceBaselineV0,
    pump_creation_mode: PumpCreationModeFactsV0,
    regime: MarketRegimeResearchFactsV0 | None = None,
) -> MarketEpisodeResearchSnapshotV0:
    """Freeze a causal Market-First episode snapshot at the persisted decision T0."""

    if episode.decision_as_of is None:
        raise ValueError("market episode decision_as_of must be frozen before research snapshot")
    decision_as_of = int(episode.decision_as_of)

    if market_intelligence.token_mint != episode.token_mint:
        raise ValueError("market intelligence token_mint must match episode")
    if pump_creation_mode.token_mint != episode.token_mint:
        raise ValueError("pump creation mode token_mint must match episode")
    if market_intelligence.as_of != decision_as_of:
        raise ValueError("market intelligence as_of must equal frozen decision_as_of")
    if pump_creation_mode.as_of != decision_as_of:
        raise ValueError("pump creation mode as_of must equal frozen decision_as_of")
    if decision_as_of < episode.first_trigger_observed_at:
        raise ValueError("decision_as_of cannot precede first trigger observation")
    if regime is not None and regime.latest_detection_chain_time is not None:
        if regime.latest_detection_chain_time > decision_as_of:
            raise ValueError("regime evidence cannot contain post-decision detection")

    quality = set(market_intelligence.data_quality_flags)
    quality.update(pump_creation_mode.data_quality_flags)
    if regime is None:
        quality.add("regime_evidence_not_available")
    else:
        quality.update(regime.data_quality_flags)

    return MarketEpisodeResearchSnapshotV0(
        method_version=MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION,
        episode_key=episode.episode_key,
        acquisition_run_key=episode.acquisition_run_key,
        token_mint=episode.token_mint,
        decision_as_of=decision_as_of,
        first_trigger_key=episode.first_trigger_key,
        first_trigger_kind=episode.first_trigger_kind,
        first_trigger_direction=episode.first_trigger_direction,
        first_trigger_chain_time=episode.first_trigger_chain_time,
        first_trigger_observed_at=episode.first_trigger_observed_at,
        market_intelligence=market_intelligence,
        pump_creation_mode=pump_creation_mode,
        regime=regime,
        data_quality_flags=tuple(sorted(quality)),
    )
