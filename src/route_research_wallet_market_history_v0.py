from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from src.causal_quote_store import load_causal_quotes
from src.database import connection
from src.market_opportunity_episode_store import (
    get_market_opportunity_episode,
)
from src.opportunity_episode_enrichment import (
    build_episode_enrichment_bundle,
)
from src.opportunity_route_research_store import (
    ensure_route_research_schema,
    load_route_research_decision,
    load_route_research_outcomes,
)


VERSION = "route_research_wallet_market_history_v0"


@dataclass(frozen=True)
class RouteResearchWalletOpportunityAssociationV0:
    prior_run_key: str
    prior_episode_key: str
    wallet_address: str
    token_mint: str
    prior_research_decision_as_of: int
    outcome_observed_at: int
    horizon_seconds: int
    route_quote_return_pct: float
    entry_quote_key: str
    exit_quote_key: str


@dataclass(frozen=True)
class RouteResearchWalletHistoryLoadResultV0:
    method_version: str
    current_episode_key: str
    history_cutoff: int
    horizon_seconds: int
    current_participant_wallet_count: int
    candidate_prior_episode_count: int
    eligible_labeled_prior_episode_count: int
    prior_episodes_with_matching_participants: int
    associations: tuple[RouteResearchWalletOpportunityAssociationV0, ...]
    exclusion_counts: dict[str, int]
    data_quality_flags: tuple[str, ...]


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _one_quote(quote_key: str):
    rows = load_causal_quotes(quote_keys=(quote_key,))
    return rows[0] if len(rows) == 1 else None


