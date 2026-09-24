from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import route_research_signal_plane_bridge_v0 as bridge
from src.config import settings
from src.database import connection
from src.market_opportunity_episode_store import (
    get_market_opportunity_episode,
)
from src.opportunity_episode_enrichment import (
    build_episode_enrichment_bundle,
)
from src.opportunity_route_research_store import (
    load_route_research_decision,
    load_route_research_outcomes,
)
from src.opportunity_wallet_market_history import (
    load_market_first_wallet_opportunity_history,
)
from src.route_research_forward_collection_900_v0 import (
    collect_route_research_forward_through_900_v0,
)


VERSION = "participant_quality_native_memory_v0"
PASS_BRIDGE = bridge.PASS_CLASSIFICATION
MEMORY_RUN_COUNT = 4
MEMORY_HORIZON_SECONDS = 900
MAX_EPISODES = 40
MIN_DECISIONS = 30
MIN_FINAL_COVERAGE_PCT = 50.0
MIN_AGGREGATE_AVAILABLE_M2_M4 = 30


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _strict_run_keys_fresh(
    run_keys: tuple[str, ...],
) -> tuple[bool, str]:
    residue: list[str] = []
    with connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for table_row in tables:
            table = str(table_row["name"])
            quoted = _quote_identifier(table)
            columns = conn.execute(
                f"PRAGMA table_info({quoted})"
            ).fetchall()
            if "acquisition_run_key" not in {
                str(row["name"]) for row in columns
            }:
                continue
            for run_key in run_keys:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {quoted} "
                    "WHERE acquisition_run_key=?",
                    (run_key,),
                ).fetchone()
                count = int(row["n"]) if row is not None else 0
                if count:
                    residue.append(
                        f"{run_key}:{table}:{count}"
                    )
    return not residue, (
        "none" if not residue else ";".join(sorted(residue))
    )


def _schedule_audit(run_key: str) -> tuple[int, int, bool]:
    outcomes = load_route_research_outcomes(
        acquisition_run_key=run_key
    )
    by_episode: dict[str, set[int]] = {}
    for item in outcomes:
        by_episode.setdefault(
            item.episode_key,
            set(),
        ).add(item.horizon_seconds)
    exact = bool(by_episode) and all(
        horizons == {300, 900, 3600}
        for horizons in by_episode.values()
    )
    return len(by_episode), len(outcomes), exact


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(
        value, (int, float)
    ):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _median_of_wallet_medians(associations) -> float | None:
    by_wallet: dict[str, list[float]] = defaultdict(list)
    for item in associations:
        value = _finite(
            item.executable_quote_return_pct
        )
        wallet = str(item.wallet_address).strip()
        if wallet and value is not None:
            by_wallet[wallet].append(value)
    medians = [
        float(median(values))
        for values in by_wallet.values()
        if values
    ]
    return float(median(medians)) if medians else None


def _participant_feature_for_episode(
    *,
    run_key: str,
    episode_key: str,
) -> dict[str, Any]:
    decision = load_route_research_decision(
        acquisition_run_key=run_key,
        episode_key=episode_key,
    )
    episode = get_market_opportunity_episode(episode_key)
    if decision is None or episode is None:
        return {
            "feature_value": None,
            "participant_wallet_count": 0,
            "wallets_with_history": 0,
            "history_coverage_pct": None,
            "association_count": 0,
            "status": "MISSING_DECISION_OR_EPISODE",
        }

    base_bundle = build_episode_enrichment_bundle(
        episode=episode,
        as_of=decision.research_decision_as_of,
    )
    participants = tuple(
        sorted(
            {
                row.wallet_address
                for row in base_bundle.wallet_intelligence.wallets
                if row.wallet_address
            }
        )
    )
    history = load_market_first_wallet_opportunity_history(
        current_episode=episode,
        current_participant_wallets=participants,
        horizon_seconds=MEMORY_HORIZON_SECONDS,
        history_cutoff=episode.first_trigger_observed_at,
    )
    value = _median_of_wallet_medians(history.associations)
    wallets_with_history = len(
        {
            item.wallet_address
            for item in history.associations
        }
    )
    coverage = (
        100.0 * wallets_with_history / len(participants)
        if participants else None
    )
    return {
        "feature_value": value,
        "participant_wallet_count": len(participants),
        "wallets_with_history": wallets_with_history,
        "history_coverage_pct": coverage,
        "association_count": len(history.associations),
        "status": (
            "AVAILABLE"
            if value is not None
            else "MISSING_HISTORY"
        ),
        "history_flags": list(history.data_quality_flags),
    }


