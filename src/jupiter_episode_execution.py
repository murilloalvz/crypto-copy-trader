from __future__ import annotations

from dataclasses import dataclass
import threading
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
from src.opportunity_provider_attempt_store import (
    OpportunityProviderAttempt,
    begin_provider_attempt,
    complete_provider_attempt,
    load_provider_attempt,
)
from src.solana import SolanaClient, SolanaRPCError


JUPITER_ENTRY_PROVIDER = "jupiter_swap_v2_order"
JUPITER_ENTRY_PURPOSE = "entry_executable_buy_v1"
USDC_DECIMALS = 6


@dataclass(frozen=True)
class JupiterEpisodeQuoteConfig:
    api_key: str
    taker_public_key: str
    rpc_url: str
    rpc_fallback_urls: tuple[str, ...] = ()
    rpc_timeout_seconds: int = 3
    jupiter_timeout_seconds: int = 5
    notional_usd: float = 25.0
    slippage_bps: int = 100


@dataclass(frozen=True)
class TokenDecimalsObservation:
    token_mint: str
    decimals: int
    observed_at: int
    source: str = "solana_getTokenSupply"


@dataclass(frozen=True)
class JupiterEpisodeQuoteResult:
    attempt: OpportunityProviderAttempt
    quote: CausalQuoteObservation | None
    reused_attempt: bool


