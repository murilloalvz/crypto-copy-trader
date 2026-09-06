from __future__ import annotations

import argparse
import sys

from src.provider_start_pacer_v44 import ProviderStartPacerV44
import route_research_forward_cohort_v43 as v43
import route_research_forward_cohort_v44 as v44
import src.route_research_forward_collection_v43 as forward_collection
import unified_market_onchain_hazard_smoke_v37 as v37
import unified_market_route_research_smoke_v41 as v41


V45_MAX_RESEARCH_EPISODES = 50
V45_MIN_RESEARCH_DECISIONS = 40


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v45 larger predeclared route-only forward cohort over the frozen v44 provider pacing. "
            "Only cohort size changes: cap=50, minimum clean decisions=40."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    return parser


def _v43_argv(*, run_key: str) -> list[str]:
    return [
        "route_research_forward_cohort_v43.py",
        "--run-key",
        run_key,
        "--max-research-episodes",
        str(V45_MAX_RESEARCH_EPISODES),
        "--min-research-decisions",
        str(V45_MIN_RESEARCH_DECISIONS),
    ]


def main() -> int:
    args = build_parser().parse_args()
    if min(
        args.hazard_start_interval_ms,
        args.entry_start_interval_ms,
        args.exit_start_interval_ms,
    ) < 0:
        raise SystemExit("v45 provider pacing intervals cannot be negative")

    hazard_pacer = ProviderStartPacerV44(interval_ms=args.hazard_start_interval_ms)
    entry_pacer = ProviderStartPacerV44(interval_ms=args.entry_start_interval_ms)
    exit_pacer = ProviderStartPacerV44(interval_ms=args.exit_start_interval_ms)
    v44._PacedHazardProbeV44.pacer = hazard_pacer
    v44._PacedEntryProbeV44.pacer = entry_pacer
    v44._PacedExitProbeV44.pacer = exit_pacer

    original_hazard_probe = v37.SolanaRPCMintHazardProbe
    original_entry_probe = v41.JupiterResearchEntryRouteProbe
    original_exit_probe = forward_collection.JupiterResearchExitRouteProbe
    original_argv = list(sys.argv)

    v37.SolanaRPCMintHazardProbe = v44._PacedHazardProbeV44
    v41.JupiterResearchEntryRouteProbe = v44._PacedEntryProbeV44
    forward_collection.JupiterResearchExitRouteProbe = v44._PacedExitProbeV44

    print("Crypto Copy Trader — Route-Only Forward Economic Cohort v45")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — frozen v42/v43/v44 semantics with a larger "
        "predeclared cohort only; no retry, no backfill, no taker, signing, submission or official "
        "decision freeze."
    )
    print(
        f"run_key={args.run_key} cohort_cap={V45_MAX_RESEARCH_EPISODES} "
        f"minimum_clean_decisions={V45_MIN_RESEARCH_DECISIONS} "
        f"hazard_start_interval_ms={args.hazard_start_interval_ms} "
        f"entry_start_interval_ms={args.entry_start_interval_ms} "
        f"exit_start_interval_ms={args.exit_start_interval_ms}"
    )

    try:
        # v45 changes only the predeclared sample size. Detector, market path, hazard/entry/exit
        # definitions, notional, slippage, exact horizons, systems gate and v44 pacing stay frozen.
        sys.argv = _v43_argv(run_key=args.run_key)
        result = v43.main()
    finally:
        sys.argv = original_argv
        v37.SolanaRPCMintHazardProbe = original_hazard_probe
        v41.JupiterResearchEntryRouteProbe = original_entry_probe
        forward_collection.JupiterResearchExitRouteProbe = original_exit_probe

    print("\nV45 PROVIDER START PACING DIAGNOSTIC")
    print(v44._snapshot_line("hazard", hazard_pacer))
    print(v44._snapshot_line("entry", entry_pacer))
    print(v44._snapshot_line("exit", exit_pacer))
    print(
        "v45_note=relative to v44, only the predeclared selected cap/minimum decision gate changes "
        "from 40/30 to 50/40. Provider attempts remain at-most-once; failed routes remain explicit "
        "missingness and are never retried or backfilled."
    )
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