def _coverage_audit(
    run_keys: tuple[str, ...],
) -> dict[str, Any]:
    by_run: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []

    for index, run_key in enumerate(run_keys, start=1):
        outcomes = load_route_research_outcomes(
            acquisition_run_key=run_key
        )
        episode_keys = sorted(
            {
                item.episode_key
                for item in outcomes
            }
        )
        rows = [
            {
                "run_index": index,
                "run_key": run_key,
                "episode_key": episode_key,
                **_participant_feature_for_episode(
                    run_key=run_key,
                    episode_key=episode_key,
                ),
            }
            for episode_key in episode_keys
        ]
        available = [
            row
            for row in rows
            if row["feature_value"] is not None
        ]
        by_run[run_key] = {
            "run_index": index,
            "episode_count": len(rows),
            "feature_available": len(available),
            "feature_availability_pct": (
                100.0 * len(available) / len(rows)
                if rows else None
            ),
        }
        all_rows.extend(rows)

    m2_m4_values = [
        float(row["feature_value"])
        for row in all_rows
        if row["run_index"] >= 2
        and row["feature_value"] is not None
    ]
    final = by_run[run_keys[-1]]
    ready = (
        final["feature_availability_pct"] is not None
        and final["feature_availability_pct"]
        >= MIN_FINAL_COVERAGE_PCT
        and len(m2_m4_values)
        >= MIN_AGGREGATE_AVAILABLE_M2_M4
    )
    cutoff = (
        float(median(m2_m4_values))
        if ready and m2_m4_values
        else None
    )
    return {
        "by_run": by_run,
        "rows": all_rows,
        "m2_m4_available_count": len(m2_m4_values),
        "m4_feature_availability_pct": (
            final["feature_availability_pct"]
        ),
        "readiness_checks": {
            "m4_coverage_gte_50_pct": (
                final["feature_availability_pct"] is not None
                and final["feature_availability_pct"]
                >= MIN_FINAL_COVERAGE_PCT
            ),
            "m2_m4_available_gte_30": (
                len(m2_m4_values)
                >= MIN_AGGREGATE_AVAILABLE_M2_M4
            ),
        },
        "outcome_blind_median_cutoff": cutoff,
        "favorable_direction": "HIGH",
        "ready": ready,
    }


