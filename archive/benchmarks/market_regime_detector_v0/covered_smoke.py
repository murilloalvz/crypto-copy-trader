"""Deterministic smoke checks for the coverage-aware Page-Hinkley boundary."""

from benchmarks.market_regime_detector_v0.causal_intensity import (
    CAUSAL_INTENSITY_VERSION,
    CausalIntensitySeriesV0,
    IntensityBinV0,
)
from benchmarks.market_regime_detector_v0.covered_page_hinkley import (
    run_covered_page_hinkley_v0,
)


def _bin(index: int, count: int | None) -> IntensityBinV0:
    observed = count is not None
    return IntensityBinV0(
        token_mint="MINT_A",
        bin_start_chain_time=index,
        bin_end_chain_time=index + 1,
        as_of=500,
        status="OBSERVED" if observed else "MISSING",
        event_count=count,
        buy_count=count if observed else None,
        sell_count=0 if observed else None,
        coverage_sources=("synthetic",) if observed else (),
        coverage_evidence_keys=("coverage",) if observed else (),
        event_transaction_keys=(),
        data_quality_flags=() if observed else ("collector_coverage_unknown",),
    )


def _series(values: list[int | None]) -> CausalIntensitySeriesV0:
    bins = tuple(_bin(index, value) for index, value in enumerate(values))
    observed = sum(value is not None for value in values)
    missing = len(values) - observed
    return CausalIntensitySeriesV0(
        method_version=CAUSAL_INTENSITY_VERSION,
        token_mint="MINT_A",
        as_of=500,
        bin_seconds=1,
        bins=bins,
        observed_bin_count=observed,
        missing_bin_count=missing,
        observed_coverage_pct=100.0 * observed / len(values),
    )


def main() -> int:
    low = [2, 2, 3, 1] * 45
    high = [8, 8, 9, 7] * 60

    continuous = run_covered_page_hinkley_v0(_series(low + high))
    assert continuous.missing_bins_skipped == 0
    assert continuous.detector_resets_due_to_missing == 0
    assert continuous.contiguous_segments == 1
    assert continuous.detections
    assert continuous.detections[0].detected_bin_start_chain_time == 188

    # A collector gap at the regime boundary must reset the detector.  The high segment
    # then starts from clean state, so there is no synthetic drift carried across the gap.
    separated = run_covered_page_hinkley_v0(_series(low + [None] + high))
    assert separated.missing_bins_skipped == 1
    assert separated.detector_resets_due_to_missing == 1
    assert separated.contiguous_segments == 2
    assert separated.detections == ()
    assert "collector_coverage_gaps_present" in separated.data_quality_flags

    print("PASS_COVERED_PAGE_HINKLEY_V0")
    print(f"continuous_first_detection={continuous.detections[0].detected_bin_start_chain_time}")
    print(f"gap_resets={separated.detector_resets_due_to_missing}")
    print(f"gap_detections={len(separated.detections)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
