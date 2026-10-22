from collections import Counter
from dataclasses import dataclass

from src.wallet_strategy_compare import fingerprint_evidence_ready
from src.wallet_strategy_lab import WalletStrategyFingerprint


@dataclass(frozen=True)
class WalletStrategyReadiness:
    address: str
    stage: str
    evidence_ready: bool
    blocker_count: int
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]


@dataclass(frozen=True)
class WalletStrategyReadinessSummary:
    wallet_count: int
    evidence_ready_count: int
    stages: dict[str, int]
    blockers: dict[str, int]
    next_actions: dict[str, int]


_BLOCKING_FLAGS = {
    "sequence_coverage_low",
    "short_observation_window",
    "strategy_token_sample_too_small",
    "exit_sizing_sample_too_small",
    "exit_sizing_quantity_anomalies",
}


def assess_wallet_strategy_readiness(fingerprint: WalletStrategyFingerprint) -> WalletStrategyReadiness:
    blockers: list[str] = []
    if fingerprint.sample_grade == "INSUFFICIENT":
        blockers.append("sample_grade_insufficient")
    if fingerprint.swap_count < 20:
        blockers.append("swap_sample_below_20")
    if fingerprint.token_count < 10:
        blockers.append("token_sample_below_10")
    if fingerprint.roundtrip_share_pct < 50.0:
        blockers.append("roundtrip_coverage_below_50")
    if fingerprint.complete_like_sizing_count < 3:
        blockers.append("complete_like_cycles_below_3")
    blockers.extend(flag for flag in fingerprint.flags if flag in _BLOCKING_FLAGS)
    blockers = list(dict.fromkeys(blockers))

    ready = fingerprint_evidence_ready(fingerprint)
    if ready:
        stage = "DESCRIPTIVE_READY"
    elif fingerprint.sample_grade == "INSUFFICIENT" or fingerprint.swap_count < 20:
        stage = "INSUFFICIENT_SAMPLE"
    else:
        stage = "EVIDENCE_GAPS"

    actions: list[str] = []
    blocker_set = set(blockers)
    if ready:
        actions.extend(("FORWARD_WATCH", "CAUSAL_CONTEXT_REVIEW"))
    else:
        if {"roundtrip_coverage_below_50", "sequence_coverage_low"} & blocker_set:
            actions.append("SELECTIVE_BACKFILL_SEQUENCE")
        if {"token_sample_below_10", "strategy_token_sample_too_small", "short_observation_window"} & blocker_set:
            actions.append("SELECTIVE_BACKFILL_BREADTH")
        if {"complete_like_cycles_below_3", "exit_sizing_sample_too_small"} & blocker_set:
            actions.append("SELECTIVE_BACKFILL_EXITS")
        if "exit_sizing_quantity_anomalies" in blocker_set:
            actions.append("DATA_QUALITY_AUDIT")
        if fingerprint.swap_count >= 20 and fingerprint.token_count >= 5:
            actions.append("FORWARD_WATCH_OBSERVABILITY")
        if not actions:
            actions.append("COLLECT_MORE_LOCAL_SAMPLE")

    return WalletStrategyReadiness(
        address=fingerprint.address,
        stage=stage,
        evidence_ready=ready,
        blocker_count=len(blockers),
        blockers=tuple(blockers),
        next_actions=tuple(dict.fromkeys(actions)),
    )


def summarize_wallet_strategy_readiness(rows: list[WalletStrategyReadiness] | tuple[WalletStrategyReadiness, ...]) -> WalletStrategyReadinessSummary:
    items = list(rows)
    return WalletStrategyReadinessSummary(
        wallet_count=len(items),
        evidence_ready_count=sum(item.evidence_ready for item in items),
        stages=dict(Counter(item.stage for item in items).most_common()),
        blockers=dict(Counter(blocker for item in items for blocker in item.blockers).most_common()),
        next_actions=dict(Counter(action for item in items for action in item.next_actions).most_common()),
    )
