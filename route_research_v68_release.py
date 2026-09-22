from __future__ import annotations

import argparse
import asyncio
import json
from os import getenv
import sys
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path

import route_research_forward_cohort_v43 as v43
import route_research_prospective_flow60_buy_share_holdout_v68 as v68
import route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0 as v68_signal_plane
import signal_plane_v68_promotion_v0 as signal_plane_promotion
import route_research_prospective_flow60_buy_share_holdout_v68_tailfix_v9 as v68_v9
import unified_market_latency_smoke_v30 as v30
import unified_market_route_research_smoke_tailfix_v9 as tailfix_v9
from src.config import settings
from src.database import connection
from src.pump_bonding_stream import (
    build_logs_subscribe_request as build_pump_logs_subscribe_request,
    rpc_http_to_ws_url,
)
from src.pumpswap_stream import (
    build_logs_subscribe_request as build_pumpswap_logs_subscribe_request,
)
import src.sqlite_write_admission as sqlite_admission
from src.signal_plane_episode_bridge_v0 import (
    SIGNAL_PLANE_EPISODE_BRIDGE_VERSION,
    build_signal_plane_episode_assignment,
)
from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketMovementFeatures,
    MarketMovementTrigger,
    MarketTradeObservation,
)


V68_RELEASE_SYSTEMS_PROFILE = (
    "v68_release_v1:v9_partial_order+causal_authoritative_writer+demoted_audit_split+writer_batch64"
)
V68_RELEASE_PUMPSWAP_WRITER_BATCH_SIZE = 64
V68_RELEASE_PUMPSWAP_WRITER_BATCH_MAX_WAIT_MS = 10
V68_REQUIRED_SIGNAL_PLANE_BRIDGE_VERSION = "signal_plane_episode_bridge_v0"
V68_SIGNAL_PLANE_PROMOTION_AUTHORIZED = False

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


def _signal_plane_bridge_contract_check() -> tuple[bool, str]:
    """Offline proof that Rust/Python trigger semantics preserve frozen episode identity."""

    features = MarketMovementFeatures(
        token_mint="TOKEN",
        as_of=120,
        chain_as_of=119,
        fast_window_seconds=30,
        baseline_horizon_seconds=300,
        fast_event_count=6,
        baseline_event_count=3,
        fast_buy_count=5,
        fast_sell_count=1,
        fast_unique_wallet_count=5,
        fast_unique_transaction_count=6,
        wallet_identity_coverage_pct=100.0,
        transaction_identity_coverage_pct=100.0,
        notional_coverage_pct=100.0,
        price_coverage_pct=100.0,
        fast_event_rate_per_second=0.2,
        baseline_event_rate_per_second=3 / 270,
        activity_acceleration_ratio=18.0,
        signed_notional_imbalance_pct=50.0,
        count_imbalance_pct=66.6666666667,
        direction="upward_pressure",
        first_price_usd=1.0,
        last_price_usd=1.1,
        fast_return_pct=10.0,
        median_observation_lag_seconds=None,
        max_observation_lag_seconds=None,
        venues=("pump",),
        market_age_seconds=20,
        data_quality_flags=(),
    )
    trigger = MarketMovementTrigger(
        token_mint="TOKEN",
        as_of=120,
        method_version=MARKET_OPPORTUNITY_RADAR_VERSION,
        trigger_kind="fresh_market_burst",
        direction="upward_pressure",
        features=features,
    )

    pump = build_signal_plane_episode_assignment(
        trigger=trigger,
        observation=MarketTradeObservation(
            token_mint="TOKEN",
            side="buy",
            chain_time=119,
            observed_at=120,
            venue="pump",
            transaction_key="pump-signature",
        ),
    )
    pumpswap = build_signal_plane_episode_assignment(
        trigger=trigger,
        observation=MarketTradeObservation(
            token_mint="TOKEN",
            side="buy",
            chain_time=119,
            observed_at=120,
            venue="pumpswap",
            transaction_key="pumpswap-signature",
        ),
    )

    passed = (
        SIGNAL_PLANE_EPISODE_BRIDGE_VERSION
        == V68_REQUIRED_SIGNAL_PLANE_BRIDGE_VERSION
        and pump.trigger_key
        == "market-radar:pump:pump-signature:TOKEN"
        and pump.venue == "pump_bonding_curve"
        and pumpswap.trigger_key
        == "market-radar:pumpswap-v3:pumpswap-signature:TOKEN"
        and pumpswap.venue == "pump_swap"
        and pump.observed_at == pumpswap.observed_at == 120
        and pump.chain_time == pumpswap.chain_time == 119
    )
    detail = (
        f"bridge_version={SIGNAL_PLANE_EPISODE_BRIDGE_VERSION} "
        f"pump_key={pump.trigger_key} pumpswap_key={pumpswap.trigger_key}"
    )
    return passed, detail


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


