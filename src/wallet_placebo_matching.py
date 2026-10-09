import math
from dataclasses import dataclass

from src.wallet_strategy_compare import (
    compare_wallet_strategy_fingerprints,
    fingerprint_evidence_ready,
)
from src.wallet_strategy_lab import WalletStrategyFingerprint


@dataclass(frozen=True)
class PlaceboMatchDiagnostic:
    """Pre-period similarity diagnostics for constructing wallet placebo cohorts.

    This object intentionally has no profitability/outcome fields and no weighted matching
    score. It exists to make the covariate differences visible before a prospective study is
    started, not to identify the "best" wallet.
    """

    target_address: str
    candidate_address: str
    comparable_dimensions: int
    matching_dimensions: int
    bucket_similarity_pct: float | None
    active_day_rate_ratio: float | None
    token_breadth_ratio: float | None
    observed_span_ratio: float | None
    first_exit_ratio: float | None
    roundtrip_abs_diff_pct: float
    scale_in_abs_diff_pct: float
    multi_sell_abs_diff_pct: float
    reentry_abs_diff_pct: float
    dominant_dex_match: bool | None
    dominant_dex_share_abs_diff_pct: float | None
    target_evidence_ready: bool
    candidate_evidence_ready: bool
    warnings: tuple[str, ...]

    @property
    def comparison_coverage_grade(self) -> str:
        if self.comparable_dimensions >= 4:
            return "FULL_BUCKET_COVERAGE"
        if self.comparable_dimensions >= 3:
            return "PARTIAL_BUCKET_COVERAGE"
        return "LOW_BUCKET_COVERAGE"


def _ratio(left: float | int | None, right: float | int | None) -> float | None:
    if left is None or right is None:
        return None
    left_value = float(left)
    right_value = float(right)
    if left_value <= 0 or right_value <= 0:
        return None
    return max(left_value, right_value) / min(left_value, right_value)


def _dominant_dex_match(
    target: WalletStrategyFingerprint,
    candidate: WalletStrategyFingerprint,
) -> bool | None:
    if target.dominant_dex is None or candidate.dominant_dex is None:
        return None
    return target.dominant_dex == candidate.dominant_dex


