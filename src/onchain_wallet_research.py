from collections import Counter
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class OnchainWalletProfile:
    address: str
    swap_count: int
    token_count: int
    buy_count: int
    sell_count: int
    first_swap_at: int | None
    last_swap_at: int | None
    observed_span_days: float
    median_actions_per_token: float
    roundtrip_token_share_pct: float
    multi_action_token_share_pct: float
    scale_in_token_share_pct: float
    partial_exit_token_share_pct: float
    reentry_token_share_pct: float
    median_first_exit_seconds: float | None
    median_roundtrip_span_seconds: float | None
    median_swap_gap_seconds: float | None
    dex_mix: dict[str, int]
    sample_grade: str
    flags: tuple[str, ...]


def _sample_grade(count: int) -> str:
    if count < 20:
        return "INSUFFICIENT"
    if count < 50:
        return "PRELIMINARY"
    if count < 150:
        return "DEVELOPING"
    return "LARGER_SAMPLE"


def _pct(count: int, total: int) -> float:
    return 100.0 * count / total if total else 0.0


def build_onchain_wallet_profile(address: str, swaps: list[dict]) -> OnchainWalletProfile:
    """Describe observed swap sequencing without Solana Tracker Data API.

    This intentionally does not infer profitability, token quality or market state. It only
    summarizes the sequence that is present in the locally synchronized Solana RPC sample.
    """
    clean = [
        item
        for item in swaps
        if item.get("kind") == "swap"
        and item.get("status") == "success"
        and item.get("token_mint")
        and item.get("token_change") is not None
        and item.get("block_time") is not None
    ]
    clean.sort(key=lambda item: int(item["block_time"]))

    per_token: dict[str, list[dict]] = {}
    for item in clean:
        per_token.setdefault(str(item["token_mint"]), []).append(item)

    roundtrips = multi_action = scale_in = partial_exit = reentry = 0
    first_exit_durations: list[float] = []
    roundtrip_spans: list[float] = []
    action_counts: list[float] = []

    for token_swaps in per_token.values():
        action_counts.append(float(len(token_swaps)))
        buys = [item for item in token_swaps if float(item["token_change"]) > 0]
        sells = [item for item in token_swaps if float(item["token_change"]) < 0]
        if len(token_swaps) > 2:
            multi_action += 1
        if not buys or not sells:
            continue

        roundtrips += 1
        first_buy_at = int(buys[0]["block_time"])
        sells_after_first_buy = [
            item for item in sells if int(item["block_time"]) >= first_buy_at
        ]
        if sells_after_first_buy:
            first_sell_at = int(sells_after_first_buy[0]["block_time"])
            last_sell_at = int(sells_after_first_buy[-1]["block_time"])
            first_exit_durations.append(float(first_sell_at - first_buy_at))
            roundtrip_spans.append(float(last_sell_at - first_buy_at))

            buys_before_first_sell = [
                item for item in buys if int(item["block_time"]) <= first_sell_at
            ]
            if len(buys_before_first_sell) >= 2:
                scale_in += 1
            if len(sells_after_first_buy) >= 2:
                partial_exit += 1
            if any(int(item["block_time"]) > first_sell_at for item in buys):
                reentry += 1

    times = [int(item["block_time"]) for item in clean]
    gaps = [
        float(current - previous)
        for previous, current in zip(times, times[1:])
        if current >= previous
    ]
    dex_mix = Counter(str(item.get("dex") or "unknown") for item in clean)
    token_count = len(per_token)
    first_at = times[0] if times else None
    last_at = times[-1] if times else None
    observed_span_days = (
        max(0.0, float(last_at - first_at) / 86_400.0)
        if first_at is not None and last_at is not None
        else 0.0
    )

    flags = []
    if len(clean) < 20:
        flags.append("onchain_sample_too_small")
    # If most observed tokens do not contain both a buy and a sell inside the
    # synchronized window, sequence summaries can overstate how complete the
    # wallet history is. Flag that condition instead of treating the sample as
    # representative of full round trips.
    if token_count and roundtrips / token_count < 0.50:
        flags.append("many_tokens_without_observed_roundtrip")
    if clean and not any(float(item["token_change"]) < 0 for item in clean):
        flags.append("no_observed_sells")
    if observed_span_days < 1 and len(clean) < 150:
        flags.append("short_observation_window")

    return OnchainWalletProfile(
        address=address,
        swap_count=len(clean),
        token_count=token_count,
        buy_count=sum(float(item["token_change"]) > 0 for item in clean),
        sell_count=sum(float(item["token_change"]) < 0 for item in clean),
        first_swap_at=first_at,
        last_swap_at=last_at,
        observed_span_days=observed_span_days,
        median_actions_per_token=median(action_counts) if action_counts else 0.0,
        roundtrip_token_share_pct=_pct(roundtrips, token_count),
        multi_action_token_share_pct=_pct(multi_action, token_count),
        scale_in_token_share_pct=_pct(scale_in, roundtrips),
        partial_exit_token_share_pct=_pct(partial_exit, roundtrips),
        reentry_token_share_pct=_pct(reentry, roundtrips),
        median_first_exit_seconds=median(first_exit_durations) if first_exit_durations else None,
        median_roundtrip_span_seconds=median(roundtrip_spans) if roundtrip_spans else None,
        median_swap_gap_seconds=median(gaps) if gaps else None,
        dex_mix=dict(dex_mix.most_common()),
        sample_grade=_sample_grade(len(clean)),
        flags=tuple(flags),
    )