def _prior_decision_keys_before(
    *,
    cutoff: int,
    current_episode_key: str,
) -> list[tuple[str, str]]:
    ensure_route_research_schema()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT acquisition_run_key, episode_key
            FROM opportunity_route_research_decisions
            WHERE research_decision_as_of < ?
              AND episode_key <> ?
            ORDER BY research_decision_as_of, id
            """,
            (int(cutoff), str(current_episode_key)),
        ).fetchall()
    return [
        (str(row["acquisition_run_key"]), str(row["episode_key"]))
        for row in rows
    ]


def _prior_participant_wallets(
    *,
    run_key: str,
    episode_key: str,
) -> tuple[str, ...]:
    decision = load_route_research_decision(
        acquisition_run_key=run_key,
        episode_key=episode_key,
    )
    episode = get_market_opportunity_episode(episode_key)
    if decision is None or episode is None:
        return tuple()
    bundle = build_episode_enrichment_bundle(
        episode=episode,
        as_of=decision.research_decision_as_of,
    )
    return tuple(
        sorted(
            {
                row.wallet_address
                for row in bundle.wallet_intelligence.wallets
                if row.wallet_address
            }
        )
    )


def load_route_research_wallet_history_v0(
    *,
    current_episode_key: str,
    current_token_mint: str,
    current_participant_wallets: tuple[str, ...] | list[str] | set[str],
    history_cutoff: int,
    horizon_seconds: int = 900,
    excluded_acquisition_run_keys: tuple[str, ...] | list[str] | set[str] = (),
) -> RouteResearchWalletHistoryLoadResultV0:
    current_key = str(current_episode_key).strip()
    token_mint = str(current_token_mint).strip()
    cutoff = int(history_cutoff)
    horizon = int(horizon_seconds)
    excluded_runs = {
        str(item).strip()
        for item in excluded_acquisition_run_keys
        if str(item).strip()
    }
    if not current_key:
        raise ValueError("current_episode_key cannot be empty")
    if not token_mint:
        raise ValueError("current_token_mint cannot be empty")
    if cutoff < 0:
        raise ValueError("history_cutoff must be non-negative")
    if horizon not in {300, 900, 3600}:
        raise ValueError("unsupported route-research history horizon")

    participants = tuple(
        sorted(
            {
                str(wallet).strip()
                for wallet in current_participant_wallets
                if str(wallet).strip()
            }
        )
    )
    participant_set = set(participants)
    exclusions: Counter[str] = Counter()
    flags: list[str] = []
    if not participants:
        flags.append("no_current_participant_wallets")

    raw_prior_keys = _prior_decision_keys_before(
        cutoff=cutoff,
        current_episode_key=current_key,
    )
    prior_keys: list[tuple[str, str]] = []
    for run_key, episode_key in raw_prior_keys:
        if run_key in excluded_runs:
            exclusions["excluded_invalid_acquisition_run"] += 1
            continue
        prior_keys.append((run_key, episode_key))

    associations: list[RouteResearchWalletOpportunityAssociationV0] = []
    eligible_labeled = 0
    matched_episodes = 0
    outcome_cache: dict[str, dict[tuple[str, int], object]] = {}

    for run_key, episode_key in prior_keys:
        decision = load_route_research_decision(
            acquisition_run_key=run_key,
            episode_key=episode_key,
        )
        episode = get_market_opportunity_episode(episode_key)
        if decision is None or episode is None:
            exclusions["missing_prior_decision_or_episode"] += 1
            continue
        if decision.research_decision_as_of >= cutoff:
            exclusions["prior_decision_not_strictly_pre_t0"] += 1
            continue
        if episode.token_mint == token_mint:
            exclusions["same_token_prior_episode"] += 1
            continue

        entry_quote = _one_quote(decision.entry_quote_key)
        if (
            entry_quote is None
            or entry_quote.token_mint != episode.token_mint
            or entry_quote.side != "buy"
            or bool(entry_quote.executable)
            or int(entry_quote.observed_at) > int(decision.research_decision_as_of)
        ):
            exclusions["invalid_prior_route_entry_quote"] += 1
            continue

        if run_key not in outcome_cache:
            outcome_cache[run_key] = {
                (item.episode_key, item.horizon_seconds): item
                for item in load_route_research_outcomes(
                    acquisition_run_key=run_key
                )
            }
        outcome = outcome_cache[run_key].get((episode_key, horizon))
        if outcome is None:
            exclusions["prior_outcome_missing"] += 1
            continue
        if outcome.status != "AVAILABLE":
            exclusions["prior_outcome_not_available"] += 1
            continue
        if (
            int(outcome.research_decision_as_of)
            != int(decision.research_decision_as_of)
            or int(outcome.target_at)
            != int(decision.research_decision_as_of) + horizon
        ):
            exclusions["prior_outcome_identity_or_clock_mismatch"] += 1
            continue
        if outcome.observed_at is None or int(outcome.observed_at) >= cutoff:
            exclusions["prior_outcome_not_known_strictly_pre_t0"] += 1
            continue
        exit_key = str(outcome.quote_key or "").strip()
        if not exit_key:
            exclusions["prior_exit_quote_missing"] += 1
            continue
        exit_quote = _one_quote(exit_key)
        if (
            exit_quote is None
            or exit_quote.token_mint != episode.token_mint
            or exit_quote.side != "sell"
            or bool(exit_quote.executable)
            or int(exit_quote.observed_at) > int(outcome.observed_at)
            or int(exit_quote.observed_at) >= cutoff
        ):
            exclusions["invalid_prior_route_exit_quote"] += 1
            continue

        entry_price = _finite(entry_quote.price_usd)
        exit_price = _finite(exit_quote.price_usd)
        if (
            entry_price is None
            or exit_price is None
            or entry_price <= 0
            or exit_price <= 0
        ):
            exclusions["invalid_prior_route_quote_price"] += 1
            continue

        eligible_labeled += 1
        prior_wallets = set(
            _prior_participant_wallets(
                run_key=run_key,
                episode_key=episode_key,
            )
        )
        matched = sorted(participant_set & prior_wallets)
        if not matched:
            exclusions["no_matching_current_wallet_in_prior_episode"] += 1
            continue

        matched_episodes += 1
        route_return = 100.0 * (exit_price / entry_price - 1.0)
        if not math.isfinite(route_return):
            exclusions["nonfinite_prior_route_return"] += 1
            continue

        for wallet in matched:
            associations.append(
                RouteResearchWalletOpportunityAssociationV0(
                    prior_run_key=run_key,
                    prior_episode_key=episode_key,
                    wallet_address=wallet,
                    token_mint=episode.token_mint,
                    prior_research_decision_as_of=(
                        decision.research_decision_as_of
                    ),
                    outcome_observed_at=int(outcome.observed_at),
                    horizon_seconds=horizon,
                    route_quote_return_pct=route_return,
                    entry_quote_key=decision.entry_quote_key,
                    exit_quote_key=exit_key,
                )
            )

    associations.sort(
        key=lambda item: (
            item.outcome_observed_at,
            item.prior_run_key,
            item.prior_episode_key,
            item.wallet_address,
        )
    )
    if participants and not associations:
        flags.append("no_valid_route_research_history_sample")
    elif associations:
        covered = {item.wallet_address for item in associations}
        if len(covered) < len(participants):
            flags.append("partial_route_research_history_coverage")
    if excluded_runs:
        flags.append("invalid_acquisition_runs_explicitly_excluded")

    return RouteResearchWalletHistoryLoadResultV0(
        method_version=VERSION,
        current_episode_key=current_key,
        history_cutoff=cutoff,
        horizon_seconds=horizon,
        current_participant_wallet_count=len(participants),
        candidate_prior_episode_count=len(prior_keys),
        eligible_labeled_prior_episode_count=eligible_labeled,
        prior_episodes_with_matching_participants=matched_episodes,
        associations=tuple(associations),
        exclusion_counts=dict(exclusions),
        data_quality_flags=tuple(flags),
    )
