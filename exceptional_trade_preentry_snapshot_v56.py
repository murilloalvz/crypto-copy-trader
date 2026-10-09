from __future__ import annotations

import argparse
import math

from src.exceptional_trade_preentry_v56 import (
    DEFAULT_PREENTRY_WINDOWS_SECONDS,
    ExceptionalTradeReferenceV56,
    derived_preentry_dynamics_v56,
    load_exceptional_trade_preentry_snapshot_v56,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Exceptional Trade Pre-Entry Snapshot v56. READ ONLY: reconstructs only market "
            "evidence strictly before a supplied wallet-entry reference using both chain_time and "
            "observed_at cutoffs. No provider calls, no writes, no outcome label, no score."
        )
    )
    parser.add_argument("--reference-key", required=True)
    parser.add_argument("--acquisition-run-key", required=True)
    parser.add_argument("--wallet", required=True)
    parser.add_argument("--token-mint", required=True)
    parser.add_argument("--entry-chain-time", required=True, type=int)
    parser.add_argument("--entry-observed-at", required=True, type=int)
    return parser


def _fmt(value) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        return f"{value:.3f}"
    return str(value)


def main() -> int:
    args = build_parser().parse_args()
    reference = ExceptionalTradeReferenceV56(
        reference_key=args.reference_key,
        acquisition_run_key=args.acquisition_run_key,
        wallet_address=args.wallet,
        token_mint=args.token_mint,
        entry_chain_time=args.entry_chain_time,
        entry_observed_at=args.entry_observed_at,
    )
    snapshot = load_exceptional_trade_preentry_snapshot_v56(reference=reference)

    print("Crypto Copy Trader — Exceptional Trade Pre-Entry Snapshot v56")
    print(
        "Mode: READ ONLY / DESCRIPTIVE RESEARCH — persisted market observations only; no RPC, "
        "no writes, no outcome labels, no strategy threshold, no recommendation."
    )
    print(
        f"reference_key={snapshot.reference_key} acquisition_run_key={snapshot.acquisition_run_key} "
        f"wallet={snapshot.wallet_address} token_mint={snapshot.token_mint}"
    )
    print(
        f"market_cutoff_chain_time=<{snapshot.market_cutoff_chain_time} "
        f"knowledge_cutoff_observed_at=<{snapshot.knowledge_cutoff_observed_at}"
    )
    print(
        f"candidate_rows_seen={snapshot.candidate_rows_seen} "
        f"rows_strictly_preentry={snapshot.rows_strictly_preentry} "
        f"excluded_same_or_later_market_time={snapshot.excluded_same_or_later_market_time} "
        f"excluded_not_known_before_entry={snapshot.excluded_not_known_before_entry}"
    )
    print(f"snapshot_flags={snapshot.data_quality_flags}")

    print("\nPRE-ENTRY WINDOWS")
    for window in snapshot.windows:
        print(
            f"window={window.window_seconds}s events={window.event_count} buys={window.buy_count} "
            f"sells={window.sell_count} wallet_coverage={_fmt(window.wallet_identity_coverage_pct)} "
            f"unique_wallets={_fmt(window.unique_wallet_count)} "
            f"unique_buy_wallets={_fmt(window.unique_buy_wallet_count)} "
            f"unique_sell_wallets={_fmt(window.unique_sell_wallet_count)} "
            f"repeated_wallet_share={_fmt(window.repeated_wallet_event_share_pct)} "
            f"top1_wallet_share={_fmt(window.top1_wallet_event_share_pct)} "
            f"top3_wallet_share={_fmt(window.top3_wallet_event_share_pct)} "
            f"buy_sell_wallet_overlap_share={_fmt(window.buy_sell_wallet_overlap_share_pct)} "
            f"notional_coverage={_fmt(window.notional_coverage_pct)} "
            f"buy_notional_share={_fmt(window.buy_notional_share_pct)} "
            f"price_coverage={_fmt(window.price_coverage_pct)} "
            f"return_pct={_fmt(window.return_pct)} flags={window.data_quality_flags}"
        )

    print("\nDERIVED PRE-ENTRY DYNAMICS")
    for name, value in derived_preentry_dynamics_v56(snapshot).items():
        print(f"{name}={_fmt(value)}")

    print("\nV56 CLASSIFICATION")
    if snapshot.rows_strictly_preentry <= 0:
        print("classification=INCONCLUSIVE_V56_NO_CAUSAL_PREENTRY_EVIDENCE")
        return 2
    if set(window.window_seconds for window in snapshot.windows) != set(
        DEFAULT_PREENTRY_WINDOWS_SECONDS
    ):
        print("classification=FAIL_V56_WINDOW_CONTRACT")
        return 2
    print("classification=READY_V56_DESCRIPTIVE_PREENTRY_SNAPSHOT")
    print(
        "Interpretation: READY means the strict pre-entry snapshot could be reconstructed. It is "
        "not evidence that the target wallet is skilled, that any participation pattern predicts "
        "returns, or that the system has a trading edge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
