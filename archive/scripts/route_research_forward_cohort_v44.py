from __future__ import annotations

import argparse
import sys

from src.jupiter_research_entry_route import JupiterResearchEntryRouteProbe
from src.jupiter_research_exit_route import JupiterResearchExitRouteProbe
from src.opportunity_onchain_hazard import SolanaRPCMintHazardProbe
from src.provider_start_pacer_v44 import ProviderStartPacerV44
import route_research_forward_cohort_v43 as v43
import src.route_research_forward_collection_v43 as forward_collection
import unified_market_onchain_hazard_smoke_v37 as v37
import unified_market_route_research_smoke_v41 as v41


class _PacedHazardProbeV44(SolanaRPCMintHazardProbe):
    pacer: ProviderStartPacerV44 | None = None

    def capture(self, episode):
        if self.pacer is None:
            raise RuntimeError("v44 hazard pacer not configured")
        self.pacer.wait_for_slot()
        return super().capture(episode)


class _PacedEntryProbeV44(JupiterResearchEntryRouteProbe):
    pacer: ProviderStartPacerV44 | None = None

    def capture(self, episode, *, hazard_attempt):
        if self.pacer is None:
            raise RuntimeError("v44 entry pacer not configured")
        self.pacer.wait_for_slot()
        return super().capture(episode, hazard_attempt=hazard_attempt)


class _PacedExitProbeV44(JupiterResearchExitRouteProbe):
    pacer: ProviderStartPacerV44 | None = None

    def capture(self, outcome):
        if self.pacer is None:
            raise RuntimeError("v44 exit pacer not configured")
        self.pacer.wait_for_slot()
        return super().capture(outcome)


def _snapshot_line(name: str, pacer: ProviderStartPacerV44) -> str:
    snapshot = pacer.snapshot()
    return (
        f"{name}_interval_ms={snapshot.interval_ms} starts={snapshot.starts} "
        f"waited_starts={snapshot.waited_starts} "
        f"total_wait_ms={snapshot.total_wait_seconds * 1000.0:.1f} "
        f"max_wait_ms={snapshot.max_wait_seconds * 1000.0:.1f}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v44 forward economic cohort with provider start pacing over the frozen v43/v42 path. "
            "Pacing changes burst shape only; it never retries failed attempts."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if min(
        args.hazard_start_interval_ms,
        args.entry_start_interval_ms,
        args.exit_start_interval_ms,
    ) < 0:
        raise SystemExit("v44 provider pacing intervals cannot be negative")

    hazard_pacer = ProviderStartPacerV44(interval_ms=args.hazard_start_interval_ms)
    entry_pacer = ProviderStartPacerV44(interval_ms=args.entry_start_interval_ms)
    exit_pacer = ProviderStartPacerV44(interval_ms=args.exit_start_interval_ms)
    _PacedHazardProbeV44.pacer = hazard_pacer
    _PacedEntryProbeV44.pacer = entry_pacer
    _PacedExitProbeV44.pacer = exit_pacer

    original_hazard_probe = v37.SolanaRPCMintHazardProbe
    original_entry_probe = v41.JupiterResearchEntryRouteProbe
    original_exit_probe = forward_collection.JupiterResearchExitRouteProbe
    original_argv = list(sys.argv)

    v37.SolanaRPCMintHazardProbe = _PacedHazardProbeV44
    v41.JupiterResearchEntryRouteProbe = _PacedEntryProbeV44
    forward_collection.JupiterResearchExitRouteProbe = _PacedExitProbeV44

    print("Crypto Copy Trader — Route-Only Forward Economic Cohort v44")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — frozen v42/v43 semantics with provider start pacing; "
        "no retry, no backfill, no taker, signing, submission or official decision freeze."
    )
    print(
        f"run_key={args.run_key} hazard_start_interval_ms={args.hazard_start_interval_ms} "
        f"entry_start_interval_ms={args.entry_start_interval_ms} "
        f"exit_start_interval_ms={args.exit_start_interval_ms}"
    )

    try:
        # v43 retains the frozen cohort protocol (cap=40, minimum=30, 120s acquisition, 11/11 gate).
        # v44 changes only provider start timing through the injected probe subclasses above.
        sys.argv = [original_argv[0], "--run-key", args.run_key]
        result = v43.main()
    finally:
        sys.argv = original_argv
        v37.SolanaRPCMintHazardProbe = original_hazard_probe
        v41.JupiterResearchEntryRouteProbe = original_entry_probe
        forward_collection.JupiterResearchExitRouteProbe = original_exit_probe

    print("\nV44 PROVIDER START PACING DIAGNOSTIC")
    print(_snapshot_line("hazard", hazard_pacer))
    print(_snapshot_line("entry", entry_pacer))
    print(_snapshot_line("exit", exit_pacer))
    print(
        "v44_note=pacing reserves a start slot before each original at-most-once provider capture. "
        "It does not retry a 429, replace explicit missingness, backfill a later quote, or alter "
        "detector/episode/FIFO/as-of/economic definitions."
    )
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
