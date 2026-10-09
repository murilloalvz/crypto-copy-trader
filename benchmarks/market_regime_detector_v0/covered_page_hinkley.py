"""Coverage-aware Page-Hinkley research runner.

River's maintained Page-Hinkley detector is applied only to contiguous OBSERVED bins.
Any MISSING bin resets detector state.  This prevents an unobserved collector gap from
being silently treated as zero activity or from connecting two unrelated regimes.

Defaults remain untuned.  Output is descriptive research evidence, not a trading signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from river import drift

from benchmarks.market_regime_detector_v0.causal_intensity import CausalIntensitySeriesV0


COVERED_PAGE_HINKLEY_VERSION = "covered_page_hinkley_v0"


@dataclass(frozen=True)
class RegimeChangeEventV0:
    token_mint: str
    detected_bin_start_chain_time: int
    detected_bin_end_chain_time: int
    observed_points_in_segment: int
    segment_start_chain_time: int
    metric: str
    detector: str
    detector_configuration: str


@dataclass(frozen=True)
class CoveredPageHinkleyResultV0:
    method_version: str
    token_mint: str
    as_of: int
    metric: str
    observed_bins_consumed: int
    missing_bins_skipped: int
    detector_resets_due_to_missing: int
    contiguous_segments: int
    detections: tuple[RegimeChangeEventV0, ...]
    data_quality_flags: tuple[str, ...]


def run_covered_page_hinkley_v0(
    series: CausalIntensitySeriesV0,
    *,
    metric: str = "event_count",
) -> CoveredPageHinkleyResultV0:
    """Run untuned River Page-Hinkley over contiguous covered intensity bins."""

    if metric not in {"event_count", "buy_count", "sell_count"}:
        raise ValueError("metric must be event_count, buy_count, or sell_count")

    detector = None
    segment_start = None
    segment_points = 0
    segments = 0
    resets = 0
    consumed = 0
    missing = 0
    detections: list[RegimeChangeEventV0] = []

    for row in series.bins:
        if row.status == "MISSING":
            missing += 1
            if detector is not None:
                detector = None
                segment_start = None
                segment_points = 0
                resets += 1
            continue

        if row.status != "OBSERVED":
            raise ValueError(f"unsupported intensity bin status: {row.status}")

        value = getattr(row, metric)
        if value is None:
            raise ValueError(f"OBSERVED bin cannot have missing {metric}")

        if detector is None:
            detector = drift.PageHinkley(mode="both")
            segment_start = row.bin_start_chain_time
            segment_points = 0
            segments += 1

        segment_points += 1
        consumed += 1
        detector.update(float(value))
        if detector.drift_detected:
            detections.append(
                RegimeChangeEventV0(
                    token_mint=series.token_mint,
                    detected_bin_start_chain_time=row.bin_start_chain_time,
                    detected_bin_end_chain_time=row.bin_end_chain_time,
                    observed_points_in_segment=segment_points,
                    segment_start_chain_time=int(segment_start),
                    metric=metric,
                    detector="river.PageHinkley",
                    detector_configuration="River 0.26.x defaults; mode=both; no tuning",
                )
            )

    flags: list[str] = []
    if missing:
        flags.append("collector_coverage_gaps_present")
    if consumed == 0:
        flags.append("no_observed_bins_for_regime_detection")

    return CoveredPageHinkleyResultV0(
        method_version=COVERED_PAGE_HINKLEY_VERSION,
        token_mint=series.token_mint,
        as_of=series.as_of,
        metric=metric,
        observed_bins_consumed=consumed,
        missing_bins_skipped=missing,
        detector_resets_due_to_missing=resets,
        contiguous_segments=segments,
        detections=tuple(detections),
        data_quality_flags=tuple(flags),
    )
