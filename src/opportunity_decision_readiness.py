from __future__ import annotations

from dataclasses import dataclass

from src.jupiter_episode_execution import JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_provider_attempt_store import (
    FINAL_PROVIDER_STATUSES,
    OpportunityProviderAttempt,
)
from src.opportunity_token_hazard import (
    SOLANA_TRACKER_HAZARD_PROVIDER,
    SOLANA_TRACKER_HAZARD_PURPOSE,
)


@dataclass(frozen=True)
class OpportunityDecisionReadiness:
    episode_key: str
    classification: str
    blockers: tuple[str, ...]
    candidate_decision_as_of: int | None
    executable_status: str
    hazard_status: str
    hazard_missingness_explicit: bool


def _matches(attempt: OpportunityProviderAttempt | None, provider: str, purpose: str) -> bool:
    return attempt is not None and attempt.provider == provider and attempt.purpose == purpose


def _provider_message(attempt: OpportunityProviderAttempt) -> str:
    details = attempt.details or {}
    values = [
        details.get("provider_error_message"),
        attempt.error_message,
    ]
    return " ".join(str(item) for item in values if item).strip().lower()


def assess_opportunity_decision_readiness(
    *,
    episode: MarketOpportunityEpisode,
    executable_attempt: OpportunityProviderAttempt | None,
    hazard_attempt: OpportunityProviderAttempt | None,
) -> OpportunityDecisionReadiness:
    """Assess whether causal prerequisites exist; never freezes ``decision_as_of`` itself.

    Hazard provider failures/missingness are allowed to remain explicit terminal evidence rather
    than silently dropping the episode. A funded executable entry remains a hard prerequisite for
    the official economic cohort, so an unfunded taker is reported as BLOCKED_BY_FUNDING instead
    of being reinterpreted as strategy failure.
    """

    blockers: list[str] = []
    clocks = [int(episode.first_trigger_observed_at)]

    if executable_attempt is None:
        executable_status = "NOT_CAPTURED"
        blockers.append("executable_quote_not_captured")
    elif not _matches(executable_attempt, JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE):
        executable_status = "WRONG_PROVIDER"
        blockers.append("executable_quote_provider_mismatch")
    else:
        executable_status = executable_attempt.status
        if executable_attempt.completed_at is not None:
            clocks.append(int(executable_attempt.completed_at))
        if executable_attempt.status == "STARTED":
            blockers.append("executable_quote_pending")
        elif executable_attempt.status == "AVAILABLE":
            if not bool((executable_attempt.details or {}).get("assembled_transaction_present")):
                blockers.append("executable_available_without_assembled_transaction")
        elif (
            executable_attempt.status == "UNAVAILABLE"
            and "insufficient funds" in _provider_message(executable_attempt)
        ):
            blockers.append("funded_taker_required")
        else:
            blockers.append("executable_quote_unavailable")

    hazard_missingness_explicit = False
    if hazard_attempt is None:
        hazard_status = "NOT_CAPTURED"
        blockers.append("token_hazard_not_captured")
    elif not _matches(hazard_attempt, SOLANA_TRACKER_HAZARD_PROVIDER, SOLANA_TRACKER_HAZARD_PURPOSE):
        hazard_status = "WRONG_PROVIDER"
        blockers.append("token_hazard_provider_mismatch")
    else:
        hazard_status = hazard_attempt.status
        if hazard_attempt.completed_at is not None:
            clocks.append(int(hazard_attempt.completed_at))
        if hazard_attempt.status == "STARTED":
            blockers.append("token_hazard_pending")
        elif hazard_attempt.status not in FINAL_PROVIDER_STATUSES:
            blockers.append("token_hazard_nonterminal")
        elif hazard_attempt.status != "AVAILABLE":
            # This is intentionally not a blocker. The final protocol may keep an episode with an
            # explicit missing/error hazard value; what is forbidden is silent omission.
            hazard_missingness_explicit = True

    if "funded_taker_required" in blockers:
        classification = "BLOCKED_BY_FUNDING"
    elif blockers:
        classification = "BLOCKED"
    else:
        classification = "READY_TO_BUILD_DECISION_BUNDLE"

    candidate = max(clocks) if classification == "READY_TO_BUILD_DECISION_BUNDLE" else None
    if candidate is not None and candidate < episode.first_trigger_observed_at:
        raise RuntimeError("candidate decision_as_of cannot precede episode trigger")

    return OpportunityDecisionReadiness(
        episode_key=episode.episode_key,
        classification=classification,
        blockers=tuple(blockers),
        candidate_decision_as_of=candidate,
        executable_status=executable_status,
        hazard_status=hazard_status,
        hazard_missingness_explicit=hazard_missingness_explicit,
    )