def _signal_plane_promotion_check(
    promotion_report: Path | None,
) -> tuple[bool, str]:
    if promotion_report is None:
        return False, "promotion_report=missing"
    return signal_plane_promotion.validate_promotion_report(
        Path(promotion_report)
    )


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _run_key_residue_counts(run_keys: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """Find any durable evidence already attached to candidate acquisition run keys.

    Historical V68's freshness guard only looked at route outcomes. A crashed acquisition can leave
    earlier observations, episodes, provider attempts or decisions without any outcome row. Reusing
    such a key is not a fresh prospective cohort. Inspect every existing SQLite table that exposes
    an `acquisition_run_key` column so new durable tables are covered automatically.
    """

    normalized = tuple(str(item).strip() for item in run_keys if str(item).strip())
    residue: dict[str, dict[str, int]] = {item: {} for item in normalized}
    if not normalized:
        return residue

    with connection() as conn:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for table_row in table_rows:
            table = str(table_row["name"])
            quoted = _quote_identifier(table)
            columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            if "acquisition_run_key" not in {str(row["name"]) for row in columns}:
                continue
            for run_key in normalized:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {quoted} WHERE acquisition_run_key=?",
                    (run_key,),
                ).fetchone()
                count = int(row["n"]) if row is not None else 0
                if count:
                    residue[run_key][table] = count
    return residue


def _format_residue(residue: dict[str, dict[str, int]]) -> str:
    parts: list[str] = []
    for run_key in sorted(residue):
        tables = residue[run_key]
        if not tables:
            continue
        body = ",".join(f"{name}:{count}" for name, count in sorted(tables.items()))
        parts.append(f"{run_key}[{body}]")
    return ";".join(parts) if parts else "none"


def collect_readiness_checks(
    *,
    run_key: str,
    promotion_report: Path | None = None,
) -> tuple[ReadinessCheck, ...]:
    base = str(run_key).strip()
    run_keys = (f"{base}-A", f"{base}-B") if base else ("", "")

    original_build_parser = v43.build_parser
    release_parser = _release_v43_parser_factory(original_build_parser)()
    defaults = _parser_defaults(release_parser)

    # Keep the historical guard, then add a stronger all-table residue audit below. Calling the
    # historical guard also ensures the route-research schema exists before the generic audit.
    historical_fresh = bool(base) and v68._fresh_run_preflight(run_keys)
    residue = _run_key_residue_counts(run_keys) if base else {}
    strict_fresh = historical_fresh and not any(residue.values())

    db_path = Path(settings.database_path)
    db_parent = db_path.parent if str(db_path.parent) else Path(".")
    explicit_rpc = bool(getenv("SOLANA_RPC_URL", "").strip())
    promotion_ok, promotion_detail = _signal_plane_promotion_check(
        promotion_report
    )

    checks = [
        ReadinessCheck("run_key_nonempty", bool(base), f"base={base or '<empty>'}"),
        ReadinessCheck(
            "fresh_v68_subcohort_keys",
            historical_fresh,
            f"run_keys={run_keys}",
        ),
        ReadinessCheck(
            "no_v68_run_key_residue",
            strict_fresh,
            f"residue={_format_residue(residue)}",
        ),
        ReadinessCheck(
            "jupiter_api_key_present",
            bool(settings.jupiter_api_key.strip()),
            "JUPITER_API_KEY=set" if settings.jupiter_api_key.strip() else "JUPITER_API_KEY=missing",
        ),
        ReadinessCheck(
            "explicit_primary_rpc_configured",
            explicit_rpc,
            "SOLANA_RPC_URL=explicit" if explicit_rpc else "SOLANA_RPC_URL=implicit_default_not_accepted_for_v68",
        ),
        ReadinessCheck(
            "rpc_url_present",
            bool(settings.rpc_url.strip()),
            "rpc_url=available" if settings.rpc_url.strip() else "rpc_url=missing",
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
            "signal_plane_episode_bridge_contract",
            _signal_plane_bridge_contract_check()[0],
            _signal_plane_bridge_contract_check()[1],
        ),
        ReadinessCheck(
            "signal_plane_v5_promotion_authorized",
            promotion_ok,
            promotion_detail,
        ),
        ReadinessCheck(
            "sqlite_admission_idle",
            sqlite_admission._GLOBAL_WRITE_ADMISSION.is_idle(),
            "shared SQLite writer admission has no active or waiting work",
        ),
    ]
    return tuple(checks)


