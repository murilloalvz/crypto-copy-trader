import math
from dataclasses import dataclass
from statistics import median


OPPORTUNITY_WALLET_INTELLIGENCE_VERSION = (
    "opportunity_wallet_intelligence_v1_1_market_first_association"
)


@dataclass(frozen=True)
class OpportunityWalletParticipation:
    """One wallet action observed inside the current opportunity episode."""

    episode_key: str
    wallet_address: str
    token_mint: str
    side: str
    chain_time: int
    observed_at: int
    notional_usd: float | None = None


@dataclass(frozen=True)
class HistoricalWalletOutcome:
    """A prior *wallet-owned* outcome known by the current causal clock.

    This type is intentionally separate from market-first opportunity outcomes. A forward +5/+15/+60
    result for a market episode where a wallet participated is not the wallet's realized PnL and must
    never be stuffed into ``realized_return_pct``. The market-first association type below carries that
    different meaning explicitly.
    """

    episode_key: str
    wallet_address: str
    token_mint: str
    entry_observed_at: int
    outcome_observed_at: int | None
    realized_return_pct: float | None = None
    hold_seconds: int | None = None


@dataclass(frozen=True)
class HistoricalWalletOpportunityAssociation:
    """A wallet's participation in a prior market-first opportunity with a resolved quote label.

    ``executable_quote_return_pct`` is the return of the *market opportunity* from the official
    executable buy quote to the official executable sell quote at one predeclared horizon. It is
    association evidence about a wallet that was present, not a claim that the wallet bought/sold at
    those prices, held for that horizon, or obtained an on-chain fill.
    """

    episode_key: str
    wallet_address: str
    token_mint: str
    prior_decision_as_of: int
    outcome_observed_at: int
    horizon_seconds: int
    executable_quote_return_pct: float
    entry_quote_key: str
    exit_quote_key: str
    method_version: str


@dataclass(frozen=True)
class WalletOpportunityEvidence:
    wallet_address: str
    current_event_count: int
    current_buy_count: int
    current_sell_count: int
    current_notional_usd: float | None
    current_notional_share_pct: float | None
    prior_resolved_episode_count: int
    prior_unique_token_count: int
    prior_same_token_episode_count: int
    prior_return_coverage_pct: float | None
    prior_positive_outcome_share_pct: float | None
    prior_mean_realized_return_pct: float | None
    prior_median_realized_return_pct: float | None
    prior_hold_coverage_pct: float | None
    prior_median_hold_seconds: float | None
    prior_market_first_episode_count: int
    prior_market_first_unique_token_count: int
    prior_market_first_same_token_episode_count: int
    prior_market_first_horizon_seconds: int | None
    prior_market_first_positive_outcome_share_pct: float | None
    prior_market_first_mean_executable_quote_return_pct: float | None
    prior_market_first_median_executable_quote_return_pct: float | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityWalletIntelligenceSnapshot:
    method_version: str
    episode_key: str
    token_mint: str
    as_of: int
    participant_wallet_count: int
    participants_with_resolved_history: int
    history_coverage_pct: float | None
    wallets_with_positive_prior_median: int
    wallets_with_negative_prior_median: int
    participants_with_market_first_history: int
    market_first_history_coverage_pct: float | None
    market_first_history_horizon_seconds: int | None
    wallets_with_positive_market_first_median: int
    wallets_with_negative_market_first_median: int
    repeated_participant_event_share_pct: float | None
    notional_coverage_pct: float | None
    wallets: tuple[WalletOpportunityEvidence, ...]
    data_quality_flags: tuple[str, ...]


def _validate_participation(item: OpportunityWalletParticipation) -> None:
    if not item.episode_key.strip():
        raise ValueError("episode_key cannot be empty")
    if not item.wallet_address.strip():
        raise ValueError("wallet_address cannot be empty")
    if not item.token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if item.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("observed_at cannot precede chain_time")
    if item.notional_usd is not None and (
        item.notional_usd < 0 or not math.isfinite(item.notional_usd)
    ):
        raise ValueError("notional_usd must be non-negative and finite")


def _validate_history(item: HistoricalWalletOutcome) -> None:
    if not item.episode_key.strip():
        raise ValueError("historical episode_key cannot be empty")
    if not item.wallet_address.strip():
        raise ValueError("historical wallet_address cannot be empty")
    if not item.token_mint.strip():
        raise ValueError("historical token_mint cannot be empty")
    if item.entry_observed_at < 0:
        raise ValueError("entry_observed_at must be non-negative")
    if item.outcome_observed_at is not None:
        if item.outcome_observed_at < item.entry_observed_at:
            raise ValueError("outcome_observed_at cannot precede entry_observed_at")
    if item.realized_return_pct is not None and not math.isfinite(item.realized_return_pct):
        raise ValueError("realized_return_pct must be finite")
    if item.hold_seconds is not None and item.hold_seconds < 0:
        raise ValueError("hold_seconds must be non-negative")


