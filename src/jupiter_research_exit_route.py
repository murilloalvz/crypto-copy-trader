from __future__ import annotations

from dataclasses import dataclass
import time

from src.assets import USDC_MINT
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.jupiter_research_entry_route import (
    JUPITER_RESEARCH_ENTRY_PROVIDER,
    JUPITER_RESEARCH_ENTRY_PURPOSE,
)
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)
from src.opportunity_provider_attempt_store import (
    OpportunityProviderAttempt,
    begin_provider_attempt,
    complete_provider_attempt,
    list_provider_attempts,
    load_provider_attempt,
)
from src.opportunity_route_research_store import (
    RouteResearchForwardOutcome,
    complete_route_research_outcome,
    load_route_research_decision,
)


JUPITER_RESEARCH_EXIT_PROVIDER = "jupiter_swap_v2_order"
JUPITER_RESEARCH_EXIT_PURPOSE_PREFIX = "forward_exit_route_only_research"

# A single transient Jupiter timeout/5xx otherwise permanently marks a forward-outcome
# PROVIDER_ERROR (begin/complete_provider_attempt makes the attempt terminal on first try).
# Retry the raw order() call a bounded number of times before giving up; this does not
# touch route-only semantics, lineage, or any frozen threshold, only order-call reliability.
JUPITER_RESEARCH_EXIT_ORDER_MAX_ATTEMPTS = 3
JUPITER_RESEARCH_EXIT_ORDER_RETRY_BACKOFF_SECONDS = 0.5

# v68-07 (2026-10-04) showed the 0.5s generic backoff is too short specifically against
# Jupiter API Gateway HTTP 429 (confirmed via error_message on the stored PROVIDER_ERROR
# outcomes: "[API Gateway] Too many requests", 57 of 59 errors that run). A 429 is rate
# limiting, not a one-off transient fault, so it gets its own longer backoff before the
# next of the same bounded MAX_ATTEMPTS retries -- still no new attempts, no threshold change.
#
# v68-08 (same day, first attempt at 3.0s) then showed 3.0s itself is too LONG relative to
# the frozen target_lateness_p95_max_seconds=2 gate: any outcome needing even one retry is
# mathematically guaranteed to exceed it. Cohort B failed on lateness_p95=6s despite
# ready_horizons=3 (105/120 available, well above the 30-per-horizon floor). Hand-reconstructed
# per-outcome retry counts from the real run (exact multiples of the 3.0s backoff in each
# outcome's observed_at-target_at gap): 76 needed 0 retries (p95 lateness of THIS group alone
# is 0s, max 1s -- confirms the non-retry path barely touches the 2s budget), 16 needed exactly
# 1 retry (real clear-time <=3.0s), 13 needed exactly 2 retries (real clear-time in (3.0, 6.0]s).
# With MAX_ATTEMPTS=3 there are only 2 backoff windows, so total available wait = 2x this
# constant. 1.5s (total 3.0s) is the largest value that still guarantees covering the full
# 16-outcome "needs <=3.0s" group without any chance of losing it to the attempt budget, which
# a shorter candidate (e.g. 1.0s, total 2.0s) cannot guarantee. The 13-outcome "needs >3.0s"
# group is lost (becomes PROVIDER_ERROR) under any backoff this short regardless -- that is not
# fixable by backoff alone and is not attempted here. Known residual risk, not claimed to be
# fully solved: per-horizon availability after losing that group can land exactly at the 30
# floor (300s projected to exactly 30/30 in the v68-08 data), and lateness_p95 could still
# exceed 2s if a large share of the recovered 16 need the full second wait -- the code does not
# persist a per-attempt timestamp, so this cannot be fully bounded from historical data alone.
JUPITER_RESEARCH_EXIT_RATE_LIMIT_STATUS_CODE = 429
JUPITER_RESEARCH_EXIT_RATE_LIMIT_BACKOFF_SECONDS = 1.5


@dataclass(frozen=True)
class JupiterResearchExitRouteConfig:
    api_key: str
    timeout_seconds: int = 5
    slippage_bps: int = 100


@dataclass(frozen=True)
class JupiterResearchExitRouteResult:
    attempt: OpportunityProviderAttempt
    quote: CausalQuoteObservation | None
    outcome: RouteResearchForwardOutcome
    reused_attempt: bool


def research_exit_purpose(horizon_seconds: int) -> str:
    horizon = int(horizon_seconds)
    if horizon <= 0:
        raise ValueError("horizon_seconds must be positive")
    return f"{JUPITER_RESEARCH_EXIT_PURPOSE_PREFIX}_{horizon}s_v1"


