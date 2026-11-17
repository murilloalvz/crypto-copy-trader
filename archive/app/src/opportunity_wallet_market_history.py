from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from src.causal_quote_store import load_causal_quotes
from src.database import connection
from src.jupiter_episode_execution import JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    ensure_market_opportunity_episode_schema,
)
from src.opportunity_forward_outcome_store import (
    FORWARD_OUTCOME_HORIZONS_SECONDS,
    ensure_opportunity_forward_outcome_schema,
    load_opportunity_forward_outcomes,
)
from src.opportunity_provider_attempt_store import (
    ensure_opportunity_provider_attempt_schema,
    list_provider_attempts,
)
from src.opportunity_wallet_intelligence import HistoricalWalletOpportunityAssociation


MARKET_FIRST_WALLET_HISTORY_VERSION = "market_first_wallet_opportunity_history_v1"
PRIOR_PARTICIPANT_WINDOW_SECONDS = 30


@dataclass(frozen=True)
class MarketFirstWalletHistoryLoadResult:
    method_version: str
    current_episode_key: str
    history_cutoff: int
    horizon_seconds: int
    current_participant_wallet_count: int
    candidate_prior_episode_count: int
    eligible_labeled_prior_episode_count: int
    prior_episodes_with_matching_participants: int
    associations: tuple[HistoricalWalletOpportunityAssociation, ...]
    exclusion_counts: tuple[tuple[str, int], ...]
    data_quality_flags: tuple[str, ...]


