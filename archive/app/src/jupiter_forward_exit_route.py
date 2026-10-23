from __future__ import annotations

from dataclasses import dataclass
import time

from src.assets import USDC_MINT
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.jupiter_episode_execution import JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)
from src.opportunity_forward_outcome_store import OpportunityForwardOutcome
from src.opportunity_provider_attempt_store import (
    OpportunityProviderAttempt,
    begin_provider_attempt,
    complete_provider_attempt,
    list_provider_attempts,
    load_provider_attempt,
)


JUPITER_FORWARD_ROUTE_PROVIDER = "jupiter_swap_v2_order"
JUPITER_FORWARD_ROUTE_PURPOSE_PREFIX = "forward_exit_route_only"


@dataclass(frozen=True)
class JupiterForwardExitRouteConfig:
    api_key: str
    timeout_seconds: int = 5
    slippage_bps: int = 100


@dataclass(frozen=True)
class JupiterForwardExitRouteResult:
    attempt: OpportunityProviderAttempt
    quote: CausalQuoteObservation | None
    reused_attempt: bool


@dataclass(frozen=True)
class _EntryLineage:
    attempt: OpportunityProviderAttempt
    quote: CausalQuoteObservation
    token_decimals: int
    amount_raw: int


def forward_route_purpose(horizon_seconds: int) -> str:
    horizon = int(horizon_seconds)
    if horizon <= 0:
        raise ValueError("horizon_seconds must be positive")
    return f"{JUPITER_FORWARD_ROUTE_PURPOSE_PREFIX}_{horizon}s_v1"


