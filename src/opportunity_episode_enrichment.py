from dataclasses import dataclass

from src.causal_quotes import CausalQuoteObservation
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_onchain_hazard import OnchainMintHazardEvidence
from src.opportunity_snapshot_core import (
    FlowTradeObservation,
    OpportunitySnapshotCoreV1,
    build_opportunity_snapshot_core_v1,
)
from src.opportunity_token_hazard import TokenHazardEvidence
from src.opportunity_wallet_intelligence import (
    HistoricalWalletOpportunityAssociation,
    HistoricalWalletOutcome,
    OpportunityWalletIntelligenceSnapshot,
    OpportunityWalletParticipation,
    build_opportunity_wallet_intelligence,
)


EPISODE_ENRICHMENT_VERSION = "episode_enrichment_v1_1_market_first_wallet_history"
HazardEvidence = TokenHazardEvidence | OnchainMintHazardEvidence


@dataclass(frozen=True)
class RiskEvidenceEnvelope:
    """Causal token-hazard evidence with explicit provider missingness.

    Provider-native fields remain separate. In particular, Solana RPC
    ``top10_token_account_concentration_pct`` is never relabeled as holder concentration and is not
    written into the Solana Tracker ``top10_pct`` field.
    """

    status: str
    data_quality_flags: tuple[str, ...]
    provider: str | None = None
    observed_at: int | None = None

    # Solana Tracker provider-native evidence. These are not synthesized by the RPC provider.
    risk_score: float | None = None
    rugged: bool | None = None
    jupiter_verified: bool | None = None
    top10_pct: float | None = None
    dev_pct: float | None = None
    snipers_pct: float | None = None
    bundlers_pct: float | None = None
    insiders_pct: float | None = None
    risk_factors: tuple[tuple[str, str, float | None], ...] = ()

    # Shared / on-chain evidence.
    freeze_authority_present: bool | None = None
    mint_authority_present: bool | None = None
    token_program: str | None = None
    token_2022: bool | None = None
    extensions_present: tuple[str, ...] = ()
    mint_context_slot: int | None = None
    top10_token_account_concentration_pct: float | None = None
    largest_token_accounts_observed: int | None = None
    largest_accounts_context_slot: int | None = None


@dataclass(frozen=True)
class EpisodeEnrichmentBundle:
    method_version: str
    episode_key: str
    token_mint: str
    as_of: int
    core: OpportunitySnapshotCoreV1
    wallet_intelligence: OpportunityWalletIntelligenceSnapshot
    risk: RiskEvidenceEnvelope


def _risk_envelope(
    *,
    episode: MarketOpportunityEpisode,
    as_of: int,
    hazard_evidence: HazardEvidence | None,
) -> RiskEvidenceEnvelope:
    if hazard_evidence is None:
        return RiskEvidenceEnvelope(
            status="not_integrated",
            data_quality_flags=("token_hazard_provider_not_integrated",),
        )
    if hazard_evidence.episode_key != episode.episode_key:
        raise ValueError("hazard evidence episode does not match enrichment episode")
    if hazard_evidence.token_mint and hazard_evidence.token_mint != episode.token_mint:
        raise ValueError("hazard evidence token does not match enrichment episode")
    if hazard_evidence.observed_at is not None and hazard_evidence.observed_at > as_of:
        return RiskEvidenceEnvelope(
            status="not_observed_as_of",
            provider=hazard_evidence.provider,
            observed_at=None,
            data_quality_flags=("token_hazard_observed_after_as_of",),
        )

    flags = list(hazard_evidence.data_quality_flags)
    if hazard_evidence.observed_at is None:
        flags.append("token_hazard_observed_at_missing")

    if isinstance(hazard_evidence, OnchainMintHazardEvidence):
        return RiskEvidenceEnvelope(
            status=hazard_evidence.status,
            provider=hazard_evidence.provider,
            observed_at=hazard_evidence.observed_at,
            freeze_authority_present=hazard_evidence.freeze_authority_present,
            mint_authority_present=hazard_evidence.mint_authority_present,
            token_program=hazard_evidence.token_program,
            token_2022=hazard_evidence.token_2022,
            extensions_present=hazard_evidence.extensions_present,
            mint_context_slot=hazard_evidence.context_slot,
            top10_token_account_concentration_pct=(
                hazard_evidence.top10_token_account_concentration_pct
            ),
            largest_token_accounts_observed=hazard_evidence.largest_token_accounts_observed,
            largest_accounts_context_slot=hazard_evidence.largest_accounts_context_slot,
            data_quality_flags=tuple(flags),
        )

    return RiskEvidenceEnvelope(
        status=hazard_evidence.status,
        provider=hazard_evidence.provider,
        observed_at=hazard_evidence.observed_at,
        risk_score=hazard_evidence.risk_score,
        rugged=hazard_evidence.rugged,
        jupiter_verified=hazard_evidence.jupiter_verified,
        top10_pct=hazard_evidence.top10_pct,
        dev_pct=hazard_evidence.dev_pct,
        snipers_pct=hazard_evidence.snipers_pct,
        bundlers_pct=hazard_evidence.bundlers_pct,
        insiders_pct=hazard_evidence.insiders_pct,
        freeze_authority_present=hazard_evidence.freeze_authority_present,
        mint_authority_present=hazard_evidence.mint_authority_present,
        risk_factors=hazard_evidence.risk_factors,
        data_quality_flags=tuple(flags),
    )


def build_episode_enrichment_bundle(
    *,
    episode: MarketOpportunityEpisode,
    as_of: int,
    quotes: tuple[CausalQuoteObservation, ...] | list[CausalQuoteObservation] = (),
    historical_wallet_outcomes: tuple[HistoricalWalletOutcome, ...]
    | list[HistoricalWalletOutcome] = (),
    historical_wallet_opportunity_associations: tuple[
        HistoricalWalletOpportunityAssociation, ...
    ]
    | list[HistoricalWalletOpportunityAssociation] = (),
    hazard_evidence: HazardEvidence | None = None,
) -> EpisodeEnrichmentBundle:
    """Build the minimal causal evidence bundle for one already-open market episode.

    This function performs no network I/O and creates no BUY/SELL recommendation. It combines
    shared Pump/PumpSwap market observations, optional causal execution quotes, wallet evidence and
    optional persisted token-hazard evidence. Wallet-owned PnL history and market-first opportunity
    associations remain separate; callers must prefilter market-first associations with the strict
    pre-T0 loader. Later evidence is never backfilled into an earlier ``as_of`` bundle.
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
        historical_opportunity_associations=list(
            historical_wallet_opportunity_associations
        ),
    )

    risk = _risk_envelope(
        episode=episode,
        as_of=as_of,
        hazard_evidence=hazard_evidence,
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