def print_readiness(
    *,
    run_key: str,
    promotion_report: Path | None = None,
) -> bool:
    checks = collect_readiness_checks(
        run_key=run_key,
        promotion_report=promotion_report,
    )
    print("Crypto Copy Trader — V68 Release Readiness V1")
    print(f"systems_profile={V68_RELEASE_SYSTEMS_PROFILE}")
    for item in checks:
        print(f"{item.name}={'PASS' if item.passed else 'FAIL'} detail={item.detail}")
    passed = all(item.passed for item in checks)
    print(f"classification={'PASS_V68_RELEASE_READINESS_V1' if passed else 'FAIL_V68_RELEASE_READINESS_V1'}")
    return passed


async def _probe_logs_subscribe(name: str, request: dict) -> ReadinessCheck:
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        return ReadinessCheck(
            f"{name}_logs_subscribe",
            False,
            "websockets_dependency=missing",
        )

    try:
        ws_url = rpc_http_to_ws_url(settings.rpc_url)
        parsed = urlsplit(ws_url)
        endpoint = parsed.hostname or "<unknown>"
        async with connect(
            ws_url,
            ping_interval=None,
            ping_timeout=None,
            open_timeout=30,
            close_timeout=5,
            max_size=16 * 1024 * 1024,
            max_queue=1024,
        ) as websocket:
            await websocket.send(json.dumps(request))
            ack_raw = await asyncio.wait_for(websocket.recv(), timeout=20)
            ack = json.loads(ack_raw)
            if "error" in ack:
                error = ack.get("error")
                return ReadinessCheck(
                    f"{name}_logs_subscribe",
                    False,
                    f"endpoint={endpoint} ack_error={error}",
                )
            if not isinstance(ack.get("result"), int):
                return ReadinessCheck(
                    f"{name}_logs_subscribe",
                    False,
                    f"endpoint={endpoint} ack=invalid_subscription_id",
                )
            return ReadinessCheck(
                f"{name}_logs_subscribe",
                True,
                f"endpoint={endpoint} ack=subscription_id",
            )
    except Exception as exc:
        return ReadinessCheck(
            f"{name}_logs_subscribe",
            False,
            f"endpoint={locals().get('endpoint', '<unresolved>')} error={type(exc).__name__}:{exc}",
        )


async def _collect_provider_health_checks_async() -> tuple[ReadinessCheck, ...]:
    pump, pumpswap = await asyncio.gather(
        _probe_logs_subscribe(
            "pump",
            build_pump_logs_subscribe_request(commitment="confirmed"),
        ),
        _probe_logs_subscribe(
            "pumpswap",
            build_pumpswap_logs_subscribe_request(commitment="confirmed"),
        ),
    )
    return (pump, pumpswap)


def collect_provider_health_checks() -> tuple[ReadinessCheck, ...]:
    return asyncio.run(_collect_provider_health_checks_async())


def print_provider_health() -> bool:
    checks = collect_provider_health_checks()
    print("\nV68 SOLANA PUBSUB PROVIDER HEALTH")
    for item in checks:
        print(f"{item.name}={'PASS' if item.passed else 'FAIL'} detail={item.detail}")
    passed = all(item.passed for item in checks)
    print(
        "provider_health_classification="
        + ("PASS_V68_SOLANA_PUBSUB_HEALTH" if passed else "FAIL_V68_SOLANA_PUBSUB_HEALTH")
    )
    return passed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical V68 release entrypoint. Runs a fail-closed readiness check, then the frozen "
            "V68 A/B prospective route-only hypothesis through the promoted Signal Plane path. "
            "A fresh acquisition cannot start without a valid promotion manifest."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--bootstrap-report", type=Path)
    parser.add_argument("--signal-plane-promotion-report", type=Path)
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

    promotion_ok, _ = _signal_plane_promotion_check(
        args.signal_plane_promotion_report
    )
    if not print_readiness(
        run_key=base,
        promotion_report=args.signal_plane_promotion_report,
    ):
        return 2
    if not print_provider_health():
        return 2
    if args.preflight_only:
        return 0

    if promotion_ok:
        if args.bootstrap_report is None:
            print("classification=FAIL_V68_SIGNAL_PLANE_BOOTSTRAP_REQUIRED")
            print(
                "Interpretation: promoted Signal Plane V68 requires an explicit "
                "--bootstrap-report; acquisition did not start."
            )
            return 2
        original_v68_argv = list(sys.argv)
        try:
            sys.argv = [
                "route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0.py",
                "--run-key",
                base,
                "--bootstrap-report",
                str(args.bootstrap_report),
                "--promotion-report",
                str(args.signal_plane_promotion_report),
                "--hazard-start-interval-ms",
                str(args.hazard_start_interval_ms),
                "--entry-start-interval-ms",
                str(args.entry_start_interval_ms),
                "--exit-start-interval-ms",
                str(args.exit_start_interval_ms),
            ]
            return int(v68_signal_plane.main())
        finally:
            sys.argv = original_v68_argv

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
