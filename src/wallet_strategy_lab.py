from collections import Counter
from dataclasses import dataclass

from src.onchain_wallet_research import build_onchain_wallet_profile
from src.wallet_exit_sizing import analyze_exit_sizing, summarize_exit_sizing


@dataclass(frozen=True)
class WalletStrategyFingerprint:
    address: str
    swap_count: int
    token_count: int
    observed_span_days: float
    sample_grade: str
    swaps_per_day: float
    frequency_rate_per_day: float
    frequency_basis: str
    holding_bucket: str
    exit_bucket: str
    reentry_bucket: str
    frequency_bucket: str
    median_first_exit_seconds: float | None
    roundtrip_share_pct: float
    scale_in_share_pct: float
    multi_sell_share_pct: float
    reentry_share_pct: float
    complete_like_sizing_count: int
    complete_multi_sell_count: int
    median_complete_multi_first_sell_fraction_pct: float | None
    median_complete_multi_runner_pct: float | None
    dominant_dex: str | None
    dominant_dex_share_pct: float
    signature: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class WalletStrategyLabSummary:
    wallet_count: int
    signatures: dict[str, int]
    holding_buckets: dict[str, int]
    exit_buckets: dict[str, int]
    reentry_buckets: dict[str, int]
    frequency_buckets: dict[str, int]


def _holding_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "holding_unknown"
    if seconds < 15 * 60:
        return "ultra_short"
    if seconds < 6 * 3_600:
        return "intraday"
    if seconds < 36 * 3_600:
        return "one_day"
    if seconds < 7 * 86_400:
        return "swing"
    return "long_hold"


def _frequency_bucket(swaps_per_day: float) -> str:
    if swaps_per_day >= 20:
        return "high_frequency"
    if swaps_per_day >= 5:
        return "active"
    if swaps_per_day >= 1:
        return "moderate"
    return "sparse"


def _reentry_bucket(reentry_share_pct: float) -> str:
    if reentry_share_pct >= 40:
        return "frequent_reentry"
    if reentry_share_pct >= 15:
        return "occasional_reentry"
    return "rare_reentry"


def _exit_bucket(
    *,
    complete_like_count: int,
    complete_multi_sell_count: int,
    median_complete_multi_first_sell_fraction_pct: float | None,
) -> str:
    if complete_like_count < 3:
        return "exit_sizing_insufficient"

    multi_share = 100.0 * complete_multi_sell_count / complete_like_count
    if (
        complete_multi_sell_count >= 2
        and multi_share >= 40.0
        and median_complete_multi_first_sell_fraction_pct is not None
        and median_complete_multi_first_sell_fraction_pct <= 75.0
    ):
        return "staged_exit_dominant"
    if multi_share <= 20.0:
        return "single_exit_dominant"
    return "mixed_exit"


