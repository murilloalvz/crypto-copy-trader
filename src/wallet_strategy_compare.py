from dataclasses import dataclass
from statistics import median

from src.wallet_strategy_lab import WalletStrategyFingerprint


@dataclass(frozen=True)
class WalletStrategySimilarity:
    left_address: str
    right_address: str
    comparable_dimensions: int
    matching_dimensions: int
    similarity_pct: float | None
    shared_signature: bool
    matching: tuple[str, ...]
    differing: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StrategyPatternSupport:
    signature: str
    wallet_count: int
    evidence_ready_count: int
    addresses: tuple[str, ...]
    support_grade: str
    median_first_exit_seconds: float | None
    median_scale_in_share_pct: float
    median_multi_sell_share_pct: float
    median_reentry_share_pct: float


_DIMENSIONS = (
    ("holding", "holding_bucket"),
    ("exit", "exit_bucket"),
    ("reentry", "reentry_bucket"),
    ("frequency", "frequency_bucket"),
)


def _dimension_is_informative(
    fingerprint: WalletStrategyFingerprint,
    dimension: str,
    value: str,
) -> bool:
    if fingerprint.swap_count <= 0:
        return False
    if dimension == "holding" and value == "holding_unknown":
        return False
    if dimension == "exit" and value == "exit_sizing_insufficient":
        return False
    return True


def fingerprint_evidence_ready(fingerprint: WalletStrategyFingerprint) -> bool:
    """Return whether the local sample is usable for cross-wallet pattern research.

    This is an evidence-coverage gate only. It says nothing about profitability or whether a
    wallet should be copied. Short bursts, narrow token samples and undersized exit-sizing
    samples remain descriptive, but are not promoted to "ready" because a fingerprint built
    from only a few token episodes may describe those episodes rather than a repeatable wallet
    strategy.
    """
    if fingerprint.sample_grade == "INSUFFICIENT":
        return False
    if fingerprint.token_count < 10:
        return False
    if fingerprint.roundtrip_share_pct < 50.0:
        return False
    if fingerprint.complete_like_sizing_count < 3:
        return False
    blocking_flags = {
        "sequence_coverage_low",
        "short_observation_window",
        "strategy_token_sample_too_small",
        "exit_sizing_sample_too_small",
        "exit_sizing_quantity_anomalies",
    }
    if any(flag in blocking_flags for flag in fingerprint.flags):
        return False
    return True


def compare_wallet_strategy_fingerprints(
    left: WalletStrategyFingerprint,
    right: WalletStrategyFingerprint,
) -> WalletStrategySimilarity:
    matching: list[str] = []
    differing: list[str] = []
    comparable = 0

    for dimension, field in _DIMENSIONS:
        left_value = str(getattr(left, field))
        right_value = str(getattr(right, field))
        if not (
            _dimension_is_informative(left, dimension, left_value)
            and _dimension_is_informative(right, dimension, right_value)
        ):
            continue
        comparable += 1
        if left_value == right_value:
            matching.append(dimension)
        else:
            differing.append(dimension)

    warnings: list[str] = []
    if not fingerprint_evidence_ready(left):
        warnings.append("left_evidence_not_ready")
    if not fingerprint_evidence_ready(right):
        warnings.append("right_evidence_not_ready")
    if comparable < 3:
        warnings.append("few_comparable_dimensions")

    similarity = 100.0 * len(matching) / comparable if comparable else None
    return WalletStrategySimilarity(
        left_address=left.address,
        right_address=right.address,
        comparable_dimensions=comparable,
        matching_dimensions=len(matching),
        similarity_pct=similarity,
        shared_signature=(
            left.signature == right.signature
            and comparable == len(_DIMENSIONS)
        ),
        matching=tuple(matching),
        differing=tuple(differing),
        warnings=tuple(warnings),
    )


def build_pairwise_strategy_comparisons(
    fingerprints: list[WalletStrategyFingerprint]
    | tuple[WalletStrategyFingerprint, ...],
) -> list[WalletStrategySimilarity]:
    rows = list(fingerprints)
    comparisons: list[WalletStrategySimilarity] = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1 :]:
            comparisons.append(compare_wallet_strategy_fingerprints(left, right))
    comparisons.sort(
        key=lambda item: (
            -(item.similarity_pct if item.similarity_pct is not None else -1.0),
            item.left_address,
            item.right_address,
        )
    )
    return comparisons


def _support_grade(wallet_count: int, evidence_ready_count: int) -> str:
    if wallet_count < 2:
        return "SINGLE_WALLET"
    if evidence_ready_count < 2:
        return "REPEATED_LOW_COVERAGE"
    if evidence_ready_count < 5:
        return "MULTI_WALLET_PRELIMINARY"
    return "MULTI_WALLET_BROADER_SUPPORT"


def summarize_recurring_strategy_patterns(
    fingerprints: list[WalletStrategyFingerprint]
    | tuple[WalletStrategyFingerprint, ...],
) -> list[StrategyPatternSupport]:
    grouped: dict[str, list[WalletStrategyFingerprint]] = {}
    for item in fingerprints:
        grouped.setdefault(item.signature, []).append(item)

    result: list[StrategyPatternSupport] = []
    for signature, group in grouped.items():
        first_exit = [
            item.median_first_exit_seconds
            for item in group
            if item.median_first_exit_seconds is not None
        ]
        ready_count = sum(fingerprint_evidence_ready(item) for item in group)
        result.append(
            StrategyPatternSupport(
                signature=signature,
                wallet_count=len(group),
                evidence_ready_count=ready_count,
                addresses=tuple(sorted(item.address for item in group)),
                support_grade=_support_grade(len(group), ready_count),
                median_first_exit_seconds=(median(first_exit) if first_exit else None),
                median_scale_in_share_pct=median(
                    item.scale_in_share_pct for item in group
                ),
                median_multi_sell_share_pct=median(
                    item.multi_sell_share_pct for item in group
                ),
                median_reentry_share_pct=median(
                    item.reentry_share_pct for item in group
                ),
            )
        )

    result.sort(
        key=lambda item: (
            -item.evidence_ready_count,
            -item.wallet_count,
            item.signature,
        )
    )
    return result
