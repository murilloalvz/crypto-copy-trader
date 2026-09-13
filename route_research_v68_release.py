from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import route_research_forward_cohort_v43 as v43
import route_research_prospective_flow60_buy_share_holdout_v68 as v68
import route_research_prospective_flow60_buy_share_holdout_v68_tailfix_v9 as v68_v9
import unified_market_latency_smoke_v30 as v30
import unified_market_route_research_smoke_tailfix_v9 as tailfix_v9
from src.config import settings
from src.sqlite_write_admission import sqlite_write_admission_snapshot


V68_RELEASE_SYSTEMS_PROFILE = (
    "v68_release_v1:v9_partial_order+causal_authoritative_writer+demoted_audit_split+writer_batch64"
)
V68_RELEASE_PUMPSWAP_WRITER_BATCH_SIZE = 64
V68_RELEASE_PUMPSWAP_WRITER_BATCH_MAX_WAIT_MS = 10

_EXPECTED_V68_ECONOMIC_CONTRACT = (
    "flow60_buy_share_pct",
    57.1429,
    65.7143,
    "LOW",
    "HIGH",
    900,
    5,
)


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str


def _parser_defaults(parser: argparse.ArgumentParser) -> dict[str, object]:
    return {
        action.dest: action.default
        for action in parser._actions
        if getattr(action, "dest", None) not in (None, "help")
    }


def _release_v43_parser_factory(original_build_parser):
    def build_parser() -> argparse.ArgumentParser:
        parser = original_build_parser()
        parser.set_defaults(
            pumpswap_writer_batch_size=V68_RELEASE_PUMPSWAP_WRITER_BATCH_SIZE,
            pumpswap_writer_batch_max_wait_ms=V68_RELEASE_PUMPSWAP_WRITER_BATCH_MAX_WAIT_MS,
        )
        return parser

    return build_parser


def _economic_contract() -> tuple[object, ...]:
    return (
        v68.V68_FEATURE_NAME,
        v68.V68_LOW_MAX,
        v68.V68_MID_MAX,
        v68.V68_FAVORABLE_GROUP,
        v68.V68_OPPOSITE_GROUP,
        v68.V68_PRIMARY_HORIZON_SECONDS,
        v68.V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT,
    )


def collect_readiness_checks(*, run_key: str) -> tuple[ReadinessCheck, ...]:
    base = str(run_key).strip()
    run_keys = (f"{base}-A", f"{base}-B") if base else ("", "")

    original_build_parser = v43.build_parser
    release_parser = _release_v43_parser_factory(original_build_parser)()
    defaults = _parser_defaults(release_parser)

    sqlite_snapshot = sqlite_write_admission_snapshot()
    sqlite_idle = not any(
        (
            sqlite_snapshot.max_resolution_waiters,
            sqlite_snapshot.max_causal_waiters,
            sqlite_snapshot.max_audit_waiters,
        )
    )

    db_path = Path(settings.database_path)
    db_parent = db_path.parent if str(db_path.parent) else Path(".")

    checks = [
        ReadinessCheck("run_key_nonempty", bool(base), f"base={base or '<empty>'}"),
        ReadinessCheck(
            "fresh_v68_subcohort_keys",
            bool(base) and v68._fresh_run_preflight(run_keys),
            f"run_keys={run_keys}",
        ),
        ReadinessCheck(
            "jupiter_api_key_present",
            bool(settings.jupiter_api_key.strip()),
            "JUPITER_API_KEY=set" if settings.jupiter_api_key.strip() else "JUPITER_API_KEY=missing",
        ),
        ReadinessCheck(
            "rpc_url_present",
            bool(settings.rpc_url.strip()),
            "SOLANA_RPC_URL=set" if settings.rpc_url.strip() else "SOLANA_RPC_URL=missing",
        ),
        ReadinessCheck(
            "database_parent_exists",
            db_parent.exists(),
            f"database_path={db_path}",
        ),
        ReadinessCheck(
            "frozen_v68_economic_contract",
            _economic_contract() == _EXPECTED_V68_ECONOMIC_CONTRACT,
            f"contract={_economic_contract()}",
        ),
        ReadinessCheck(
            "v9_runner_available",
            v68_v9.tailfix_v9.run_smoke_tailfix_v9 is tailfix_v9.run_smoke_tailfix_v9,
            "canonical V9 systems runner binding",
        ),
        ReadinessCheck(
            "pumpswap_workers_capacity",
            int(defaults["pumpswap_workers"]) >= v30.MIN_PUMPSWAP_WORKERS,
            f"workers={defaults['pumpswap_workers']} min={v30.MIN_PUMPSWAP_WORKERS}",
        ),
        ReadinessCheck(
            "pump_prepare_workers_capacity",
            int(defaults["pump_prepare_workers"]) >= v30.MIN_PUMP_PREPARE_WORKERS,
            f"workers={defaults['pump_prepare_workers']} min={v30.MIN_PUMP_PREPARE_WORKERS}",
        ),
        ReadinessCheck(
            "pumpswap_prepare_submitters_capacity",
            int(defaults["pumpswap_prepare_submitters"])
            >= v30.MIN_PUMPSWAP_PREPARE_SUBMITTERS,
            f"submitters={defaults['pumpswap_prepare_submitters']} min={v30.MIN_PUMPSWAP_PREPARE_SUBMITTERS}",
        ),
        ReadinessCheck(
            "pumpswap_prepare_executor_capacity",
            int(defaults["pumpswap_prepare_executor_workers"])
            >= v30.MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
            f"workers={defaults['pumpswap_prepare_executor_workers']} min={v30.MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS}",
        ),
        ReadinessCheck(
            "default_io_capacity",
            int(defaults["default_io_workers"]) >= v30.MIN_DEFAULT_IO_WORKERS,
            f"workers={defaults['default_io_workers']} min={v30.MIN_DEFAULT_IO_WORKERS}",
        ),
        ReadinessCheck(
            "release_writer_batch_size",
            int(defaults["pumpswap_writer_batch_size"])
            == V68_RELEASE_PUMPSWAP_WRITER_BATCH_SIZE,
            f"batch_size={defaults['pumpswap_writer_batch_size']}",
        ),
        ReadinessCheck(
            "release_writer_batch_wait",
            int(defaults["pumpswap_writer_batch_max_wait_ms"])
            == V68_RELEASE_PUMPSWAP_WRITER_BATCH_MAX_WAIT_MS,
            f"max_wait_ms={defaults['pumpswap_writer_batch_max_wait_ms']}",
        ),
        ReadinessCheck(
            "sqlite_admission_idle",
            sqlite_idle,
            "no active waiter high-water observed in current process",
        ),
    ]
    return tuple(checks)