def build_wallet_strategy_fingerprint(
    address: str,
    swaps: list[dict],
) -> WalletStrategyFingerprint:
    """Build a deterministic descriptive fingerprint from the observed local RPC sample.

    This is intentionally not a profitability score and does not decide whether a wallet
    should be copied. It is a research abstraction that groups observed execution behavior
    so multiple wallets can be compared without using the Solana Tracker Data API.

    Calendar swaps/day is kept as a descriptive field, but the frequency archetype uses the
    median inter-swap gap when available. This prevents one distant historical observation or
    a partial backfill from turning an otherwise active execution pattern into a false
    ``sparse`` classification.
    """
    profile = build_onchain_wallet_profile(address, swaps)
    sizing_rows = analyze_exit_sizing(swaps)
    sizing = summarize_exit_sizing(sizing_rows)

    effective_days = max(profile.observed_span_days, 1.0 / 24.0)
    calendar_swaps_per_day = (
        profile.swap_count / effective_days if profile.swap_count else 0.0
    )
    if profile.median_swap_gap_seconds is not None and profile.median_swap_gap_seconds > 0:
        frequency_rate_per_day = 86_400.0 / profile.median_swap_gap_seconds
        frequency_basis = "median_swap_gap"
    else:
        frequency_rate_per_day = calendar_swaps_per_day
        frequency_basis = "calendar_span"

    holding_bucket = _holding_bucket(profile.median_first_exit_seconds)
    frequency_bucket = _frequency_bucket(frequency_rate_per_day)
    reentry_bucket = _reentry_bucket(profile.reentry_token_share_pct)
    exit_bucket = _exit_bucket(
        complete_like_count=sizing.complete_like_count,
        complete_multi_sell_count=sizing.complete_multi_sell_count,
        median_complete_multi_first_sell_fraction_pct=(
            sizing.median_complete_multi_first_sell_fraction_pct
        ),
    )

    dominant_dex = None
    dominant_dex_share_pct = 0.0
    if profile.dex_mix and profile.swap_count:
        dominant_dex, dominant_count = max(
            profile.dex_mix.items(), key=lambda item: item[1]
        )
        dominant_dex_share_pct = 100.0 * dominant_count / profile.swap_count

    flags = list(profile.flags)
    if sizing.token_count < 5:
        flags.append("exit_sizing_sample_too_small")
    if sizing.quantity_anomaly_share_pct > 10.0:
        flags.append("exit_sizing_quantity_anomalies")
    if profile.roundtrip_token_share_pct < 50.0:
        flags.append("sequence_coverage_low")
    if calendar_swaps_per_day > 0 and frequency_rate_per_day > 0:
        ratio = max(calendar_swaps_per_day, frequency_rate_per_day) / min(
            calendar_swaps_per_day, frequency_rate_per_day
        )
        if ratio >= 3.0:
            flags.append("calendar_frequency_differs_from_active_intensity")

    signature = "|".join(
        [holding_bucket, exit_bucket, reentry_bucket, frequency_bucket]
    )

    return WalletStrategyFingerprint(
        address=address,
        swap_count=profile.swap_count,
        token_count=profile.token_count,
        observed_span_days=profile.observed_span_days,
        sample_grade=profile.sample_grade,
        swaps_per_day=calendar_swaps_per_day,
        frequency_rate_per_day=frequency_rate_per_day,
        frequency_basis=frequency_basis,
        holding_bucket=holding_bucket,
        exit_bucket=exit_bucket,
        reentry_bucket=reentry_bucket,
        frequency_bucket=frequency_bucket,
        median_first_exit_seconds=profile.median_first_exit_seconds,
        roundtrip_share_pct=profile.roundtrip_token_share_pct,
        scale_in_share_pct=profile.scale_in_token_share_pct,
        multi_sell_share_pct=profile.partial_exit_token_share_pct,
        reentry_share_pct=profile.reentry_token_share_pct,
        complete_like_sizing_count=sizing.complete_like_count,
        complete_multi_sell_count=sizing.complete_multi_sell_count,
        median_complete_multi_first_sell_fraction_pct=(
            sizing.median_complete_multi_first_sell_fraction_pct
        ),
        median_complete_multi_runner_pct=sizing.median_complete_multi_runner_pct,
        dominant_dex=dominant_dex,
        dominant_dex_share_pct=dominant_dex_share_pct,
        signature=signature,
        flags=tuple(dict.fromkeys(flags)),
    )


def summarize_wallet_strategy_lab(
    fingerprints: list[WalletStrategyFingerprint]
    | tuple[WalletStrategyFingerprint, ...],
) -> WalletStrategyLabSummary:
    rows = list(fingerprints)
    return WalletStrategyLabSummary(
        wallet_count=len(rows),
        signatures=dict(Counter(item.signature for item in rows).most_common()),
        holding_buckets=dict(
            Counter(item.holding_bucket for item in rows).most_common()
        ),
        exit_buckets=dict(Counter(item.exit_bucket for item in rows).most_common()),
        reentry_buckets=dict(
            Counter(item.reentry_bucket for item in rows).most_common()
        ),
        frequency_buckets=dict(
            Counter(item.frequency_bucket for item in rows).most_common()
        ),
    )
