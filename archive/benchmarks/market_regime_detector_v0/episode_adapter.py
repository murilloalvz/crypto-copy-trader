"""Adapter from coverage-aware Page-Hinkley research output to episode facts."""

from src.market_episode_research_snapshot import MarketRegimeResearchFactsV0

from benchmarks.market_regime_detector_v0.covered_page_hinkley import (
    CoveredPageHinkleyResultV0,
)


def to_market_regime_research_facts_v0(
    result: CoveredPageHinkleyResultV0,
) -> MarketRegimeResearchFactsV0:
    latest = (
        result.detections[-1].detected_bin_start_chain_time
        if result.detections
        else None
    )
    return MarketRegimeResearchFactsV0(
        method_version=result.method_version,
        detector="river.PageHinkley",
        metric=result.metric,
        detection_count=len(result.detections),
        latest_detection_chain_time=latest,
        observed_bins_consumed=result.observed_bins_consumed,
        missing_bins_skipped=result.missing_bins_skipped,
        detector_resets_due_to_missing=result.detector_resets_due_to_missing,
        contiguous_segments=result.contiguous_segments,
        data_quality_flags=result.data_quality_flags,
    )
