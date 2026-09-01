import statistics
from collections import Counter
from dataclasses import dataclass

from src.wallet_quote_drift import WalletQuoteDriftObservation
from src.wallet_quote_watch import ForwardBuyEvent


@dataclass(frozen=True)
class WalletForwardDriftClusterSummary:
    delay_seconds: int
    event_count: int
    token_cluster_count: int
    event_median_adverse_drift_pct: float | None
    median_of_token_medians_pct: float | None
    min_token_median_pct: float | None
    max_token_median_pct: float | None


@dataclass(frozen=True)
class WalletForwardDependenceSummary:
    buy_event_count: int
    wallet_count: int
    token_count: int
    wallet_token_cluster_count: int
    repeated_wallet_token_buy_count: int
    repeated_wallet_token_buy_share_pct: float
    largest_wallet_buy_count: int
    largest_wallet_buy_share_pct: float
    largest_token_buy_count: int
    largest_token_buy_share_pct: float
    largest_wallet_token_cluster_count: int
    largest_wallet_token_cluster_share_pct: float
    cautions: tuple[str, ...]
    drift_clusters: tuple[WalletForwardDriftClusterSummary, ...]


def _largest(counter: Counter) -> tuple[int, float]:
    total = sum(counter.values())
    if not total:
        return 0, 0.0
    count = max(counter.values())
    return count, 100.0 * count / total


def summarize_wallet_forward_dependence(
    buys: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    *,
    drift_observations: list[WalletQuoteDriftObservation]
    | tuple[WalletQuoteDriftObservation, ...] = (),
) -> WalletForwardDependenceSummary:
    """Expose repeated-event dependence before event-level metrics are interpreted.

    Several BUY observations from the same wallet/token are useful operational events but are
    not independent market opportunities. A fast wallet can generate many event rows while the
    run still covers only one or two tokens. This audit keeps both units visible and also
    reports quote drift after giving each token equal weight through a median-within-token,
    then median-across-token aggregation.

    Caution labels are descriptive audit flags, never strategy gates.
    """
    event_keys: set[str] = set()
    for item in buys:
        if not item.observation_key.strip():
            raise ValueError("buy observation_key cannot be empty")
        if item.observation_key in event_keys:
            raise ValueError("duplicate buy observation_key")
        event_keys.add(item.observation_key)

    wallet_counts = Counter(item.wallet_address for item in buys)
    token_counts = Counter(item.token_mint for item in buys)
    wallet_token_counts = Counter((item.wallet_address, item.token_mint) for item in buys)
    event_count = len(buys)
    cluster_count = len(wallet_token_counts)
    repeated_count = max(0, event_count - cluster_count)
    repeated_share = 100.0 * repeated_count / event_count if event_count else 0.0
    largest_wallet_count, largest_wallet_share = _largest(wallet_counts)
    largest_token_count, largest_token_share = _largest(token_counts)
    largest_cluster_count, largest_cluster_share = _largest(wallet_token_counts)

    cautions: list[str] = []
    # Thresholds only surface dependence risk; they do not accept/reject a wallet or strategy.
    if event_count >= 5 and len(token_counts) < 5:
        cautions.append("few_unique_tokens_for_event_level_inference")
    if event_count >= 5 and largest_token_share >= 50.0:
        cautions.append("single_token_dominates_buy_events")
    if event_count >= 5 and largest_wallet_share >= 80.0:
        cautions.append("single_wallet_dominates_buy_events")
    if event_count >= 5 and repeated_share >= 50.0:
        cautions.append("repeated_same_wallet_token_actions")

    drift_summaries: list[WalletForwardDriftClusterSummary] = []
    for delay in sorted({item.delay_seconds for item in drift_observations}):
        group = [item for item in drift_observations if item.delay_seconds == delay]
        event_values = [item.adverse_execution_drift_pct for item in group]
        by_token: dict[str, list[float]] = {}
        for item in group:
            by_token.setdefault(item.token_mint, []).append(item.adverse_execution_drift_pct)
        token_medians = [statistics.median(values) for values in by_token.values() if values]
        drift_summaries.append(
            WalletForwardDriftClusterSummary(
                delay_seconds=delay,
                event_count=len(group),
                token_cluster_count=len(token_medians),
                event_median_adverse_drift_pct=(
                    statistics.median(event_values) if event_values else None
                ),
                median_of_token_medians_pct=(
                    statistics.median(token_medians) if token_medians else None
                ),
                min_token_median_pct=(min(token_medians) if token_medians else None),
                max_token_median_pct=(max(token_medians) if token_medians else None),
            )
        )

    return WalletForwardDependenceSummary(
        buy_event_count=event_count,
        wallet_count=len(wallet_counts),
        token_count=len(token_counts),
        wallet_token_cluster_count=cluster_count,
        repeated_wallet_token_buy_count=repeated_count,
        repeated_wallet_token_buy_share_pct=repeated_share,
        largest_wallet_buy_count=largest_wallet_count,
        largest_wallet_buy_share_pct=largest_wallet_share,
        largest_token_buy_count=largest_token_count,
        largest_token_buy_share_pct=largest_token_share,
        largest_wallet_token_cluster_count=largest_cluster_count,
        largest_wallet_token_cluster_share_pct=largest_cluster_share,
        cautions=tuple(cautions),
        drift_clusters=tuple(drift_summaries),
    )