def _validate_market_first_association(item: HistoricalWalletOpportunityAssociation) -> None:
    if not item.episode_key.strip():
        raise ValueError("market-first historical episode_key cannot be empty")
    if not item.wallet_address.strip():
        raise ValueError("market-first historical wallet_address cannot be empty")
    if not item.token_mint.strip():
        raise ValueError("market-first historical token_mint cannot be empty")
    if item.prior_decision_as_of < 0 or item.outcome_observed_at < 0:
        raise ValueError("market-first historical clocks must be non-negative")
    if item.outcome_observed_at < item.prior_decision_as_of:
        raise ValueError("market-first outcome cannot precede its prior decision")
    if item.horizon_seconds <= 0:
        raise ValueError("market-first history horizon must be positive")
    if not math.isfinite(item.executable_quote_return_pct):
        raise ValueError("market-first executable_quote_return_pct must be finite")
    if not item.entry_quote_key.strip() or not item.exit_quote_key.strip():
        raise ValueError("market-first history requires entry and exit quote keys")
    if not item.method_version.strip():
        raise ValueError("market-first history method_version cannot be empty")


def _coverage(known: int, total: int) -> float | None:
    if total <= 0:
        return None
    return 100.0 * known / total


def build_opportunity_wallet_intelligence(
    *,
    episode_key: str,
    token_mint: str,
    as_of: int,
    participations: list[OpportunityWalletParticipation],
    historical_outcomes: list[HistoricalWalletOutcome],
    historical_opportunity_associations: tuple[HistoricalWalletOpportunityAssociation, ...]
    | list[HistoricalWalletOpportunityAssociation] = (),
) -> OpportunityWalletIntelligenceSnapshot:
    """Build descriptive wallet evidence for the wallets present in one market opportunity.

    This function intentionally has no whitelist, wallet score, ``passed``, recommendation or BUY
    decision. Wallet-owned historical outcomes and market-first opportunity associations stay as
    separate evidence families so an opportunity quote return can never masquerade as realized wallet
    PnL. Every historical label must already be observable by ``as_of``; future/unresolved evidence
    stays missing.
    """

    episode = str(episode_key).strip()
    mint = str(token_mint).strip()
    if not episode:
        raise ValueError("episode_key cannot be empty")
    if not mint:
        raise ValueError("token_mint cannot be empty")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")

    for item in participations:
        _validate_participation(item)
    for item in historical_outcomes:
        _validate_history(item)
    for item in historical_opportunity_associations:
        _validate_market_first_association(item)

    association_horizons = {
        item.horizon_seconds for item in historical_opportunity_associations
    }
    if len(association_horizons) > 1:
        raise ValueError(
            "market-first wallet history must use one predeclared horizon per snapshot"
        )
    association_horizon = next(iter(association_horizons), None)

    current = [
        item
        for item in participations
        if item.episode_key == episode
        and item.token_mint == mint
        and item.chain_time <= as_of
        and item.observed_at <= as_of
    ]
    current.sort(key=lambda item: (item.observed_at, item.chain_time, item.wallet_address))

    participants = sorted({item.wallet_address for item in current})
    known_notionals = [item for item in current if item.notional_usd is not None]
    notional_coverage = _coverage(len(known_notionals), len(current))
    notionals_complete = bool(current) and len(known_notionals) == len(current)
    total_current_notional = (
        sum(float(item.notional_usd) for item in current)
        if notionals_complete
        else None
    )

    wallet_rows: list[WalletOpportunityEvidence] = []
    for wallet in participants:
        wallet_current = [item for item in current if item.wallet_address == wallet]

        # Wallet-owned history: keep only outcomes that were genuinely known by this snapshot.
        resolved = [
            item
            for item in historical_outcomes
            if item.wallet_address == wallet
            and item.episode_key != episode
            and item.entry_observed_at <= as_of
            and item.outcome_observed_at is not None
            and item.outcome_observed_at <= as_of
        ]
        resolved.sort(key=lambda item: (int(item.outcome_observed_at or 0), item.episode_key))

        returns = [
            float(item.realized_return_pct)
            for item in resolved
            if item.realized_return_pct is not None
        ]
        holds = [
            int(item.hold_seconds)
            for item in resolved
            if item.hold_seconds is not None
        ]

        # Market-first history: association only. It says this wallet was present in a prior
        # opportunity whose official executable quote outcome was already known; it does not claim
        # the wallet itself realized that outcome.
        associated = [
            item
            for item in historical_opportunity_associations
            if item.wallet_address == wallet
            and item.episode_key != episode
            and item.prior_decision_as_of <= as_of
            and item.outcome_observed_at <= as_of
        ]
        associated.sort(key=lambda item: (item.outcome_observed_at, item.episode_key))
        associated_returns = [
            float(item.executable_quote_return_pct) for item in associated
        ]

        wallet_notional = (
            sum(float(item.notional_usd) for item in wallet_current)
            if notionals_complete
            else None
        )
        wallet_notional_share = (
            100.0 * wallet_notional / total_current_notional
            if wallet_notional is not None
            and total_current_notional is not None
            and total_current_notional > 0
            else None
        )

        quality: list[str] = []
        if not resolved:
            quality.append("no_resolved_prior_history")
        elif len(resolved) < 5:
            quality.append("small_resolved_history_sample")
        if resolved and len(returns) < len(resolved):
            quality.append("partial_prior_return_coverage")
        if resolved and len(holds) < len(resolved):
            quality.append("partial_prior_hold_coverage")
        if not associated:
            quality.append("no_resolved_market_first_history")
        elif len(associated) < 5:
            quality.append("small_market_first_history_sample")
        if not notionals_complete and wallet_current:
            quality.append("partial_current_notional_coverage")

        wallet_rows.append(
            WalletOpportunityEvidence(
                wallet_address=wallet,
                current_event_count=len(wallet_current),
                current_buy_count=sum(1 for item in wallet_current if item.side == "buy"),
                current_sell_count=sum(1 for item in wallet_current if item.side == "sell"),
                current_notional_usd=wallet_notional,
                current_notional_share_pct=wallet_notional_share,
                prior_resolved_episode_count=len(resolved),
                prior_unique_token_count=len({item.token_mint for item in resolved}),
                prior_same_token_episode_count=sum(1 for item in resolved if item.token_mint == mint),
                prior_return_coverage_pct=_coverage(len(returns), len(resolved)),
                prior_positive_outcome_share_pct=(
                    100.0 * sum(1 for value in returns if value > 0) / len(returns)
                    if returns
                    else None
                ),
                prior_mean_realized_return_pct=(
                    sum(returns) / len(returns) if returns else None
                ),
                prior_median_realized_return_pct=(median(returns) if returns else None),
                prior_hold_coverage_pct=_coverage(len(holds), len(resolved)),
                prior_median_hold_seconds=(median(holds) if holds else None),
                prior_market_first_episode_count=len(associated),
                prior_market_first_unique_token_count=len(
                    {item.token_mint for item in associated}
                ),
                prior_market_first_same_token_episode_count=sum(
                    1 for item in associated if item.token_mint == mint
                ),
                prior_market_first_horizon_seconds=(
                    associated[0].horizon_seconds if associated else None
                ),
                prior_market_first_positive_outcome_share_pct=(
                    100.0
                    * sum(1 for value in associated_returns if value > 0)
                    / len(associated_returns)
                    if associated_returns
                    else None
                ),
                prior_market_first_mean_executable_quote_return_pct=(
                    sum(associated_returns) / len(associated_returns)
                    if associated_returns
                    else None
                ),
                prior_market_first_median_executable_quote_return_pct=(
                    median(associated_returns) if associated_returns else None
                ),
                data_quality_flags=tuple(quality),
            )
        )

    with_history = [row for row in wallet_rows if row.prior_resolved_episode_count > 0]
    positive_median = sum(
        1
        for row in wallet_rows
        if row.prior_median_realized_return_pct is not None
        and row.prior_median_realized_return_pct > 0
    )
    negative_median = sum(
        1
        for row in wallet_rows
        if row.prior_median_realized_return_pct is not None
        and row.prior_median_realized_return_pct < 0
    )
    with_market_first_history = [
        row for row in wallet_rows if row.prior_market_first_episode_count > 0
    ]
    positive_market_first_median = sum(
        1
        for row in wallet_rows
        if row.prior_market_first_median_executable_quote_return_pct is not None
        and row.prior_market_first_median_executable_quote_return_pct > 0
    )
    negative_market_first_median = sum(
        1
        for row in wallet_rows
        if row.prior_market_first_median_executable_quote_return_pct is not None
        and row.prior_market_first_median_executable_quote_return_pct < 0
    )

    repeated_share = None
    if current:
        repeated_share = 100.0 * (len(current) - len(participants)) / len(current)

    quality: list[str] = []
    if not current:
        quality.append("no_causal_wallet_participation")
    if participants and len(with_history) < len(participants):
        quality.append("partial_resolved_wallet_history")
    if participants and not with_market_first_history:
        quality.append("no_valid_market_first_history_sample")
    elif participants and len(with_market_first_history) < len(participants):
        quality.append("partial_market_first_wallet_history")
    if current and not notionals_complete:
        quality.append("partial_current_notional_coverage")

    return OpportunityWalletIntelligenceSnapshot(
        method_version=OPPORTUNITY_WALLET_INTELLIGENCE_VERSION,
        episode_key=episode,
        token_mint=mint,
        as_of=as_of,
        participant_wallet_count=len(participants),
        participants_with_resolved_history=len(with_history),
        history_coverage_pct=_coverage(len(with_history), len(participants)),
        wallets_with_positive_prior_median=positive_median,
        wallets_with_negative_prior_median=negative_median,
        participants_with_market_first_history=len(with_market_first_history),
        market_first_history_coverage_pct=_coverage(
            len(with_market_first_history), len(participants)
        ),
        market_first_history_horizon_seconds=association_horizon,
        wallets_with_positive_market_first_median=positive_market_first_median,
        wallets_with_negative_market_first_median=negative_market_first_median,
        repeated_participant_event_share_pct=repeated_share,
        notional_coverage_pct=notional_coverage,
        wallets=tuple(wallet_rows),
        data_quality_flags=tuple(quality),
    )
