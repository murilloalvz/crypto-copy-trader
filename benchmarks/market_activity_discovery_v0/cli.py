from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import time
from typing import Sequence

from src.market_activity_discovery_cohort_v0 import load_market_activity_discovery_members_v0
from src.market_activity_discovery_run_v0 import (
    close_market_activity_discovery_run_v0,
    create_market_activity_discovery_run_v0,
    interrupt_market_activity_discovery_run_v0,
    load_market_activity_discovery_run_v0,
)
from src.opportunity_forward_outcome_store import load_opportunity_forward_outcomes


CLI_VERSION = "market_activity_discovery_cli_v0"


def _epoch_now() -> int:
    return int(time.time())


def _run_or_fail(run_key: str):
    run = load_market_activity_discovery_run_v0(acquisition_run_key=run_key)
    if run is None:
        raise ValueError("market activity discovery run not found")
    return run


def inspect_market_activity_discovery_run_v0(*, acquisition_run_key: str) -> dict[str, object]:
    run = _run_or_fail(acquisition_run_key)
    members = load_market_activity_discovery_members_v0(
        cohort_key=run.cohort_key,
        acquisition_run_key=run.acquisition_run_key,
    )
    dispositions: dict[str, int] = {}
    for member in members:
        dispositions[member.disposition] = dispositions.get(member.disposition, 0) + 1

    outcomes = load_opportunity_forward_outcomes(acquisition_run_key=run.acquisition_run_key)
    outcome_statuses: dict[str, int] = {}
    outcome_status_by_horizon: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        outcome_statuses[outcome.status] = outcome_statuses.get(outcome.status, 0) + 1
        horizon = str(outcome.horizon_seconds)
        bucket = outcome_status_by_horizon.setdefault(horizon, {})
        bucket[outcome.status] = bucket.get(outcome.status, 0) + 1

    analyzable = sum(1 for member in members if member.primary_analysis_eligible)
    return {
        "cli_version": CLI_VERSION,
        "run": asdict(run),
        "cohort_denominator": len(members),
        "analyzable_t0_count": analyzable,
        "dispositions": dict(sorted(dispositions.items())),
        "forward_outcome_count": len(outcomes),
        "forward_outcome_statuses": dict(sorted(outcome_statuses.items())),
        "forward_outcome_status_by_horizon": {
            key: dict(sorted(value.items()))
            for key, value in sorted(outcome_status_by_horizon.items(), key=lambda item: int(item[0]))
        },
        "economic_edge_evaluated": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="market-activity-discovery-v0",
        description="Research-only operations for the preregistered Market Activity Discovery V0.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    open_parser = sub.add_parser("open", help="Create the immutable six-hour discovery run.")
    open_parser.add_argument("--run-key", required=True)
    open_parser.add_argument("--cohort-key", required=True)
    open_parser.add_argument("--started-at", type=int, default=None)

    inspect_parser = sub.add_parser("inspect", help="Inspect run/cohort/outcome accounting only.")
    inspect_parser.add_argument("--run-key", required=True)

    close_parser = sub.add_parser("close", help="Close normally after the frozen deadline.")
    close_parser.add_argument("--run-key", required=True)
    close_parser.add_argument("--observed-at", type=int, default=None)

    interrupt_parser = sub.add_parser("interrupt", help="Record an operational interruption.")
    interrupt_parser.add_argument("--run-key", required=True)
    interrupt_parser.add_argument("--observed-at", type=int, default=None)
    interrupt_parser.add_argument("--reason", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "open":
        started_at = int(args.started_at) if args.started_at is not None else _epoch_now()
        run = create_market_activity_discovery_run_v0(
            acquisition_run_key=args.run_key,
            cohort_key=args.cohort_key,
            started_at=started_at,
        )
        payload: object = {"cli_version": CLI_VERSION, "run": asdict(run)}
    elif args.command == "inspect":
        payload = inspect_market_activity_discovery_run_v0(
            acquisition_run_key=args.run_key,
        )
    elif args.command == "close":
        observed_at = int(args.observed_at) if args.observed_at is not None else _epoch_now()
        run = close_market_activity_discovery_run_v0(
            acquisition_run_key=args.run_key,
            observed_at=observed_at,
        )
        payload = {"cli_version": CLI_VERSION, "run": asdict(run)}
    elif args.command == "interrupt":
        observed_at = int(args.observed_at) if args.observed_at is not None else _epoch_now()
        run = interrupt_market_activity_discovery_run_v0(
            acquisition_run_key=args.run_key,
            observed_at=observed_at,
            reason=args.reason,
        )
        payload = {"cli_version": CLI_VERSION, "run": asdict(run)}
    else:  # pragma: no cover - argparse enforces the subcommand set.
        raise RuntimeError("unsupported CLI command")

    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