def run_memory_build(
    *,
    base_run_key: str,
    bootstrap_report: Path,
    acquisition_duration_seconds: float = 120.0,
    artifact_root: Path = Path(
        "artifacts/participant_quality_native_memory_v0"
    ),
) -> dict[str, Any]:
    base = str(base_run_key).strip()
    if not base:
        raise ValueError("base_run_key cannot be empty")
    run_keys = tuple(
        f"{base}-M{index}"
        for index in range(1, MEMORY_RUN_COUNT + 1)
    )
    fresh, residue = _strict_run_keys_fresh(run_keys)
    if not fresh:
        return {
            "version": VERSION,
            "classification": (
                "FAIL_PARTICIPANT_MEMORY_RUN_KEY_NOT_FRESH"
            ),
            "run_keys": list(run_keys),
            "residue": residue,
        }

    artifact_root.mkdir(parents=True, exist_ok=True)
    run_reports: list[dict[str, Any]] = []

    for index, run_key in enumerate(run_keys, start=1):
        print(
            f"\n=== PARTICIPANT MEMORY M{index} "
            f"ACQUISITION START {run_key} ==="
        )
        shadow_out = artifact_root / (
            f"{run_key}-signal-plane-shadow.json"
        )
        bridge_out = artifact_root / (
            f"{run_key}-route-research-bridge.json"
        )
        bridge_report = asyncio.run(
            bridge.run_bridge(
                run_key=run_key,
                bootstrap_report=bootstrap_report,
                duration_seconds=acquisition_duration_seconds,
                shadow_output=shadow_out,
                report_output=bridge_out,
                max_episodes=MAX_EPISODES,
                research_notional_usd=25.0,
                research_slippage_bps=100,
                hazard_start_interval_ms=650,
                entry_start_interval_ms=1000,
            )
        )
        decisions, scheduled, exact_three = _schedule_audit(
            run_key
        )
        if (
            bridge_report.get("classification") != PASS_BRIDGE
            or decisions < MIN_DECISIONS
            or not exact_three
            or scheduled != decisions * 3
        ):
            return {
                "version": VERSION,
                "classification": (
                    "INCONCLUSIVE_PARTICIPANT_MEMORY_ACQUISITION"
                ),
                "failed_run_key": run_key,
                "bridge_classification": bridge_report.get(
                    "classification"
                ),
                "decision_count": decisions,
                "scheduled_count": scheduled,
                "exact_three_horizons": exact_three,
                "run_reports": run_reports,
            }

        print(
            f"=== PARTICIPANT MEMORY M{index} "
            "300/900 MATURITY ==="
        )
        forward = (
            collect_route_research_forward_through_900_v0(
                acquisition_run_key=run_key,
                api_key=settings.jupiter_api_key,
                exit_start_interval_ms=250,
            )
        )
        run_report = {
            "run_index": index,
            "run_key": run_key,
            "bridge_classification": bridge_report.get(
                "classification"
            ),
            "decision_count": decisions,
            "scheduled_count": scheduled,
            "forward_900_classification": (
                forward.classification
            ),
            "forward_900_statuses": (
                forward.statuses_target
            ),
            "forward_900_by_horizon": forward.by_horizon,
            "target_lateness_p95_seconds": (
                forward.target_lateness_p95_seconds
            ),
        }
        run_reports.append(run_report)
        if (
            forward.classification
            != "PASS_MEMORY_FORWARD_300_900_COMPLETE"
        ):
            return {
                "version": VERSION,
                "classification": (
                    "INCONCLUSIVE_PARTICIPANT_MEMORY_900_MATURITY"
                ),
                "failed_run_key": run_key,
                "run_reports": run_reports,
            }

    audit = _coverage_audit(run_keys)
    classification = (
        "READY_TO_PREREGISTER_NATIVE_PARTICIPANT_QUALITY_HOLDOUT"
        if audit["ready"]
        else "INCONCLUSIVE_NATIVE_PARTICIPANT_MEMORY_COVERAGE"
    )
    report = {
        "type": "participant_quality_native_memory_report",
        "version": VERSION,
        "classification": classification,
        "authorization": (
            "memory_build_only_no_economic_verdict_no_live_money"
        ),
        "run_keys": list(run_keys),
        "memory_horizon_seconds": MEMORY_HORIZON_SECONDS,
        "run_reports": run_reports,
        "coverage_audit": audit,
        "economic_outcomes_evaluated": False,
        "fresh_economic_holdout_started": False,
        "interpretation": (
            "READY means only that native causal participant-history "
            "coverage is sufficient to preregister a separate future "
            "holdout. It is not an edge verdict."
        ),
    }
    out = artifact_root / f"{base}-report.json"
    out.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report["artifact"] = str(out)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run-key", required=True)
    parser.add_argument(
        "--bootstrap-report",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=120.0,
    )
    args = parser.parse_args()

    report = run_memory_build(
        base_run_key=args.base_run_key,
        bootstrap_report=args.bootstrap_report,
        acquisition_duration_seconds=args.duration_seconds,
    )
    print("\nCrypto Copy Trader — Participant Quality Native Memory V0")
    print(f"classification={report.get('classification')}")
    print(f"run_keys={report.get('run_keys')}")
    for item in report.get("run_reports") or []:
        print(
            f"M{item['run_index']} "
            f"decisions={item['decision_count']} "
            f"bridge={item['bridge_classification']} "
            f"forward900={item['forward_900_classification']} "
            f"lateness_p95={item['target_lateness_p95_seconds']}"
        )
    audit = report.get("coverage_audit") or {}
    if audit:
        for key, value in (audit.get("by_run") or {}).items():
            print(
                f"COVERAGE {key} "
                f"episodes={value['episode_count']} "
                f"available={value['feature_available']} "
                f"pct={value['feature_availability_pct']}"
            )
        print(
            "M2_M4_AVAILABLE="
            f"{audit.get('m2_m4_available_count')}"
        )
        print(
            "M4_COVERAGE_PCT="
            f"{audit.get('m4_feature_availability_pct')}"
        )
        print(
            "OUTCOME_BLIND_MEDIAN_CUTOFF="
            f"{audit.get('outcome_blind_median_cutoff')}"
        )
        print(
            "FAVORABLE_DIRECTION="
            f"{audit.get('favorable_direction')}"
        )
    if report.get("artifact"):
        print(f"report={report['artifact']}")
    return 0 if str(report.get("classification", "")).startswith(
        "READY_"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
