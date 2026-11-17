from dataclasses import dataclass, replace

from src.wallet_strategy_lab import build_wallet_strategy_fingerprint


PROTOCOL_VERSION = "wallet_forward_acquisition_v1"
MAX_ACTIVITY_RATE_PER_DAY = 20.0
MAX_LATEST_SWAP_AGE_SECONDS = 48 * 60 * 60
MIN_ACTIVE_DAYS_7D = 2
MIN_COMPLETE_LIKE_SIZING = 3
MIN_ROUNDTRIP_SHARE_PCT = 50.0
MIN_SWAP_COUNT = 20
MIN_ACTIVITY_RATE_PER_DAY = 1.0


@dataclass(frozen=True)
class WalletForwardAcquisitionProfile:
    address: str
    cutoff_at: int
    swap_count: int
    roundtrip_share_pct: float
    complete_like_sizing_count: int
    frequency_rate_per_day: float
    frequency_bucket: str
    latest_swap_at: int | None
    latest_swap_age_seconds: int | None
    swaps_72h: int
    active_days_7d: int
    signature: str
    flags: tuple[str, ...]
    eligible: bool
    exclusion_reasons: tuple[str, ...]


def _clean_pre_t0_swaps(swaps: list[dict], cutoff_at: int) -> list[dict]:
    clean = []
    for item in swaps:
        block_time = item.get("block_time")
        if (
            item.get("kind") == "swap"
            and item.get("status") == "success"
            and item.get("token_mint")
            and item.get("token_change") is not None
            and block_time is not None
            and int(block_time) <= cutoff_at
        ):
            clean.append(item)
    return sorted(clean, key=lambda item: int(item["block_time"]))


def _eligibility_reasons(
    *,
    swap_count: int,
    roundtrip_share_pct: float,
    complete_like_sizing_count: int,
    frequency_rate_per_day: float,
    latest_swap_age_seconds: int | None,
    active_days_7d: int,
    flags: tuple[str, ...],
) -> list[str]:
    reasons: list[str] = []
    if swap_count < MIN_SWAP_COUNT:
        reasons.append("insufficient_swaps")
    if roundtrip_share_pct < MIN_ROUNDTRIP_SHARE_PCT:
        reasons.append("roundtrip_below_50pct")
    if complete_like_sizing_count < MIN_COMPLETE_LIKE_SIZING:
        reasons.append("insufficient_complete_like_sizing")
    if frequency_rate_per_day < MIN_ACTIVITY_RATE_PER_DAY:
        reasons.append("activity_sparse")
    if frequency_rate_per_day > MAX_ACTIVITY_RATE_PER_DAY:
        reasons.append("activity_above_copyability_ceiling")
    if latest_swap_age_seconds is None:
        reasons.append("latest_swap_unknown")
    elif latest_swap_age_seconds > MAX_LATEST_SWAP_AGE_SECONDS:
        reasons.append("latest_swap_older_than_48h")
    if active_days_7d < MIN_ACTIVE_DAYS_7D:
        reasons.append("insufficient_active_days_7d")
    if "sequence_coverage_low" in flags:
        reasons.append("sequence_coverage_low")
    return list(dict.fromkeys(reasons))


def build_wallet_forward_acquisition_profile(
    address: str,
    swaps: list[dict],
    *,
    cutoff_at: int,
    extra_exclusion_reasons: tuple[str, ...] = (),
) -> WalletForwardAcquisitionProfile:
    clean = _clean_pre_t0_swaps(swaps, cutoff_at)
    fingerprint = build_wallet_strategy_fingerprint(address, clean)

    latest_swap_at = int(clean[-1]["block_time"]) if clean else None
    latest_swap_age_seconds = (
        max(0, cutoff_at - latest_swap_at) if latest_swap_at is not None else None
    )
    cutoff_72h = cutoff_at - 72 * 60 * 60
    cutoff_7d = cutoff_at - 7 * 24 * 60 * 60
    swaps_72h = sum(int(item["block_time"]) >= cutoff_72h for item in clean)
    active_days_7d = len(
        {
            int(item["block_time"]) // 86_400
            for item in clean
            if int(item["block_time"]) >= cutoff_7d
        }
    )

    reasons = _eligibility_reasons(
        swap_count=fingerprint.swap_count,
        roundtrip_share_pct=fingerprint.roundtrip_share_pct,
        complete_like_sizing_count=fingerprint.complete_like_sizing_count,
        frequency_rate_per_day=fingerprint.frequency_rate_per_day,
        latest_swap_age_seconds=latest_swap_age_seconds,
        active_days_7d=active_days_7d,
        flags=fingerprint.flags,
    )
    reasons.extend(extra_exclusion_reasons)
    reasons = list(dict.fromkeys(reasons))

    return WalletForwardAcquisitionProfile(
        address=address,
        cutoff_at=cutoff_at,
        swap_count=fingerprint.swap_count,
        roundtrip_share_pct=fingerprint.roundtrip_share_pct,
        complete_like_sizing_count=fingerprint.complete_like_sizing_count,
        frequency_rate_per_day=fingerprint.frequency_rate_per_day,
        frequency_bucket=fingerprint.frequency_bucket,
        latest_swap_at=latest_swap_at,
        latest_swap_age_seconds=latest_swap_age_seconds,
        swaps_72h=swaps_72h,
        active_days_7d=active_days_7d,
        signature=fingerprint.signature,
        flags=fingerprint.flags,
        eligible=not reasons,
        exclusion_reasons=tuple(reasons),
    )


def with_extra_exclusion(
    profile: WalletForwardAcquisitionProfile,
    reason: str,
) -> WalletForwardAcquisitionProfile:
    reasons = tuple(dict.fromkeys((*profile.exclusion_reasons, reason)))
    return replace(profile, eligible=False, exclusion_reasons=reasons)


def _rank_key(profile: WalletForwardAcquisitionProfile) -> tuple:
    latest_age = (
        profile.latest_swap_age_seconds
        if profile.latest_swap_age_seconds is not None
        else 10**18
    )
    return (
        -profile.active_days_7d,
        -profile.swaps_72h,
        latest_age,
        profile.address,
    )


def select_wallet_forward_cohort(
    profiles: list[WalletForwardAcquisitionProfile]
    | tuple[WalletForwardAcquisitionProfile, ...],
    *,
    max_wallets: int = 5,
) -> list[WalletForwardAcquisitionProfile]:
    if max_wallets < 1:
        raise ValueError("max_wallets precisa ser >= 1")

    ranked = sorted((item for item in profiles if item.eligible), key=_rank_key)
    selected: list[WalletForwardAcquisitionProfile] = []
    seen_signatures: set[str] = set()

    for item in ranked:
        if item.signature in seen_signatures:
            continue
        selected.append(item)
        seen_signatures.add(item.signature)
        if len(selected) >= max_wallets:
            return selected

    selected_addresses = {item.address for item in selected}
    for item in ranked:
        if item.address in selected_addresses:
            continue
        selected.append(item)
        selected_addresses.add(item.address)
        if len(selected) >= max_wallets:
            break

    return selected