def build_placebo_match_diagnostic(
    target: WalletStrategyFingerprint,
    candidate: WalletStrategyFingerprint,
) -> PlaceboMatchDiagnostic:
    """Compare one candidate against a target using pre-period behavior only."""

    if target.address == candidate.address:
        raise ValueError("target wallet cannot be its own placebo candidate")

    bucket = compare_wallet_strategy_fingerprints(target, candidate)
    target_ready = fingerprint_evidence_ready(target)
    candidate_ready = fingerprint_evidence_ready(candidate)
    activity_ratio = _ratio(
        target.frequency_rate_per_day,
        candidate.frequency_rate_per_day,
    )
    token_ratio = _ratio(target.token_count, candidate.token_count)
    span_ratio = _ratio(target.observed_span_days, candidate.observed_span_days)
    first_exit_ratio = _ratio(
        target.median_first_exit_seconds,
        candidate.median_first_exit_seconds,
    )
    dex_match = _dominant_dex_match(target, candidate)
    dex_share_diff = (
        abs(target.dominant_dex_share_pct - candidate.dominant_dex_share_pct)
        if dex_match is not None
        else None
    )

    warnings: list[str] = []
    if not target_ready:
        warnings.append("target_evidence_not_ready")
    if not candidate_ready:
        warnings.append("candidate_evidence_not_ready")
    if bucket.comparable_dimensions < 3:
        warnings.append("few_comparable_dimensions")
    if activity_ratio is None:
        warnings.append("activity_rate_uncomparable")
    if token_ratio is None:
        warnings.append("token_breadth_uncomparable")
    if span_ratio is None:
        warnings.append("observation_span_uncomparable")
    if first_exit_ratio is None:
        warnings.append("holding_time_uncomparable")
    if dex_match is None:
        warnings.append("dominant_dex_unavailable")
    if candidate.token_count < 10:
        warnings.append("candidate_token_sample_narrow")
    if "short_observation_window" in candidate.flags:
        warnings.append("candidate_short_observation_window")
    if "sequence_coverage_low" in candidate.flags:
        warnings.append("candidate_sequence_coverage_low")

    return PlaceboMatchDiagnostic(
        target_address=target.address,
        candidate_address=candidate.address,
        comparable_dimensions=bucket.comparable_dimensions,
        matching_dimensions=bucket.matching_dimensions,
        bucket_similarity_pct=bucket.similarity_pct,
        active_day_rate_ratio=activity_ratio,
        token_breadth_ratio=token_ratio,
        observed_span_ratio=span_ratio,
        first_exit_ratio=first_exit_ratio,
        roundtrip_abs_diff_pct=abs(
            target.roundtrip_share_pct - candidate.roundtrip_share_pct
        ),
        scale_in_abs_diff_pct=abs(
            target.scale_in_share_pct - candidate.scale_in_share_pct
        ),
        multi_sell_abs_diff_pct=abs(
            target.multi_sell_share_pct - candidate.multi_sell_share_pct
        ),
        reentry_abs_diff_pct=abs(
            target.reentry_share_pct - candidate.reentry_share_pct
        ),
        dominant_dex_match=dex_match,
        dominant_dex_share_abs_diff_pct=dex_share_diff,
        target_evidence_ready=target_ready,
        candidate_evidence_ready=candidate_ready,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _ratio_distance(value: float | None) -> float:
    """Return symmetric log-distance; 1.0 is an exact ratio match."""

    if value is None or value <= 0:
        return math.inf
    return abs(math.log(value))


def placebo_match_sort_key(item: PlaceboMatchDiagnostic) -> tuple:
    """Deterministic lexicographic ordering, deliberately not a weighted score.

    Evidence coverage is considered before behavioral closeness. This avoids an opaque
    pseudo-precision number and keeps every underlying mismatch inspectable in the report.
    """

    return (
        not item.candidate_evidence_ready,
        -item.comparable_dimensions,
        -(item.bucket_similarity_pct if item.bucket_similarity_pct is not None else -1.0),
        _ratio_distance(item.active_day_rate_ratio),
        _ratio_distance(item.token_breadth_ratio),
        _ratio_distance(item.first_exit_ratio),
        item.roundtrip_abs_diff_pct,
        0 if item.dominant_dex_match is True else 1 if item.dominant_dex_match is False else 2,
        _ratio_distance(item.observed_span_ratio),
        item.candidate_address,
    )


def rank_placebo_candidates(
    target: WalletStrategyFingerprint,
    candidates: list[WalletStrategyFingerprint]
    | tuple[WalletStrategyFingerprint, ...],
    *,
    require_evidence_ready: bool = False,
) -> list[PlaceboMatchDiagnostic]:
    """Rank pre-period candidates while preserving weak candidates as explicit evidence gaps."""

    result: list[PlaceboMatchDiagnostic] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.address == target.address or candidate.address in seen:
            continue
        seen.add(candidate.address)
        diagnostic = build_placebo_match_diagnostic(target, candidate)
        if require_evidence_ready and not diagnostic.candidate_evidence_ready:
            continue
        result.append(diagnostic)
    return sorted(result, key=placebo_match_sort_key)


def select_disjoint_placebo_addresses(
    ranked_candidates: list[PlaceboMatchDiagnostic]
    | tuple[PlaceboMatchDiagnostic, ...],
    *,
    count: int,
    require_evidence_ready: bool = True,
) -> tuple[str, ...]:
    """Select candidate addresses from an already frozen ranking.

    The function does not declare the resulting group scientifically matched. It only makes
    deterministic, disjoint selection possible after the analyst has reviewed diagnostics.
    """

    if count <= 0:
        raise ValueError("count must be positive")
    chosen: list[str] = []
    seen: set[str] = set()
    for item in ranked_candidates:
        if item.candidate_address in seen:
            continue
        if require_evidence_ready and not item.candidate_evidence_ready:
            continue
        seen.add(item.candidate_address)
        chosen.append(item.candidate_address)
        if len(chosen) == count:
            break
    if len(chosen) < count:
        raise ValueError("not enough eligible placebo candidates for requested count")
    return tuple(chosen)
