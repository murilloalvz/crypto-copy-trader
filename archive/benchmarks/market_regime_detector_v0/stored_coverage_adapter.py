"""Adapter from persisted collector coverage to the research intensity boundary."""

from benchmarks.market_regime_detector_v0.causal_intensity import MarketCoverageInterval
from src.market_collection_coverage_store import StoredMarketCoverageInterval


def to_market_coverage_intervals_v0(
    rows: tuple[StoredMarketCoverageInterval, ...] | list[StoredMarketCoverageInterval],
) -> tuple[MarketCoverageInterval, ...]:
    intervals: list[MarketCoverageInterval] = []
    for row in rows:
        if row.coverage_kind != "continuous_observed":
            raise ValueError(f"unsupported persisted coverage_kind: {row.coverage_kind}")
        intervals.append(
            MarketCoverageInterval(
                start_chain_time=row.start_chain_time,
                end_chain_time=row.end_chain_time,
                available_at=row.available_at,
                source=f"{row.source_provider}:{row.source_scope}",
                token_mint=row.token_mint,
                evidence_key=row.evidence_key,
            )
        )
    return tuple(intervals)