class JupiterResearchExitRouteProbe:
    """Capture and finalize one route-only causal SELL research outcome.

    This operates only on ``opportunity_route_research_outcomes``. It never writes the official
    executable forward-outcome store. The SELL amount is the exact raw token amount quoted by the
    frozen route-only BUY research entry.
    """

    def __init__(self, config: JupiterResearchExitRouteConfig):
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= config.slippage_bps <= 10_000:
            raise ValueError("slippage_bps must be between 0 and 10000")
        self.config = config

    @staticmethod
    def attempt_key(outcome: RouteResearchForwardOutcome) -> str:
        return (
            f"provider:{JUPITER_RESEARCH_EXIT_PROVIDER}:"
            f"{research_exit_purpose(outcome.horizon_seconds)}:"
            f"{outcome.acquisition_run_key}:{outcome.episode_key}"
        )

    @staticmethod
    def quote_key(outcome: RouteResearchForwardOutcome) -> str:
        return (
            f"research-exit-route:{JUPITER_RESEARCH_EXIT_PROVIDER}:"
            f"{outcome.acquisition_run_key}:{outcome.episode_key}:"
            f"{outcome.horizon_seconds}s"
        )

    @staticmethod
    def _entry_lineage(outcome: RouteResearchForwardOutcome):
        decision = load_route_research_decision(
            acquisition_run_key=outcome.acquisition_run_key,
            episode_key=outcome.episode_key,
        )
        if decision is None:
            raise ValueError("route research decision is missing")
        if (
            decision.token_mint != outcome.token_mint
            or decision.research_decision_as_of != outcome.research_decision_as_of
        ):
            raise ValueError("route research decision/outcome lineage mismatch")

        quotes = load_causal_quotes(quote_keys=(decision.entry_quote_key,))
        if len(quotes) != 1:
            raise ValueError("route research entry quote is missing or ambiguous")
        entry_quote = quotes[0]
        if (
            entry_quote.side != "buy"
            or entry_quote.token_mint != outcome.token_mint
            or entry_quote.executable
            or entry_quote.observed_at > decision.research_decision_as_of
        ):
            raise ValueError("route research entry quote violates frozen lineage")

        attempts = list_provider_attempts(
            acquisition_run_key=outcome.acquisition_run_key,
            provider=JUPITER_RESEARCH_ENTRY_PROVIDER,
            purpose=JUPITER_RESEARCH_ENTRY_PURPOSE,
        )
        matching = [item for item in attempts if item.episode_key == outcome.episode_key]
        if len(matching) != 1 or matching[0].status != "AVAILABLE":
            raise ValueError("route research entry provider attempt is missing or ambiguous")
        entry_attempt = matching[0]
        if entry_attempt.artifact_key != decision.entry_quote_key:
            raise ValueError("route research entry artifact key mismatch")
        try:
            amount_raw = int(str(entry_quote.output_amount_raw or ""))
            decimals = int((entry_attempt.details or {})["token_decimals"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("route research entry lacks SELL sizing metadata") from exc
        if amount_raw <= 0 or not 0 <= decimals <= 18:
            raise ValueError("route research entry sizing metadata is invalid")
        return decision, entry_attempt, entry_quote, amount_raw, decimals

    def _existing(self, outcome: RouteResearchForwardOutcome) -> JupiterResearchExitRouteResult:
        attempt = load_provider_attempt(attempt_key=self.attempt_key(outcome))
        if attempt is None:
            raise RuntimeError("research exit attempt disappeared after idempotent begin")
        quote = None
        if attempt.artifact_key:
            rows = load_causal_quotes(quote_keys=(attempt.artifact_key,))
            quote = rows[0] if rows else None
        # If a previous call completed the provider attempt it must also have terminalized the
        # research outcome. Reloading through the public list is unnecessary: the caller already
        # supplied the immutable outcome identity, and complete_route_research_outcome is idempotent.
        final_outcome = outcome
        if attempt.status == "AVAILABLE" and quote is not None:
            final_outcome = complete_route_research_outcome(
                outcome_key=outcome.outcome_key,
                status="AVAILABLE",
                observed_at=quote.observed_at,
                quote_key=attempt.artifact_key,
            )
        elif attempt.status in {"PROVIDER_ERROR", "CONFIG_MISSING", "NORMALIZATION_ERROR", "UNAVAILABLE"}:
            final_outcome = complete_route_research_outcome(
                outcome_key=outcome.outcome_key,
                status="PROVIDER_ERROR" if attempt.status != "UNAVAILABLE" else "UNAVAILABLE",
                observed_at=int(attempt.completed_at or outcome.target_at),
                error_type=attempt.error_type or attempt.status,
                error_message=attempt.error_message,
            )
        return JupiterResearchExitRouteResult(attempt, quote, final_outcome, True)

    def capture(self, outcome: RouteResearchForwardOutcome) -> JupiterResearchExitRouteResult:
        if outcome.status != "PENDING":
            raise ValueError("research exit probe only accepts PENDING outcomes")
        now = int(time.time())
        if now < outcome.target_at:
            raise ValueError("research exit probe cannot run before exact target")

        decision, entry_attempt, _entry_quote, amount_raw, decimals = self._entry_lineage(outcome)
        started_at = max(now, outcome.target_at)
        is_new = begin_provider_attempt(
            attempt_key=self.attempt_key(outcome),
            acquisition_run_key=outcome.acquisition_run_key,
            episode_key=outcome.episode_key,
            provider=JUPITER_RESEARCH_EXIT_PROVIDER,
            purpose=research_exit_purpose(outcome.horizon_seconds),
            started_at=started_at,
        )
        if not is_new:
            return self._existing(outcome)

        api_key = self.config.api_key.strip()
        if not api_key:
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(outcome),
                status="CONFIG_MISSING",
                completed_at=max(started_at, int(time.time())),
                error_type="JupiterConfigMissing",
                error_message="JUPITER_API_KEY is required",
                details={
                    "route_only": True,
                    "research_only": True,
                    "official_forward_outcome_completed": False,
                    "entry_quote_key": decision.entry_quote_key,
                },
            )
            completed = complete_route_research_outcome(
                outcome_key=outcome.outcome_key,
                status="PROVIDER_ERROR",
                observed_at=int(attempt.completed_at or started_at),
                error_type=attempt.error_type,
                error_message=attempt.error_message,
            )
            return JupiterResearchExitRouteResult(attempt, None, completed, False)

        last_exc: JupiterOrderError | None = None
        order = None
        for retry_index in range(JUPITER_RESEARCH_EXIT_ORDER_MAX_ATTEMPTS):
            try:
                order = JupiterSwapV2Client(
                    api_key=api_key,
                    timeout=self.config.timeout_seconds,
                ).order(
                    input_mint=outcome.token_mint,
                    output_mint=USDC_MINT,
                    amount_raw=amount_raw,
                    taker=None,
                    slippage_bps=self.config.slippage_bps,
                )
                last_exc = None
                break
            except JupiterOrderError as exc:
                last_exc = exc
                if retry_index + 1 < JUPITER_RESEARCH_EXIT_ORDER_MAX_ATTEMPTS:
                    backoff = (
                        JUPITER_RESEARCH_EXIT_RATE_LIMIT_BACKOFF_SECONDS
                        if exc.status_code == JUPITER_RESEARCH_EXIT_RATE_LIMIT_STATUS_CODE
                        else JUPITER_RESEARCH_EXIT_ORDER_RETRY_BACKOFF_SECONDS
                    )
                    time.sleep(backoff)
        if last_exc is not None:
            exc = last_exc
            completed_at = max(started_at, int(time.time()))
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(outcome),
                status="PROVIDER_ERROR",
                completed_at=completed_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={
                    "route_only": True,
                    "research_only": True,
                    "official_forward_outcome_completed": False,
                    "entry_quote_key": decision.entry_quote_key,
                    "sell_amount_raw": str(amount_raw),
                },
            )
            completed = complete_route_research_outcome(
                outcome_key=outcome.outcome_key,
                status="PROVIDER_ERROR",
                observed_at=completed_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return JupiterResearchExitRouteResult(attempt, None, completed, False)

        try:
            if order.has_assembled_transaction:
                raise ValueError("research route-only SELL unexpectedly returned assembled transaction")
            quote = jupiter_order_to_causal_quote(
                order,
                token_mint=outcome.token_mint,
                side="sell",
                token_decimals=decimals,
            )
            if quote.executable:
                raise ValueError("research exit route quote must remain non-executable")
            if quote.observed_at < outcome.target_at:
                raise ValueError("research exit quote cannot precede exact target")
        except (JupiterOrderError, ValueError, TypeError) as exc:
            completed_at = max(started_at, int(time.time()), order.observed_at)
            attempt = complete_provider_attempt(
                attempt_key=self.attempt_key(outcome),
                status="NORMALIZATION_ERROR",
                completed_at=completed_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={
                    "route_only": True,
                    "research_only": True,
                    "official_forward_outcome_completed": False,
                    "entry_quote_key": decision.entry_quote_key,
                    "sell_amount_raw": str(amount_raw),
                },
            )
            completed = complete_route_research_outcome(
                outcome_key=outcome.outcome_key,
                status="PROVIDER_ERROR",
                observed_at=completed_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return JupiterResearchExitRouteResult(attempt, None, completed, False)

        artifact_key = self.quote_key(outcome)
        record_causal_quote(quote, quote_key=artifact_key)
        attempt = complete_provider_attempt(
            attempt_key=self.attempt_key(outcome),
            status="AVAILABLE",
            completed_at=max(started_at, int(time.time()), quote.observed_at),
            artifact_key=artifact_key,
            details={
                "route_only": True,
                "research_only": True,
                "official_forward_outcome_completed": False,
                "taker_supplied": False,
                "assembled_transaction_present": False,
                "entry_quote_key": decision.entry_quote_key,
                "entry_attempt_key": entry_attempt.attempt_key,
                "sell_amount_raw": str(amount_raw),
                "token_decimals": decimals,
                "target_at": outcome.target_at,
                "quote_observed_at": quote.observed_at,
                "target_lateness_seconds": quote.observed_at - outcome.target_at,
                "route_id": quote.route_id,
                "router": quote.provider_router,
            },
        )
        completed = complete_route_research_outcome(
            outcome_key=outcome.outcome_key,
            status="AVAILABLE",
            observed_at=quote.observed_at,
            quote_key=artifact_key,
        )
        return JupiterResearchExitRouteResult(attempt, quote, completed, False)