def print_readiness(*, run_key: str) -> bool:
    checks = collect_readiness_checks(run_key=run_key)
    print("Crypto Copy Trader — V68 Release Readiness V1")
    print(f"systems_profile={V68_RELEASE_SYSTEMS_PROFILE}")
    for item in checks:
        print(f"{item.name}={'PASS' if item.passed else 'FAIL'} detail={item.detail}")
    passed = all(item.passed for item in checks)
    print(f"classification={'PASS_V68_RELEASE_READINESS_V1' if passed else 'FAIL_V68_RELEASE_READINESS_V1'}")
    return passed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical V68 release entrypoint. Runs a fail-closed readiness check, then the frozen "
            "V68 A/B prospective route-only hypothesis through the accepted V9 systems path with "
            "a systems-only PumpSwap writer burst-capacity increase from 32 to 64."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    base = args.run_key.strip()
    if not base:
        raise SystemExit("--run-key cannot be empty")
    if min(
        args.hazard_start_interval_ms,
        args.entry_start_interval_ms,
        args.exit_start_interval_ms,
    ) < 0:
        raise SystemExit("provider pacing intervals cannot be negative")

    if not print_readiness(run_key=base):
        return 2
    if args.preflight_only:
        return 0

    original_v68_argv = list(sys.argv)
    original_v43_build_parser = v43.build_parser
    original_run_smoke = v68.v54.run_smoke_v54
    original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
    try:
        v43.build_parser = _release_v43_parser_factory(original_v43_build_parser)
        v68.v54.run_smoke_v54 = tailfix_v9.run_smoke_tailfix_v9
        v68.V68_VALIDATED_SYSTEMS_PROFILE = V68_RELEASE_SYSTEMS_PROFILE
        sys.argv = [
            "route_research_prospective_flow60_buy_share_holdout_v68.py",
            "--run-key",
            base,
            "--hazard-start-interval-ms",
            str(args.hazard_start_interval_ms),
            "--entry-start-interval-ms",
            str(args.entry_start_interval_ms),
            "--exit-start-interval-ms",
            str(args.exit_start_interval_ms),
        ]
        return int(v68.main())
    finally:
        sys.argv = original_v68_argv
        v68.v54.run_smoke_v54 = original_run_smoke
        v68.V68_VALIDATED_SYSTEMS_PROFILE = original_profile
        v43.build_parser = original_v43_build_parser


if __name__ == "__main__":
    raise SystemExit(main())
