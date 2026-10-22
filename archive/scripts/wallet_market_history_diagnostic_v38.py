from __future__ import annotations

import argparse
from collections import Counter

from src.database import connection
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    ensure_market_opportunity_episode_schema,
)
from src.opportunity_forward_outcome_store import FORWARD_OUTCOME_HORIZONS_SECONDS
from src.opportunity_wallet_market_history import (
    PRIOR_PARTICIPANT_WINDOW_SECONDS,
    load_market_first_wallet_opportunity_history,
)


def _episodes_for_run(run_key: str, limit: int) -> tuple[MarketOpportunityEpisode, ...]:
    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint,
                first_trigger_key, first_trigger_kind, first_trigger_direction,
                first_trigger_chain_time, first_trigger_observed_at,
                episode_closes_at, decision_as_of
            FROM market_opportunity_episodes
            WHERE acquisition_run_key=?
            ORDER BY first_trigger_observed_at, id
            LIMIT ?""",
            (run_key, int(limit)),
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
            decision_as_of=(
                int(row["decision_as_of"])
                if row["decision_as_of"] is not None
                else None
            ),
        )
        for row in rows
    )


def _participant_wallets_at_t0(episode: MarketOpportunityEpisode) -> tuple[str, ...]:
    t0 = int(episode.first_trigger_observed_at)
    rows = load_market_trades(
        acquisition_run_key=episode.acquisition_run_key,
        token_mint=episode.token_mint,
        as_of=t0,
        chain_time_after=max(0, t0 - PRIOR_PARTICIPANT_WINDOW_SECONDS),
    )
    return tuple(
        sorted(
            {
                item.observation.wallet_address
                for item in rows
                if item.observation.wallet_address is not None
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only diagnostic for strict pre-T0 market-first wallet opportunity history. "
            "No RPC/provider calls and no writes."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument(
        "--horizon-seconds",
        required=True,
        type=int,
        choices=FORWARD_OUTCOME_HORIZONS_SECONDS,
        help="Predeclare exactly one official label horizon: 300, 900 or 3600.",
    )
    parser.add_argument("--max-episodes", type=int, default=12)
    args = parser.parse_args()
    if args.max_episodes <= 0:
        parser.error("max-episodes must be positive")

    print("Crypto Copy Trader — Market-First Wallet History Diagnostic v38")
    print(
        "Mode: READ ONLY — persisted market-first evidence only; no legacy wallet-first PnL, "
        "no RPC/provider calls, no backfill."
    )
    print(
        f"run_key={args.run_key} horizon_seconds={args.horizon_seconds} "
        f"max_episodes={args.max_episodes}"
    )

    episodes = _episodes_for_run(args.run_key, args.max_episodes)
    total_participants = 0
    total_candidates = 0
    total_eligible_labels = 0
    total_matching_prior_episodes = 0
    total_associations = 0
    aggregate_exclusions: Counter[str] = Counter()
    aggregate_flags: Counter[str] = Counter()

    print("\nEPISODES")
    for index, episode in enumerate(episodes, start=1):
        participants = _participant_wallets_at_t0(episode)
        result = load_market_first_wallet_opportunity_history(
            current_episode=episode,
            current_participant_wallets=participants,
            horizon_seconds=args.horizon_seconds,
        )
        total_participants += len(participants)
        total_candidates += result.candidate_prior_episode_count
        total_eligible_labels += result.eligible_labeled_prior_episode_count
        total_matching_prior_episodes += result.prior_episodes_with_matching_participants
        total_associations += len(result.associations)
        aggregate_exclusions.update(dict(result.exclusion_counts))
        aggregate_flags.update(result.data_quality_flags)
        print(
            f"[{index:02d}] episode={episode.episode_key[-18:]} t0={episode.first_trigger_observed_at} "
            f"participants={len(participants)} candidates={result.candidate_prior_episode_count} "
            f"eligible_labels={result.eligible_labeled_prior_episode_count} "
            f"matching_prior_episodes={result.prior_episodes_with_matching_participants} "
            f"associations={len(result.associations)} flags={list(result.data_quality_flags)}"
        )

    print("\nSUMMARY")
    print(
        f"episodes={len(episodes)} participant_wallet_observations={total_participants} "
        f"candidate_prior_episode_checks={total_candidates} "
        f"eligible_labeled_prior_episode_checks={total_eligible_labels} "
        f"matching_prior_episode_checks={total_matching_prior_episodes} "
        f"associations={total_associations}"
    )
    print(f"exclusion_counts={dict(sorted(aggregate_exclusions.items()))}")
    print(f"data_quality_flags={dict(sorted(aggregate_flags.items()))}")

    if not episodes:
        classification = "INCONCLUSIVE_NO_EPISODE_SAMPLE"
    elif total_associations > 0:
        classification = "PASS_HAS_STRICT_PRE_T0_MARKET_FIRST_HISTORY"
    else:
        classification = "INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE"
    print(f"classification={classification}")
    print(
        "Interpretation rule: no official history sample is not strategy failure. Legacy wallet-first "
        "PnL/discovery data is intentionally ignored, and an outcome observed at the same second as "
        "current T0 is excluded because ordering is ambiguous at second-level resolution."
    )


if __name__ == "__main__":
    main()