class JupiterForwardExitRouteProbe:
    """Capture one causal route-only SELL observation at an exact forward target.

    This probe is deliberately *not* the official executable forward-outcome collector. It calls
    Jupiter ``/order`` without a taker, so it can study route availability without pretending that
    the paper wallet owns tokens it never actually bought. A successful artifact must therefore be
    non-executable and never completes ``opportunity_forward_outcomes`` as AVAILABLE.

    The amount sold is the exact raw token amount from the prior executable BUY quote. This keeps
    quote-to-quote research sizing internally consistent while preserving the distinction between a
    candidate route and a landed/fill position.
    """

    def __init__(self, config: JupiterForwardExitRouteConfig):
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= config.slippage_bps <= 10_000:
            raise ValueError("slippage_bps must be between 0 and 10000")
        self.config = config

    @staticmethod
    def attempt_key(outcome: OpportunityForwardOutcome) -> str:
        return (
            f"provider:{JUPITER_FORWARD_ROUTE_PROVIDER}:"
            f"{forward_route_purpose(outcome.horizon_seconds)}:"
            f"{outcome.acquisition_run_key}:{outcome.episode_key}"
        )

    @staticmethod
    def quote_key(outcome: OpportunityForwardOutcome) -> str:
        return (
            f"forward-route-quote:{JUPITER_FORWARD_ROUTE_PROVIDER}:"
            f"{outcome.acquisition_run_key}:{outcome.episode_key}:"
            f"{outcome.horizon_seconds}s"
        )

    def _existing_result(self, outcome: OpportunityForwardOutcome) -> JupiterForwardExitRouteResult:
        attempt = load_provider_attempt(attempt_key=self.attempt_key(outcome))
        if attempt is None:
            raise RuntimeError("forward route attempt disappeared after idempotent begin")
        quote = None
        if attempt.artifact_key:
            rows = load_causal_quotes(quote_keys=(attempt.artifact_key,))
            quote = rows[0] if rows else None
        return JupiterForwardExitRouteResult(attempt=attempt, quote=quote, reused_attempt=True)

    @staticmethod
    def _load_entry_lineage(outcome: OpportunityForwardOutcome) -> _EntryLineage:
        attempts = list_provider_attempts(
            acquisition_run_key=outcome.acquisition_run_key,
            provider=JUPITER_ENTRY_PROVIDER,
            purpose=JUPITER_ENTRY_PURPOSE,
        )
        matching = [item for item in attempts if item.episode_key == outcome.episode_key]
        if len(matching) != 1:
            raise ValueError("official entry provider lineage is missing or ambiguous")
        attempt = matching[0]
        if attempt.status != "AVAILABLE":
            raise ValueError("official entry provider attempt is not AVAILABLE")
        if attempt.completed_at is None or attempt.completed_at > outcome.decision_as_of:
            raise ValueError("official entry provider result was not known by decision_as_of")
        if not bool(attempt.details.get("assembled_transaction_present")):
            raise ValueError("official entry lineage lacks assembled transaction evidence")
        artifact_key = str(attempt.artifact_key or "").strip()
        if not artifact_key:
            raise ValueError("official entry quote artifact is missing")
        rows = load_causal_quotes(quote_keys=(artifact_key,))
        if len(rows) != 1:
            raise ValueError("official entry quote artifact is missing or ambiguous")
        quote = rows[0]
        if (
            not quote.executable
            or quote.side != "buy"
            or quote.token_mint != outcome.token_mint
            or quote.observed_at > outcome.decision_as_of
        ):
            raise ValueError("official entry quote does not match frozen decision lineage")
        if quote.output_mint != outcome.token_mint:
            raise ValueError("official entry BUY quote must output the researched token")
        try:
            amount_raw = int(str(quote.output_amount_raw or ""))
            token_decimals = int(attempt.details["token_decimals"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("official entry lineage lacks sell sizing metadata") from exc
        if amount_raw <= 0:
            raise ValueError("official entry output amount must be positive")
        if not 0 <= token_decimals <= 18:
            raise ValueError("official entry token decimals are invalid")
        return _EntryLineage(
            attempt=attempt,
            quote=quote,
            token_decimals=token_decimals,
            amount_raw=amount_raw,
        )

    def capture(self, outcome: OpportunityForwardOutcome) -> JupiterForwardExitRouteResult:
        if outcome.status != "PENDING":
            raise ValueError("forward route probe only accepts PENDING official outcomes")
        now = int(time.time())
        if now < outcome.target_at:
            raise ValueError("forward route probe cannot run before the exact target time")

        lineage = self._load_entry_lineage(outcome)
        purpose = forward_route_purpose(outcome.horizon_seconds)
        started_at = max(now, outcome.target_at)
        is_new = begin_provider_attempt(
            attempt_key=self.attempt_key(outcome),
            acquisition_run_key=outcome.acquisition_run_key,
            episode_key=outcome.episode_key,
            provider=JUPITER_FORWARD_ROUTE_PROVIDER,
            purpose=purpose,
            started_at=started_at,
        )
        if not is_new:
            return self._existing_result(outcome)

        api_key = self.config.api_key.strip()
        if not api_key:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(outcome),
                status="CONFIG_MISSING",
                completed_at=max(started_at, int(time.time())),
                details={
                    "missing": ["JUPITER_API_KEY"],
                    "route_only": True,
                    "official_forward_outcome_completed": False,
                },
            )
            return JupiterForwardExitRouteResult(attempt=attempt, quote=None, reused_attempt=False)

        try:
            order = JupiterSwapV2Client(
                api_key=api_key,
                timeout=self.config.timeout_seconds,
            ).order(
                input_mint=outcome.token_mint,
                output_mint=USDC_MINT,
                amount_raw=lineage.amount_raw,
                taker=None,
                slippage_bps=self.config.slippage_bps,
            )
        except JupiterOrderError as exc:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(outcome),
                status="PROVIDER_ERROR",
                completed_at=max(started_at, int(time.time())),
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={
                    "route_only": True,
                    "official_forward_outcome_completed": False,
                    "entry_quote_key": lineage.attempt.artifact_key,
                    "sell_amount_raw": str(lineage.amount_raw),
                    "slippage_bps": self.config.slippage_bps,
                },
            )
            return JupiterForwardExitRouteResult(attempt=attempt, quote=None, reused_attempt=False)

        try:
            if order.has_assembled_transaction:
                raise ValueError("route-only Jupiter order unexpectedly returned an assembled transaction")
            quote = jupiter_order_to_causal_quote(
                order,
                token_mint=outcome.token_mint,
                side="sell",
                token_decimals=lineage.token_decimals,
            )
            if quote.executable:
                raise ValueError("route-only forward quote must remain non-executable")
            if quote.observed_at < outcome.target_at:
                raise ValueError("forward route observation cannot precede exact target")
        except (JupiterOrderError, ValueError, TypeError) as exc:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(outcome),
                status="NORMALIZATION_ERROR",
                completed_at=max(started_at, int(time.time()), order.observed_at),
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={
                    "route_only": True,
                    "official_forward_outcome_completed": False,
                    "entry_quote_key": lineage.attempt.artifact_key,
                    "sell_amount_raw": str(lineage.amount_raw),
                    "provider_error_code": order.error_code,
                    "provider_error_message": order.error_message,
                },
            )
            return JupiterForwardExitRouteResult(attempt=attempt, quote=None, reused_attempt=False)

        artifact_key = self.quote_key(outcome)
        record_causal_quote(quote, quote_key=artifact_key)
        attempt = complete_provider_attempt(
            attempt_key=self.attempt_key(outcome),
            status="AVAILABLE",
            completed_at=max(started_at, int(time.time()), quote.observed_at),
            artifact_key=artifact_key,
            details={
                "route_only": True,
                "official_forward_outcome_completed": False,
                "taker_supplied": False,
                "assembled_transaction_present": False,
                "entry_quote_key": lineage.attempt.artifact_key,
                "sell_amount_raw": str(lineage.amount_raw),
                "token_decimals": lineage.token_decimals,
                "target_at": outcome.target_at,
                "quote_observed_at": quote.observed_at,
                "target_lateness_seconds": quote.observed_at - outcome.target_at,
                "slippage_bps": self.config.slippage_bps,
                "route_id": quote.route_id,
                "router": quote.provider_router,
            },
        )
        return JupiterForwardExitRouteResult(attempt=attempt, quote=quote, reused_attempt=False)
