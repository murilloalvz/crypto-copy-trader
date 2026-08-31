from dataclasses import dataclass

from src.social_features import SocialBurstFeatures, build_social_burst_features
from src.social_intelligence import SocialEvent


@dataclass(frozen=True)
class WaveOpportunityEvidence:
    signal_id: int
    token_mint: str
    detected_at: int
    wave_score: float
    strategy_version: str


@dataclass(frozen=True)
class WalletActionObservation:
    address: str
    token_mint: str
    side: str
    chain_time: int
    observed_at: int


@dataclass(frozen=True)
class WalletOpportunityContext:
    observed_action_count: int
    buy_action_count: int
    sell_action_count: int
    unique_buy_wallet_count: int
    unique_sell_wallet_count: int
    latest_buy_observed_at: int | None
    latest_sell_observed_at: int | None


@dataclass(frozen=True)
class OpportunityContextSnapshot:
    token_mint: str
    as_of: int
    wave: WaveOpportunityEvidence | None
    wallets: WalletOpportunityContext
    social: SocialBurstFeatures | None
    available_channels: tuple[str, ...]


def _validate_wallet_observation(item: WalletActionObservation) -> None:
    if not item.address.strip():
        raise ValueError("wallet address cannot be empty")
    if not item.token_mint.strip():
        raise ValueError("wallet token_mint cannot be empty")
    if item.side not in {"buy", "sell"}:
        raise ValueError("wallet side must be buy or sell")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("wallet timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("wallet observed_at cannot be earlier than chain_time")


def build_wallet_opportunity_context(
    observations: list[WalletActionObservation] | tuple[WalletActionObservation, ...],
    *,
    token_mint: str,
    as_of: int,
) -> WalletOpportunityContext:
    if as_of < 0:
        raise ValueError("as_of must be non-negative")

    eligible: list[WalletActionObservation] = []
    for item in observations:
        _validate_wallet_observation(item)
        if item.token_mint != token_mint or item.observed_at > as_of:
            continue
        eligible.append(item)

    buys = [item for item in eligible if item.side == "buy"]
    sells = [item for item in eligible if item.side == "sell"]
    return WalletOpportunityContext(
        observed_action_count=len(eligible),
        buy_action_count=len(buys),
        sell_action_count=len(sells),
        unique_buy_wallet_count=len({item.address for item in buys}),
        unique_sell_wallet_count=len({item.address for item in sells}),
        latest_buy_observed_at=max((item.observed_at for item in buys), default=None),
        latest_sell_observed_at=max((item.observed_at for item in sells), default=None),
    )


def build_opportunity_context(
    *,
    token_mint: str,
    as_of: int,
    wave: WaveOpportunityEvidence | None = None,
    wallet_observations: list[WalletActionObservation]
    | tuple[WalletActionObservation, ...] = (),
    social_events: list[SocialEvent] | tuple[SocialEvent, ...] = (),
    include_social: bool = True,
) -> OpportunityContextSnapshot:
    """Join independent evidence channels without assigning a trading score.

    Every channel is constrained by what was observable at ``as_of``. Historical chain data
    synchronized later must not be represented as if it had been observed live; callers need
    a real ``observed_at`` for wallet actions. The returned snapshot is research context only,
    not a buy/sell decision.
    """
    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")

    eligible_wave = None
    if wave is not None:
        if wave.token_mint != token_mint:
            raise ValueError("wave token does not match opportunity token")
        if wave.detected_at < 0:
            raise ValueError("wave detected_at must be non-negative")
        if wave.detected_at <= as_of:
            eligible_wave = wave

    wallet_context = build_wallet_opportunity_context(
        wallet_observations,
        token_mint=token_mint,
        as_of=as_of,
    )

    social = None
    if include_social:
        social = build_social_burst_features(
            social_events,
            as_of=as_of,
            token_mint=token_mint,
        )

    channels: list[str] = []
    if eligible_wave is not None:
        channels.append("wave")
    if wallet_context.observed_action_count:
        channels.append("wallets")
    if social is not None and (
        social.current_event_count or social.prior_baseline_event_count
    ):
        channels.append("social")

    return OpportunityContextSnapshot(
        token_mint=token_mint,
        as_of=as_of,
        wave=eligible_wave,
        wallets=wallet_context,
        social=social,
        available_channels=tuple(channels),
    )
