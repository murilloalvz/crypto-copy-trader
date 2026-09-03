from dataclasses import dataclass

from src.causal_quotes import CausalQuoteObservation
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_snapshot_core import (
    FlowTradeObservation,
    OpportunitySnapshotCoreV1,
    build_opportunity_snapshot_core_v1,
)
from src.opportunity_wallet_intelligence import (
    HistoricalWalletOutcome,
    OpportunityWalletIntelligenceSnapshot,
    OpportunityWalletParticipation,
    build_opportunity_wallet_intelligence,
)


EPISODE_ENRICHMENT_VERSION = "episode_enrichment_v1_minimal"


@dataclass(frozen=True)
class RiskEvidenceEnvelope:
    """Explicit placeholder until a causal token-hazard provider is wired live.

    Flow concentration belongs to the Core and wallet snapshot; it must not be mislabeled as a
    rug/manipulation probability. The E2E pipeline therefore carries risk missingness explicitly
    rather than inventing a score from incomplete data.
    """

    status: str
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class EpisodeEnrichmentBundle:
    method_version: str
    episode_key: str
    token_mint: str
    as_of: int
    core: OpportunitySnapshotCoreV1
    wallet_intelligence: OpportunityWalletIntelligenceSnapshot
    risk: RiskEvidenceEnvelope


def build_episode_enrichment_bundle(
    *,
    episode: MarketOpportunityEpisode,
    as_of: int,
    quotes: tuple[CausalQuoteObservation, ...] | list[CausalQuoteObservation] = (),
    historical_wallet_outcomes: tuple[HistoricalWalletOutcome, ...]
    | list[HistoricalWalletOutcome] = (),
) -> EpisodeEnrichmentBundle:
    """Build the minimal causal evidence bundle for one already-open market episode.

    This function performs no network I/O and creates no BUY/SELL recommendation. It combines
    the shared Pump/PumpSwap market store with optional causal execution quotes and already-known
    wallet outcomes. Token hazard remains explicitly unavailable until its live provider is wired.
    """

    if as_of < episode.first_trigger_observed_at:
        raise ValueError("enrichment as_of cannot precede episode trigger observation")

    lower = max(0, as_of - 300)
    stored = load_market_trades(
        acquisition_run_key=episode.acquisition_run_key,
        token_mint=episode.token_mint,
        as_of=as_of,
        chain_time_after=lower,
    )
    flow = tuple(
        FlowTradeObservation(
            token_mint=item.observation.token_mint,
            side=item.observation.side,
            chain_time=item.observation.chain_time,
            observed_at=item.observation.observed_at,
            wallet_address=item.observation.wallet_address,
            notional_usd=item.observation.notional_usd,
            price_usd=item.observation.price_usd,
        )
        for item in stored
    )

    core = build_opportunity_snapshot_core_v1(
        token_mint=episode.token_mint,
        as_of=as_of,
        flow_observations=flow,
        quotes=quotes,
    )

    fast_lower = as_of - 30
    participations = [
        OpportunityWalletParticipation(
            episode_key=episode.episode_key,
            wallet_address=item.observation.wallet_address,
            token_mint=episode.token_mint,
            side=item.observation.side,
            chain_time=item.observation.chain_time,
            observed_at=item.observation.observed_at,
            notional_usd=item.observation.notional_usd,
        )
        for item in stored
        if item.observation.wallet_address is not None
        and fast_lower < item.observation.chain_time <= as_of
        and item.observation.observed_at <= as_of
    ]
    wallets = build_opportunity_wallet_intelligence(
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        as_of=as_of,
        participations=participations,
        historical_outcomes=list(historical_wallet_outcomes),
    )

    risk = RiskEvidenceEnvelope(
        status="not_integrated",
        data_quality_flags=("token_hazard_provider_not_integrated",),
    )
    return EpisodeEnrichmentBundle(
        method_version=EPISODE_ENRICHMENT_VERSION,
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        as_of=as_of,
        core=core,
        wallet_intelligence=wallets,
        risk=risk,
    )
