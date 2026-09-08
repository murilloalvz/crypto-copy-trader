from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.market_observation_store import StoredMarketTrade


OPPORTUNITY_WALLET_CONVERGENCE_VERSION = (
    "opportunity_wallet_convergence_v60_1_t0_anchored_dual_clock"
)


@dataclass(frozen=True)
class FrozenWalletCohortMemberV60:
    wallet_address: str
    cohort_key: str
    frozen_at: int
    strategy_signature: str | None = None
    evidence_version: str | None = None


@dataclass(frozen=True)
class WalletConvergenceEvidenceV60:
    method_version: str
    acquisition_run_key: str
    token_mint: str
    market_anchor_time: int
    as_of: int
    window_seconds: int
    cohort_key: str
    eligible_cohort_size: int
    market_event_count: int
    market_wallet_identity_coverage_pct: float | None
    cohort_event_count: int
    cohort_buy_event_count: int
    cohort_sell_event_count: int
    unique_cohort_wallet_count: int
    unique_cohort_buy_wallet_count: int
    unique_cohort_sell_wallet_count: int
    unique_strategy_signature_count: int | None
    cohort_buy_sell_overlap_count: int
    repeated_cohort_event_share_pct: float | None
    cohort_share_of_known_wallet_events_pct: float | None
    first_cohort_buy_offset_seconds: int | None
    last_cohort_buy_offset_seconds: int | None
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_member(member: FrozenWalletCohortMemberV60) -> None:
    _required(member.wallet_address, "wallet_address")
    _required(member.cohort_key, "cohort_key")
    if int(member.frozen_at) < 0:
        raise ValueError("frozen_at must be non-negative")
    if member.strategy_signature is not None and not member.strategy_signature.strip():
        raise ValueError("strategy_signature cannot be blank")
    if member.evidence_version is not None and not member.evidence_version.strip():
        raise ValueError("evidence_version cannot be blank")