class JupiterEpisodeQuoteProbe:
    """Capture one read-only Jupiter entry route for one newly admitted market episode.

    The probe is intentionally at-most-once per (run, episode, provider, purpose). STARTED is
    persisted before any RPC/provider I/O, so replay/restart cannot silently duplicate calls.
    Missing config and provider/metadata failures are first-class evidence, never converted into
    synthetic prices. Supplying a taker public key only asks Jupiter to assemble a candidate
    transaction; this class has no signing or execute method.
    """

    def __init__(self, config: JupiterEpisodeQuoteConfig):
        if config.rpc_timeout_seconds <= 0 or config.jupiter_timeout_seconds <= 0:
            raise ValueError("provider timeouts must be positive")
        if config.notional_usd <= 0:
            raise ValueError("notional_usd must be positive")
        if not 0 <= config.slippage_bps <= 10_000:
            raise ValueError("slippage_bps must be between 0 and 10000")
        self.config = config
        self._decimals_cache: dict[str, TokenDecimalsObservation] = {}
        self._decimals_lock = threading.Lock()

    @staticmethod
    def attempt_key(episode: MarketOpportunityEpisode) -> str:
        return (
            f"provider:{JUPITER_ENTRY_PROVIDER}:{JUPITER_ENTRY_PURPOSE}:"
            f"{episode.acquisition_run_key}:{episode.episode_key}"
        )

    @staticmethod
    def quote_key(episode: MarketOpportunityEpisode) -> str:
        return (
            f"episode-quote:{JUPITER_ENTRY_PROVIDER}:{JUPITER_ENTRY_PURPOSE}:"
            f"{episode.acquisition_run_key}:{episode.episode_key}"
        )

    def _existing_result(self, episode: MarketOpportunityEpisode) -> JupiterEpisodeQuoteResult:
        attempt = load_provider_attempt(attempt_key=self.attempt_key(episode))
        if attempt is None:
            raise RuntimeError("provider attempt disappeared after idempotent begin")
        quote = None
        if attempt.artifact_key:
            rows = load_causal_quotes(quote_keys=(attempt.artifact_key,))
            quote = rows[0] if rows else None
        return JupiterEpisodeQuoteResult(attempt=attempt, quote=quote, reused_attempt=True)

    def _complete(
        self,
        episode: MarketOpportunityEpisode,
        *,
        started_at: int,
        status: str,
        artifact_key: str | None = None,
        error: BaseException | None = None,
        details: dict | None = None,
        completed_floor: int | None = None,
    ) -> OpportunityProviderAttempt:
        completed_at = max(
            started_at,
            int(time.time()),
            int(completed_floor) if completed_floor is not None else started_at,
        )
        return complete_provider_attempt(
            attempt_key=self.attempt_key(episode),
            status=status,
            completed_at=completed_at,
            artifact_key=artifact_key,
            error_type=(type(error).__name__ if error is not None else None),
            error_message=(str(error) if error is not None else None),
            details=details or {},
        )

    def _resolve_token_decimals(self, token_mint: str) -> TokenDecimalsObservation:
        mint = token_mint.strip()
        if not mint:
            raise ValueError("token_mint cannot be empty")
        with self._decimals_lock:
            cached = self._decimals_cache.get(mint)
        if cached is not None:
            return cached

        client = SolanaClient(
            rpc_url=self.config.rpc_url,
            timeout=self.config.rpc_timeout_seconds,
            fallback_urls=self.config.rpc_fallback_urls,
        )
        result = client.call(
            "getTokenSupply",
            [mint, {"commitment": "confirmed"}],
            max_attempts=1,
        )
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict) or value.get("decimals") is None:
            raise SolanaRPCError("getTokenSupply did not return token decimals")
        try:
            decimals = int(value["decimals"])
        except (TypeError, ValueError) as exc:
            raise SolanaRPCError("getTokenSupply returned invalid token decimals") from exc
        if not 0 <= decimals <= 18:
            raise SolanaRPCError("token decimals outside supported range")

        observation = TokenDecimalsObservation(
            token_mint=mint,
            decimals=decimals,
            observed_at=int(time.time()),
        )
        with self._decimals_lock:
            existing = self._decimals_cache.setdefault(mint, observation)
        return existing

    def capture(self, episode: MarketOpportunityEpisode) -> JupiterEpisodeQuoteResult:
        if not episode.episode_key.strip() or not episode.token_mint.strip():
            raise ValueError("episode identity is incomplete")
        started_at = max(int(time.time()), int(episode.first_trigger_observed_at))
        is_new = begin_provider_attempt(
            attempt_key=self.attempt_key(episode),
            acquisition_run_key=episode.acquisition_run_key,
            episode_key=episode.episode_key,
            provider=JUPITER_ENTRY_PROVIDER,
            purpose=JUPITER_ENTRY_PURPOSE,
            started_at=started_at,
        )
        if not is_new:
            return self._existing_result(episode)

        missing = []
        api_key = self.config.api_key.strip()
        taker = self.config.taker_public_key.strip()
        if not api_key:
            missing.append("JUPITER_API_KEY")
        if not taker:
            missing.append("JUPITER_TAKER_PUBLIC_KEY")
        if missing:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="CONFIG_MISSING",
                details={"missing": missing},
            )
            return JupiterEpisodeQuoteResult(attempt=attempt, quote=None, reused_attempt=False)

        try:
            decimals = self._resolve_token_decimals(episode.token_mint)
        except (SolanaRPCError, ValueError, TypeError, KeyError) as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="METADATA_ERROR",
                error=exc,
            )
            return JupiterEpisodeQuoteResult(attempt=attempt, quote=None, reused_attempt=False)

        amount_raw = int(round(self.config.notional_usd * (10**USDC_DECIMALS)))
        if amount_raw <= 0:
            raise ValueError("notional_usd rounds to a zero USDC amount")

        try:
            order = JupiterSwapV2Client(
                api_key=api_key,
                timeout=self.config.jupiter_timeout_seconds,
            ).order(
                input_mint=USDC_MINT,
                output_mint=episode.token_mint,
                amount_raw=amount_raw,
                taker=taker,
                slippage_bps=self.config.slippage_bps,
            )
        except JupiterOrderError as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="PROVIDER_ERROR",
                error=exc,
                details={
                    "notional_usd": self.config.notional_usd,
                    "slippage_bps": self.config.slippage_bps,
                    "token_decimals": decimals.decimals,
                    "metadata_observed_at": decimals.observed_at,
                },
            )
            return JupiterEpisodeQuoteResult(attempt=attempt, quote=None, reused_attempt=False)

        try:
            quote = jupiter_order_to_causal_quote(
                order,
                token_mint=episode.token_mint,
                side="buy",
                token_decimals=decimals.decimals,
            )
            if quote.observed_at < episode.first_trigger_observed_at:
                raise ValueError("Jupiter quote cannot precede episode admission clock")
        except (JupiterOrderError, ValueError, TypeError) as exc:
            attempt = self._complete(
                episode,
                started_at=started_at,
                status="NORMALIZATION_ERROR",
                error=exc,
                details={
                    "token_decimals": decimals.decimals,
                    "metadata_observed_at": decimals.observed_at,
                },
                completed_floor=order.observed_at,
            )
            return JupiterEpisodeQuoteResult(attempt=attempt, quote=None, reused_attempt=False)

        artifact_key = self.quote_key(episode)
        record_causal_quote(quote, quote_key=artifact_key)
        status = "AVAILABLE" if quote.executable else "UNAVAILABLE"
        attempt = self._complete(
            episode,
            started_at=started_at,
            status=status,
            artifact_key=artifact_key,
            details={
                "notional_usd": self.config.notional_usd,
                "slippage_bps": self.config.slippage_bps,
                "token_decimals": decimals.decimals,
                "metadata_observed_at": decimals.observed_at,
                "quote_observed_at": quote.observed_at,
                "assembled_transaction_present": quote.executable,
                "route_id": quote.route_id,
                "router": quote.provider_router,
            },
            completed_floor=quote.observed_at,
        )
        return JupiterEpisodeQuoteResult(attempt=attempt, quote=quote, reused_attempt=False)