def _load_prior_episodes_before(
    *, current_episode_key: str, history_cutoff: int
) -> tuple[MarketOpportunityEpisode, ...]:
    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint,
                first_trigger_key, first_trigger_kind, first_trigger_direction,
                first_trigger_chain_time, first_trigger_observed_at,
                episode_closes_at, decision_as_of
            FROM market_opportunity_episodes
            WHERE decision_as_of IS NOT NULL
              AND decision_as_of < ?
              AND episode_key <> ?
            ORDER BY decision_as_of, id""",
            (history_cutoff, current_episode_key),
        ).fetchall()
    return tuple(
        MarketOpportunityEpisode(
            episode_key=str(row["episode_key"]),
            acquisition_run_key=str(row["acquisition_run_key"]),
            token_mint=str(row["token_mint"]),
            first_trigger_key=str(row["first_trigger_key"]),
            first_trigger_kind=str(row["first_trigger_kind"]),
            first_trigger_direction=str(row["first_trigger_direction"]),
            first_trigger_chain_time=int(row["first_trigger_chain_time"]),
            first_trigger_observed_at=int(row["first_trigger_observed_at"]),
            episode_closes_at=int(row["episode_closes_at"]),
            decision_as_of=int(row["decision_as_of"]),
        )
        for row in rows
    )


def _one_quote(quote_key: str):
    rows = load_causal_quotes(quote_keys=(quote_key,))
    return rows[0] if len(rows) == 1 else None


def load_market_first_wallet_opportunity_history(
    *,
    current_episode: MarketOpportunityEpisode,
    current_participant_wallets: tuple[str, ...] | list[str] | set[str],
    horizon_seconds: int,
    history_cutoff: int | None = None,
) -> MarketFirstWalletHistoryLoadResult:
    """Load only official market-first wallet association labels known strictly before current T0.

    This loader deliberately refuses every legacy wallet-first PnL/discovery table. A wallet gets one
    association with a prior opportunity only when all of the following are true:

    - the prior market-first episode had an immutable ``decision_as_of`` before current T0;
    - its Jupiter entry provider attempt was AVAILABLE with an assembled transaction and a persisted
      executable BUY quote already included in that prior decision clock;
    - the exact predeclared +5/+15/+60 forward outcome is AVAILABLE and its executable SELL quote was
      observed strictly before current T0;
    - the wallet was causally present in the prior opportunity's 30-second decision window.

    The resulting return is a quote-to-quote opportunity label, not the wallet's realized PnL and not
    proof of a landed/fill execution. Missing/unavailable history is excluded explicitly rather than
    converted into a loss or backfilled from a later quote.
    """

    if not current_episode.episode_key.strip():
        raise ValueError("current episode_key cannot be empty")
    if current_episode.first_trigger_observed_at < 0:
        raise ValueError("current episode T0 must be non-negative")

    horizon = int(horizon_seconds)
    if horizon not in FORWARD_OUTCOME_HORIZONS_SECONDS:
        raise ValueError(
            "horizon_seconds must be one frozen forward horizon: 300, 900 or 3600"
        )

    cutoff = (
        int(current_episode.first_trigger_observed_at)
        if history_cutoff is None
        else int(history_cutoff)
    )
    if cutoff < 0:
        raise ValueError("history_cutoff must be non-negative")
    if cutoff > current_episode.first_trigger_observed_at:
        raise ValueError("history_cutoff cannot extend beyond current episode T0")

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

    ensure_opportunity_provider_attempt_schema()
    ensure_opportunity_forward_outcome_schema()
    candidates = _load_prior_episodes_before(
        current_episode_key=current_episode.episode_key,
        history_cutoff=cutoff,
    )
    if not candidates:
        flags.append("no_prior_official_market_first_decisions")

    attempts_by_run: dict[str, dict[str, object]] = {}
    outcomes_by_run: dict[str, dict[tuple[str, int], object]] = {}
    quote_cache: dict[str, object | None] = {}
    associations: list[HistoricalWalletOpportunityAssociation] = []
    eligible_labeled = 0
    matched_prior_episodes = 0

    def quote_for(key: str):
        if key not in quote_cache:
            quote_cache[key] = _one_quote(key)
        return quote_cache[key]

    for prior in candidates:
        assert prior.decision_as_of is not None
        decision = int(prior.decision_as_of)
        run_key = prior.acquisition_run_key

        if run_key not in attempts_by_run:
            attempts_by_run[run_key] = {
                item.episode_key: item
                for item in list_provider_attempts(
                    acquisition_run_key=run_key,
                    provider=JUPITER_ENTRY_PROVIDER,
                    purpose=JUPITER_ENTRY_PURPOSE,
                )
            }
        entry_attempt = attempts_by_run[run_key].get(prior.episode_key)
        if entry_attempt is None or getattr(entry_attempt, "status", None) != "AVAILABLE":
            exclusions["entry_executable_quote_not_available"] += 1
            continue
        if getattr(entry_attempt, "completed_at", None) is None or int(
            entry_attempt.completed_at
        ) > decision:
            exclusions["entry_provider_completion_after_decision"] += 1
            continue
        if not bool((getattr(entry_attempt, "details", None) or {}).get(
            "assembled_transaction_present"
        )):
            exclusions["entry_available_without_assembled_transaction"] += 1
            continue
        entry_key = str(getattr(entry_attempt, "artifact_key", None) or "").strip()
        if not entry_key:
            exclusions["entry_quote_artifact_missing"] += 1
            continue
        entry_quote = quote_for(entry_key)
        if (
            entry_quote is None
            or not bool(getattr(entry_quote, "executable", False))
            or getattr(entry_quote, "side", None) != "buy"
            or getattr(entry_quote, "token_mint", None) != prior.token_mint
            or int(getattr(entry_quote, "observed_at", decision + 1)) > decision
        ):
            exclusions["entry_quote_invalid_for_prior_decision"] += 1
            continue

        if run_key not in outcomes_by_run:
            outcomes_by_run[run_key] = {
                (item.episode_key, item.horizon_seconds): item
                for item in load_opportunity_forward_outcomes(
                    acquisition_run_key=run_key
                )
            }
        outcome = outcomes_by_run[run_key].get((prior.episode_key, horizon))
        if outcome is None:
            exclusions["forward_outcome_missing_for_predeclared_horizon"] += 1
            continue
        if getattr(outcome, "status", None) != "AVAILABLE":
            exclusions["forward_outcome_not_available"] += 1
            continue
        if (
            int(getattr(outcome, "decision_as_of", -1)) != decision
            or getattr(outcome, "token_mint", None) != prior.token_mint
            or int(getattr(outcome, "target_at", -1)) != decision + horizon
        ):
            exclusions["forward_outcome_identity_or_clock_mismatch"] += 1
            continue
        outcome_observed_at = getattr(outcome, "observed_at", None)
        if outcome_observed_at is None or int(outcome_observed_at) >= cutoff:
            exclusions["forward_outcome_not_known_strictly_pre_t0"] += 1
            continue
        exit_key = str(getattr(outcome, "quote_key", None) or "").strip()
        if not exit_key:
            exclusions["exit_quote_artifact_missing"] += 1
            continue
        exit_quote = quote_for(exit_key)
        if (
            exit_quote is None
            or not bool(getattr(exit_quote, "executable", False))
            or getattr(exit_quote, "side", None) != "sell"
            or getattr(exit_quote, "token_mint", None) != prior.token_mint
            or int(getattr(exit_quote, "observed_at", cutoff)) > int(outcome_observed_at)
            or int(getattr(exit_quote, "observed_at", cutoff)) >= cutoff
        ):
            exclusions["exit_quote_invalid_or_not_known_pre_t0"] += 1
            continue

        entry_price = float(getattr(entry_quote, "price_usd"))
        exit_price = float(getattr(exit_quote, "price_usd"))
        if (
            entry_price <= 0
            or exit_price <= 0
            or not math.isfinite(entry_price)
            or not math.isfinite(exit_price)
        ):
            exclusions["nonfinite_or_nonpositive_quote_price"] += 1
            continue
        executable_quote_return_pct = 100.0 * (exit_price / entry_price - 1.0)
        if not math.isfinite(executable_quote_return_pct):
            exclusions["nonfinite_quote_return"] += 1
            continue

        eligible_labeled += 1
        prior_trades = load_market_trades(
            acquisition_run_key=prior.acquisition_run_key,
            token_mint=prior.token_mint,
            as_of=decision,
            chain_time_after=max(0, decision - PRIOR_PARTICIPANT_WINDOW_SECONDS),
        )
        prior_wallets = {
            item.observation.wallet_address
            for item in prior_trades
            if item.observation.wallet_address is not None
        }
        matched_wallets = sorted(participant_set.intersection(prior_wallets))
        if not matched_wallets:
            exclusions["no_matching_current_wallet_in_prior_opportunity"] += 1
            continue

        matched_prior_episodes += 1
        resolved_at = max(int(outcome_observed_at), int(exit_quote.observed_at))
        for wallet in matched_wallets:
            associations.append(
                HistoricalWalletOpportunityAssociation(
                    episode_key=prior.episode_key,
                    wallet_address=wallet,
                    token_mint=prior.token_mint,
                    prior_decision_as_of=decision,
                    outcome_observed_at=resolved_at,
                    horizon_seconds=horizon,
                    executable_quote_return_pct=executable_quote_return_pct,
                    entry_quote_key=entry_key,
                    exit_quote_key=exit_key,
                    method_version=MARKET_FIRST_WALLET_HISTORY_VERSION,
                )
            )

    associations.sort(
        key=lambda item: (
            item.outcome_observed_at,
            item.episode_key,
            item.wallet_address,
        )
    )
    if participants and not associations:
        flags.append("no_valid_market_first_history_sample")
    elif associations:
        covered_wallets = {item.wallet_address for item in associations}
        if len(covered_wallets) < len(participants):
            flags.append("partial_market_first_history_coverage")

    return MarketFirstWalletHistoryLoadResult(
        method_version=MARKET_FIRST_WALLET_HISTORY_VERSION,
        current_episode_key=current_episode.episode_key,
        history_cutoff=cutoff,
        horizon_seconds=horizon,
        current_participant_wallet_count=len(participants),
        candidate_prior_episode_count=len(candidates),
        eligible_labeled_prior_episode_count=eligible_labeled,
        prior_episodes_with_matching_participants=matched_prior_episodes,
        associations=tuple(associations),
        exclusion_counts=tuple(sorted(exclusions.items())),
        data_quality_flags=tuple(flags),
    )