def build_wallet_convergence_evidence_v60(
    *,
    acquisition_run_key: str,
    token_mint: str,
    as_of: int,
    window_seconds: int,
    cohort_key: str,
    members: Iterable[FrozenWalletCohortMemberV60],
    stored_trades: Iterable[StoredMarketTrade],
    market_anchor_time: int | None = None,
) -> WalletConvergenceEvidenceV60:
    """Describe pre-frozen wallet participation after a market-first episode exists.

    ``market_anchor_time`` controls the market window and the cohort-membership freeze boundary;
    ``as_of`` controls what was actually known. For prospective episode research, the intended
    call is episode T0 as the market anchor plus research_decision_as_of as the knowledge cutoff.

    This prevents two subtle leaks when the decision occurs after the episode trigger:
    - a wallet enrolled between T0 and the research decision cannot retroactively join the cohort;
    - a post-T0 trade cannot enter the pre-T0 market window merely because it was known by decision.

    When ``market_anchor_time`` is omitted it defaults to ``as_of`` for backward compatibility.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    mint = _required(token_mint, "token_mint")
    cohort = _required(cohort_key, "cohort_key")
    cutoff = int(as_of)
    anchor = cutoff if market_anchor_time is None else int(market_anchor_time)
    if cutoff < 0 or anchor < 0:
        raise ValueError("market and knowledge timestamps must be non-negative")
    if anchor > cutoff:
        raise ValueError("market_anchor_time cannot be after as_of")
    if int(window_seconds) <= 0:
        raise ValueError("window_seconds must be positive")
    window = int(window_seconds)

    by_wallet: dict[str, FrozenWalletCohortMemberV60] = {}
    for member in members:
        _validate_member(member)
        if member.wallet_address in by_wallet:
            raise ValueError("duplicate wallet in cohort input")
        by_wallet[member.wallet_address] = member

    eligible_members = {
        address: member
        for address, member in by_wallet.items()
        if member.cohort_key == cohort and int(member.frozen_at) < anchor
    }

    lower = anchor - window
    market_rows = [
        item
        for item in stored_trades
        if item.acquisition_run_key == run_key
        and item.observation.token_mint == mint
        and lower < int(item.observation.chain_time) <= anchor
        and int(item.observation.observed_at) <= cutoff
    ]
    market_rows.sort(
        key=lambda item: (
            int(item.observation.chain_time),
            int(item.observation.observed_at),
            item.event_key,
        )
    )

    known_wallet_rows = [item for item in market_rows if item.observation.wallet_address]
    wallet_coverage = (
        100.0 * len(known_wallet_rows) / len(market_rows) if market_rows else None
    )

    cohort_rows = [
        item
        for item in known_wallet_rows
        if str(item.observation.wallet_address) in eligible_members
    ]
    buy_rows = [item for item in cohort_rows if item.observation.side == "buy"]
    sell_rows = [item for item in cohort_rows if item.observation.side == "sell"]

    cohort_wallets = {str(item.observation.wallet_address) for item in cohort_rows}
    buy_wallets = {str(item.observation.wallet_address) for item in buy_rows}
    sell_wallets = {str(item.observation.wallet_address) for item in sell_rows}
    overlap = buy_wallets & sell_wallets

    signatures = {
        eligible_members[address].strategy_signature
        for address in cohort_wallets
        if eligible_members[address].strategy_signature is not None
    }
    signature_coverage_complete = bool(cohort_wallets) and all(
        eligible_members[address].strategy_signature is not None
        for address in cohort_wallets
    )
    unique_signature_count = len(signatures) if signature_coverage_complete else None

    repeated_share = None
    if cohort_rows:
        repeated_share = 100.0 * (len(cohort_rows) - len(cohort_wallets)) / len(cohort_rows)

    cohort_known_share = None
    if known_wallet_rows:
        cohort_known_share = 100.0 * len(cohort_rows) / len(known_wallet_rows)

    buy_offsets = [int(item.observation.chain_time) - anchor for item in buy_rows]

    flags: list[str] = []
    if not eligible_members:
        flags.append("no_cohort_members_frozen_before_market_anchor")
    if market_rows and len(known_wallet_rows) != len(market_rows):
        flags.append("partial_market_wallet_identity_coverage")
    if cohort_wallets and not signature_coverage_complete:
        flags.append("partial_strategy_signature_coverage")
    if not cohort_rows:
        flags.append("no_frozen_cohort_participation_in_window")
    if cohort_rows and not buy_rows:
        flags.append("cohort_participation_without_buy_event")

    return WalletConvergenceEvidenceV60(
        method_version=OPPORTUNITY_WALLET_CONVERGENCE_VERSION,
        acquisition_run_key=run_key,
        token_mint=mint,
        market_anchor_time=anchor,
        as_of=cutoff,
        window_seconds=window,
        cohort_key=cohort,
        eligible_cohort_size=len(eligible_members),
        market_event_count=len(market_rows),
        market_wallet_identity_coverage_pct=wallet_coverage,
        cohort_event_count=len(cohort_rows),
        cohort_buy_event_count=len(buy_rows),
        cohort_sell_event_count=len(sell_rows),
        unique_cohort_wallet_count=len(cohort_wallets),
        unique_cohort_buy_wallet_count=len(buy_wallets),
        unique_cohort_sell_wallet_count=len(sell_wallets),
        unique_strategy_signature_count=unique_signature_count,
        cohort_buy_sell_overlap_count=len(overlap),
        repeated_cohort_event_share_pct=repeated_share,
        cohort_share_of_known_wallet_events_pct=cohort_known_share,
        first_cohort_buy_offset_seconds=min(buy_offsets) if buy_offsets else None,
        last_cohort_buy_offset_seconds=max(buy_offsets) if buy_offsets else None,
        data_quality_flags=tuple(flags),
    )
