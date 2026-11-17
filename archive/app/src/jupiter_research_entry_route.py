from __future__ import annotations

from dataclasses import dataclass
import time

from src.assets import USDC_MINT
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_onchain_hazard import ONCHAIN_HAZARD_PROVIDER, ONCHAIN_HAZARD_PURPOSE
from src.opportunity_provider_attempt_store import (
    FINAL_PROVIDER_STATUSES,
    OpportunityProviderAttempt,
    begin_provider_attempt,
    complete_provider_attempt,
    load_provider_attempt,
)


JUPITER_RESEARCH_ENTRY_PROVIDER = "jupiter_swap_v2_order"
JUPITER_RESEARCH_ENTRY_PURPOSE = "entry_route_only_research_v1"
USDC_DECIMALS = 6


@dataclass(frozen=True)
class JupiterResearchEntryRouteConfig:
    api_key: str
    timeout_seconds: int = 5
    notional_usd: float = 25.0
    slippage_bps: int = 100


@dataclass(frozen=True)
class JupiterResearchEntryRouteResult:
    attempt: OpportunityProviderAttempt
    quote: CausalQuoteObservation | None
    reused_attempt: bool


class JupiterResearchEntryRouteProbe:
    """Capture a causal BUY route without a taker for research-only forward cohorts.

    The route uses the on-chain hazard Mint snapshot as the already-observed token-decimals source,
    avoiding a duplicate metadata RPC. A successful quote MUST remain non-executable. This probe
    never freezes the official market episode ``decision_as_of`` and never signs or submits.
    """

    def __init__(self, config: JupiterResearchEntryRouteConfig):
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if config.notional_usd <= 0:
            raise ValueError("notional_usd must be positive")
        if not 0 <= config.slippage_bps <= 10_000:
            raise ValueError("slippage_bps must be between 0 and 10000")
        self.config = config

    @staticmethod
    def attempt_key(episode: MarketOpportunityEpisode) -> str:
        return (
            f"provider:{JUPITER_RESEARCH_ENTRY_PROVIDER}:{JUPITER_RESEARCH_ENTRY_PURPOSE}:"
            f"{episode.acquisition_run_key}:{episode.episode_key}"
        )

    @staticmethod
    def quote_key(episode: MarketOpportunityEpisode) -> str:
        return (
            f"research-entry-route:{JUPITER_RESEARCH_ENTRY_PROVIDER}:"
            f"{episode.acquisition_run_key}:{episode.episode_key}"
        )

    def _existing(self, episode: MarketOpportunityEpisode) -> JupiterResearchEntryRouteResult:
        attempt = load_provider_attempt(attempt_key=self.attempt_key(episode))
        if attempt is None:
            raise RuntimeError("research entry attempt disappeared after idempotent begin")
        quote = None
        if attempt.artifact_key:
            rows = load_causal_quotes(quote_keys=(attempt.artifact_key,))
            quote = rows[0] if rows else None
        return JupiterResearchEntryRouteResult(attempt=attempt, quote=quote, reused_attempt=True)

    @staticmethod
    def _hazard_decimals(
        episode: MarketOpportunityEpisode,
        hazard_attempt: OpportunityProviderAttempt,
    ) -> tuple[int, int]:
        if hazard_attempt.episode_key != episode.episode_key:
            raise ValueError("hazard attempt episode does not match research entry episode")
        if (hazard_attempt.provider, hazard_attempt.purpose) != (
            ONCHAIN_HAZARD_PROVIDER,
            ONCHAIN_HAZARD_PURPOSE,
        ):
            raise ValueError("research entry requires the frozen on-chain hazard provider")
        if hazard_attempt.status not in FINAL_PROVIDER_STATUSES:
            raise ValueError("hazard attempt is not terminal")
        if hazard_attempt.status != "AVAILABLE":
            raise ValueError("research entry requires AVAILABLE on-chain Mint evidence")
        if hazard_attempt.completed_at is None:
            raise ValueError("hazard attempt completion clock is missing")
        details = hazard_attempt.details or {}
        if str(details.get("token_mint") or "") != episode.token_mint:
            raise ValueError("hazard Mint identity does not match episode token")
        try:
            decimals = int(details["decimals"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("hazard evidence lacks token decimals") from exc
        if not 0 <= decimals <= 18:
            raise ValueError("hazard token decimals are invalid")
        return decimals, int(hazard_attempt.completed_at)

    def capture(
        self,
        episode: MarketOpportunityEpisode,
        *,
        hazard_attempt: OpportunityProviderAttempt,
    ) -> JupiterResearchEntryRouteResult:
        decimals, hazard_completed_at = self._hazard_decimals(episode, hazard_attempt)
        started_at = max(int(time.time()), episode.first_trigger_observed_at, hazard_completed_at)
        is_new = begin_provider_attempt(
            attempt_key=self.attempt_key(episode),
            acquisition_run_key=episode.acquisition_run_key,
            episode_key=episode.episode_key,
            provider=JUPITER_RESEARCH_ENTRY_PROVIDER,
            purpose=JUPITER_RESEARCH_ENTRY_PURPOSE,
            started_at=started_at,
        )
        if not is_new:
            return self._existing(episode)

        api_key = self.config.api_key.strip()
        if not api_key:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(episode),
                status="CONFIG_MISSING",
                completed_at=max(started_at, int(time.time())),
                details={
                    "missing": ["JUPITER_API_KEY"],
                    "route_only": True,
                    "official_decision_frozen": False,
                    "hazard_attempt_key": hazard_attempt.attempt_key,
                },
            )
            return JupiterResearchEntryRouteResult(attempt, None, False)

        amount_raw = int(round(self.config.notional_usd * (10**USDC_DECIMALS)))
        if amount_raw <= 0:
            raise ValueError("notional_usd rounds to zero USDC amount")

        try:
            order = JupiterSwapV2Client(
                api_key=api_key,
                timeout=self.config.timeout_seconds,
            ).order(
                input_mint=USDC_MINT,
                output_mint=episode.token_mint,
                amount_raw=amount_raw,
                taker=None,
                slippage_bps=self.config.slippage_bps,
            )
        except JupiterOrderError as exc:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(episode),
                status="PROVIDER_ERROR",
                completed_at=max(started_at, int(time.time())),
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={
                    "route_only": True,
                    "official_decision_frozen": False,
                    "hazard_attempt_key": hazard_attempt.attempt_key,
                    "notional_usd": self.config.notional_usd,
                    "slippage_bps": self.config.slippage_bps,
                    "token_decimals": decimals,
                },
            )
            return JupiterResearchEntryRouteResult(attempt, None, False)

        try:
            if order.has_assembled_transaction:
                raise ValueError("research route-only BUY unexpectedly returned assembled transaction")
            quote = jupiter_order_to_causal_quote(
                order,
                token_mint=episode.token_mint,
                side="buy",
                token_decimals=decimals,
            )
            if quote.executable:
                raise ValueError("research entry route-only quote must be non-executable")
            if quote.observed_at < hazard_completed_at:
                raise ValueError("research entry quote cannot precede required hazard evidence")
        except (JupiterOrderError, ValueError, TypeError) as exc:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(episode),
                status="NORMALIZATION_ERROR",
                completed_at=max(started_at, int(time.time()), order.observed_at),
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={
                    "route_only": True,
                    "official_decision_frozen": False,
                    "hazard_attempt_key": hazard_attempt.attempt_key,
                    "token_decimals": decimals,
                    "provider_error_code": order.error_code,
                    "provider_error_message": order.error_message,
                },
            )
            return JupiterResearchEntryRouteResult(attempt, None, False)

        artifact_key = self.quote_key(episode)
        record_causal_quote(quote, quote_key=artifact_key)
        attempt = complete_provider_attempt(
            attempt_key=self.attempt_key(episode),
            status="AVAILABLE",
            completed_at=max(started_at, int(time.time()), quote.observed_at),
            artifact_key=artifact_key,
            details={
                "route_only": True,
                "official_decision_frozen": False,
                "taker_supplied": False,
                "assembled_transaction_present": False,
                "hazard_attempt_key": hazard_attempt.attempt_key,
                "hazard_completed_at": hazard_completed_at,
                "notional_usd": self.config.notional_usd,
                "slippage_bps": self.config.slippage_bps,
                "token_decimals": decimals,
                "quote_observed_at": quote.observed_at,
                "route_id": quote.route_id,
                "router": quote.provider_router,
            },
        )
        return JupiterResearchEntryRouteResult(attempt, quote, False)
