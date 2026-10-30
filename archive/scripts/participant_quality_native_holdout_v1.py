from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

import route_research_signal_plane_bridge_v0 as bridge
from benchmarks.burst_selection_diagnostic_v0.run import (
    _metrics_dict,
    spearman_rank_correlation,
)
from participant_quality_native_memory_v1 import (
    VERSION as MEMORY_VERSION,
    _participant_feature_for_episode,
    _schedule_audit,
    _strict_run_keys_fresh,
)
from src.causal_quote_store import load_causal_quotes
from src.config import settings
from src.opportunity_route_research_store import (
    load_route_research_decision,
    load_route_research_outcomes,
)
from src.route_research_forward_collection_900_v0 import (
    collect_route_research_forward_through_900_v0,
)


VERSION = "participant_quality_native_holdout_v1_preregistered"
PASS_BRIDGE = bridge.PASS_CLASSIFICATION

MEMORY_REPORT_CLASSIFICATION = (
    "READY_TO_PREREGISTER_NATIVE_PARTICIPANT_QUALITY_HOLDOUT"
)
MEMORY_RUN_KEYS = (
    "participant-quality-native-memory-rolefix-20260924-03-M1",
    "participant-quality-native-memory-rolefix-20260924-03-M2",
    "participant-quality-native-memory-rolefix-20260924-03-M3",
    "participant-quality-native-memory-rolefix-20260924-03-M4",
)
FEATURE_NAME = (
    "native_participant_prior_900_route_quote_return_"
    "median_of_wallet_medians_pct"
)
FROZEN_CUTOFF = -65.65233776856643
FAVORABLE_GROUP = "HIGH"
PRIMARY_HORIZON_SECONDS = 900
HOLDOUT_RUN_COUNT = 2
MAX_EPISODES = 40
MIN_DECISIONS_PER_COHORT = 30
MIN_FEATURE_COVERAGE_PCT_PER_COHORT = 50.0
MIN_PAIRED_TOTAL = 40
MIN_GROUP_TOTAL = 15
MIN_GROUP_SUPPORT_PER_COHORT = 5
CATASTROPHIC_RETURN_PCT = -80.0


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _metric_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if not math.isnan(number) else None
    if value == "INF":
        return math.inf
    if value == "-INF":
        return -math.inf
    return None


def group_for_feature(value: float | None) -> str | None:
    if value is None:
        return None
    return "HIGH" if float(value) > FROZEN_CUTOFF else "LOW"


def _one_quote(quote_key: str):
    rows = load_causal_quotes(quote_keys=(str(quote_key),))
    return rows[0] if len(rows) == 1 else None


def _current_900_return(
    *,
    run_key: str,
    episode_key: str,
) -> tuple[float | None, str]:
    decision = load_route_research_decision(
        acquisition_run_key=run_key,
        episode_key=episode_key,
    )
    if decision is None:
        return None, "MISSING_DECISION"

    outcomes = {
        (item.episode_key, item.horizon_seconds): item
        for item in load_route_research_outcomes(
            acquisition_run_key=run_key
        )
    }
    outcome = outcomes.get(
        (episode_key, PRIMARY_HORIZON_SECONDS)
    )
    if outcome is None:
        return None, "MISSING_900_OUTCOME"
    if outcome.status != "AVAILABLE":
        return None, f"OUTCOME_{outcome.status}"

    entry = _one_quote(decision.entry_quote_key)
    exit_quote = _one_quote(str(outcome.quote_key or ""))
    if entry is None or exit_quote is None:
        return None, "MISSING_ROUTE_QUOTE"
    if (
        entry.side != "buy"
        or exit_quote.side != "sell"
        or bool(entry.executable)
        or bool(exit_quote.executable)
    ):
        return None, "INVALID_ROUTE_QUOTE_SEMANTICS"
    if (
        int(entry.observed_at)
        > int(decision.research_decision_as_of)
        or outcome.observed_at is None
        or int(exit_quote.observed_at) > int(outcome.observed_at)
    ):
        return None, "ROUTE_QUOTE_CLOCK_VIOLATION"

    entry_price = _finite(entry.price_usd)
    exit_price = _finite(exit_quote.price_usd)
    if (
        entry_price is None
        or exit_price is None
        or entry_price <= 0
        or exit_price <= 0
    ):
        return None, "INVALID_ROUTE_QUOTE_PRICE"

    value = 100.0 * (exit_price / entry_price - 1.0)
    if not math.isfinite(value):
        return None, "NONFINITE_RETURN"
    return value, "AVAILABLE"


def _feature_rows_for_run(run_key: str) -> list[dict[str, Any]]:
    outcomes = load_route_research_outcomes(
        acquisition_run_key=run_key
    )
    episode_keys = sorted(
        {
            item.episode_key
            for item in outcomes
            if item.horizon_seconds == PRIMARY_HORIZON_SECONDS
        }
    )
    rows: list[dict[str, Any]] = []
    for episode_key in episode_keys:
        feature = _participant_feature_for_episode(
            run_key=run_key,
            episode_key=episode_key,
            allowed_history_run_keys=MEMORY_RUN_KEYS,
        )
        feature_value = _finite(feature.get("feature_value"))
        outcome_value, outcome_status = _current_900_return(
            run_key=run_key,
            episode_key=episode_key,
        )
        rows.append(
            {
                "run_key": run_key,
                "episode_key": episode_key,
                "feature_value": feature_value,
                "group": group_for_feature(feature_value),
                "feature_status": feature.get("status"),
                "participant_wallet_count": feature.get(
                    "participant_wallet_count"
                ),
                "wallets_with_history": feature.get(
                    "wallets_with_history"
                ),
                "history_coverage_pct": feature.get(
                    "history_coverage_pct"
                ),
                "association_count": feature.get(
                    "association_count"
                ),
                "outcome_900_return_pct": outcome_value,
                "outcome_status": outcome_status,
            }
        )
    return rows


def _tail_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return (
        100.0
        * sum(value <= CATASTROPHIC_RETURN_PCT for value in values)
        / len(values)
    )


def _group_metrics(values: list[float]) -> dict[str, Any]:
    return {
        **_metrics_dict(values),
        "catastrophic_loss_count": sum(
            value <= CATASTROPHIC_RETURN_PCT
            for value in values
        ),
        "catastrophic_loss_rate_pct": _tail_rate(values),
    }


def evaluate_rows(
    rows_by_cohort: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    cohort_reports: dict[str, Any] = {}
    paired_all: list[dict[str, Any]] = []

    for cohort, rows in rows_by_cohort.items():
        known = [
            row
            for row in rows
            if row.get("feature_value") is not None
        ]
        paired = [
            row
            for row in known
            if row.get("outcome_900_return_pct") is not None
            and row.get("group") in {"HIGH", "LOW"}
        ]
        paired_all.extend(paired)

        groups = {
            group: [
                float(row["outcome_900_return_pct"])
                for row in paired
                if row["group"] == group
            ]
            for group in ("HIGH", "LOW")
        }
        coverage_pct = (
            100.0 * len(known) / len(rows)
            if rows else None
        )
        cohort_reports[cohort] = {
            "episodes": len(rows),
            "feature_known": len(known),
            "feature_coverage_pct": coverage_pct,
            "paired": len(paired),
            "groups": {
                group: _group_metrics(values)
                for group, values in groups.items()
            },
        }

    xs = [
        float(row["feature_value"])
        for row in paired_all
    ]
    ys = [
        float(row["outcome_900_return_pct"])
        for row in paired_all
    ]
    aggregate_groups = {
        group: [
            float(row["outcome_900_return_pct"])
            for row in paired_all
            if row["group"] == group
        ]
        for group in ("HIGH", "LOW")
    }
    aggregate = {
        "paired": len(paired_all),
        "spearman": spearman_rank_correlation(xs, ys),
        "groups": {
            group: _group_metrics(values)
            for group, values in aggregate_groups.items()
        },
    }

    support_checks = {
        "feature_coverage_gte_50_pct_each": all(
            report["feature_coverage_pct"] is not None
            and report["feature_coverage_pct"]
            >= MIN_FEATURE_COVERAGE_PCT_PER_COHORT
            for report in cohort_reports.values()
        ),
        "paired_total_gte_40": (
            aggregate["paired"] >= MIN_PAIRED_TOTAL
        ),
        "high_total_gte_15": (
            aggregate["groups"]["HIGH"]["n"]
            >= MIN_GROUP_TOTAL
        ),
        "low_total_gte_15": (
            aggregate["groups"]["LOW"]["n"]
            >= MIN_GROUP_TOTAL
        ),
        "group_support_gte_5_each_cohort": all(
            report["groups"]["HIGH"]["n"]
            >= MIN_GROUP_SUPPORT_PER_COHORT
            and report["groups"]["LOW"]["n"]
            >= MIN_GROUP_SUPPORT_PER_COHORT
            for report in cohort_reports.values()
        ),
    }

    high = aggregate["groups"]["HIGH"]
    low = aggregate["groups"]["LOW"]
    rho = _metric_number(aggregate["spearman"])

    median_high = _metric_number(high["median_return_pct"])
    median_low = _metric_number(low["median_return_pct"])
    mean_wo_best_high = _metric_number(
        high["mean_without_best_pct"]
    )
    mean_wo_best_low = _metric_number(
        low["mean_without_best_pct"]
    )
    pf_high = _metric_number(high["profit_factor"])
    pf_low = _metric_number(low["profit_factor"])
    tail_high = _metric_number(
        high["catastrophic_loss_rate_pct"]
    )
    tail_low = _metric_number(
        low["catastrophic_loss_rate_pct"]
    )

    effect_checks = {
        "aggregate_spearman_positive": (
            rho is not None and rho > 0
        ),
        "aggregate_high_median_gt_low": (
            median_high is not None
            and median_low is not None
            and median_high > median_low
        ),
        "high_median_gt_low_each_cohort": all(
            (
                _metric_number(
                    report["groups"]["HIGH"][
                        "median_return_pct"
                    ]
                )
                is not None
                and _metric_number(
                    report["groups"]["LOW"][
                        "median_return_pct"
                    ]
                )
                is not None
                and float(
                    report["groups"]["HIGH"][
                        "median_return_pct"
                    ]
                )
                > float(
                    report["groups"]["LOW"][
                        "median_return_pct"
                    ]
                )
            )
            for report in cohort_reports.values()
        ),
        "aggregate_high_mean_without_best_gt_low": (
            mean_wo_best_high is not None
            and mean_wo_best_low is not None
            and mean_wo_best_high > mean_wo_best_low
        ),
        "aggregate_high_profit_factor_gt_low": (
            pf_high is not None
            and pf_low is not None
            and pf_high > pf_low
        ),
        "aggregate_high_catastrophic_tail_not_worse": (
            tail_high is not None
            and tail_low is not None
            and tail_high <= tail_low
        ),
    }

    support_ok = all(support_checks.values())
    effect_ok = all(effect_checks.values())
    if not support_ok:
        classification = (
            "INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_HOLDOUT_SUPPORT"
        )
    elif effect_ok:
        classification = (
            "KEEP_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE"
        )
    else:
        classification = (
            "KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE"
        )

    return {
        "classification": classification,
        "cohorts": cohort_reports,
        "aggregate": aggregate,
        "support_checks": support_checks,
        "effect_checks": effect_checks,
    }


def _validate_memory_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("version") != MEMORY_VERSION:
        raise ValueError("memory report version mismatch")
    if (
        report.get("classification")
        != MEMORY_REPORT_CLASSIFICATION
    ):
        raise ValueError("memory report is not holdout-ready")
    if tuple(report.get("run_keys") or ()) != MEMORY_RUN_KEYS:
        raise ValueError("memory run keys do not match preregistration")
    audit = report.get("coverage_audit") or {}
    cutoff = _finite(
        audit.get("outcome_blind_median_cutoff")
    )
    if cutoff is None or cutoff != FROZEN_CUTOFF:
        raise ValueError("frozen cutoff mismatch")
    if audit.get("favorable_direction") != FAVORABLE_GROUP:
        raise ValueError("favorable direction mismatch")
    return report


def run_holdout(
    *,
    base_run_key: str,
    memory_report: Path,
    bootstrap_report: Path,
    acquisition_duration_seconds: float = 120.0,
    artifact_root: Path = Path(
        "artifacts/participant_quality_native_holdout_v1"
    ),
) -> dict[str, Any]:
    _validate_memory_report(memory_report)

    base = str(base_run_key).strip()
    if not base:
        raise ValueError("base_run_key cannot be empty")
    run_keys = tuple(
        f"{base}-H{index}"
        for index in range(1, HOLDOUT_RUN_COUNT + 1)
    )
    fresh, residue = _strict_run_keys_fresh(run_keys)
    if not fresh:
        return {
            "version": VERSION,
            "classification": (
                "FAIL_PARTICIPANT_HOLDOUT_RUN_KEY_NOT_FRESH"
            ),
            "run_keys": list(run_keys),
            "residue": residue,
        }

    artifact_root.mkdir(parents=True, exist_ok=True)
    acquisition_reports: list[dict[str, Any]] = []

    for index, run_key in enumerate(run_keys, start=1):
        print(
            f"\n=== PARTICIPANT QUALITY HOLDOUT H{index} "
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
            or decisions < MIN_DECISIONS_PER_COHORT
            or not exact_three
            or scheduled != decisions * 3
        ):
            return {
                "version": VERSION,
                "classification": (
                    "INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_"
                    "HOLDOUT_ACQUISITION"
                ),
                "failed_run_key": run_key,
                "bridge_classification": bridge_report.get(
                    "classification"
                ),
                "decision_count": decisions,
                "scheduled_count": scheduled,
                "exact_three_horizons": exact_three,
                "acquisition_reports": acquisition_reports,
            }

        print(
            f"=== PARTICIPANT QUALITY HOLDOUT H{index} "
            "300/900 MATURITY ==="
        )
        forward = collect_route_research_forward_through_900_v0(
            acquisition_run_key=run_key,
            api_key=settings.jupiter_api_key,
            exit_start_interval_ms=250,
        )
        acquisition_reports.append(
            {
                "cohort": f"H{index}",
                "run_key": run_key,
                "bridge_classification": bridge_report.get(
                    "classification"
                ),
                "decision_count": decisions,
                "scheduled_count": scheduled,
                "forward_900_classification": (
                    forward.classification
                ),
                "forward_900_statuses": forward.statuses_target,
                "target_lateness_p95_seconds": (
                    forward.target_lateness_p95_seconds
                ),
            }
        )
        if (
            forward.classification
            != "PASS_MEMORY_FORWARD_300_900_COMPLETE"
        ):
            return {
                "version": VERSION,
                "classification": (
                    "INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_"
                    "HOLDOUT_900_MATURITY"
                ),
                "failed_run_key": run_key,
                "acquisition_reports": acquisition_reports,
            }

    rows_by_cohort = {
        f"H{index}": _feature_rows_for_run(run_key)
        for index, run_key in enumerate(run_keys, start=1)
    }
    evaluation = evaluate_rows(rows_by_cohort)

    report = {
        "type": "participant_quality_native_holdout_report",
        "version": VERSION,
        "classification": evaluation["classification"],
        "authorization": (
            "prospective_paper_research_no_live_money_"
            "selection_edge_candidate_only"
        ),
        "memory_report": str(memory_report),
        "memory_run_keys": list(MEMORY_RUN_KEYS),
        "holdout_run_keys": list(run_keys),
        "feature_name": FEATURE_NAME,
        "frozen_cutoff": FROZEN_CUTOFF,
        "group_rule": (
            "HIGH if feature > cutoff; LOW if feature <= cutoff; "
            "missing remains unclassified"
        ),
        "favorable_group": FAVORABLE_GROUP,
        "primary_horizon_seconds": PRIMARY_HORIZON_SECONDS,
        "catastrophic_return_threshold_pct": (
            CATASTROPHIC_RETURN_PCT
        ),
        "acquisition_reports": acquisition_reports,
        "rows": rows_by_cohort,
        **evaluation,
        "economic_hypothesis_modified": False,
        "scientific_thresholds_modified": False,
        "interpretation": (
            "KEEP promotes Participant Quality only to an independent "
            "replication candidate. It is not mature edge and does not "
            "authorize live-money execution. KILL closes this frozen "
            "selection rule. INCONCLUSIVE permits no economic verdict."
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


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def print_summary(report: dict[str, Any]) -> None:
    print(
        "\nCrypto Copy Trader — Native Participant Quality "
        "Prospective Holdout V1"
    )
    print(f"classification={report.get('classification')}")
    print(f"holdout_run_keys={report.get('holdout_run_keys')}")
    for item in report.get("acquisition_reports") or []:
        print(
            f"{item['cohort']} decisions={item['decision_count']} "
            f"bridge={item['bridge_classification']} "
            f"forward900={item['forward_900_classification']} "
            f"lateness_p95={item['target_lateness_p95_seconds']}"
        )

    cohorts = report.get("cohorts") or {}
    for name in ("H1", "H2"):
        item = cohorts.get(name)
        if not item:
            continue
        print(
            f"{name}_COVERAGE episodes={item['episodes']} "
            f"known={item['feature_known']} "
            f"pct={_fmt(item['feature_coverage_pct'])} "
            f"paired={item['paired']} "
            f"HIGH_n={item['groups']['HIGH']['n']} "
            f"LOW_n={item['groups']['LOW']['n']} "
            f"HIGH_median={_fmt(item['groups']['HIGH']['median_return_pct'])} "
            f"LOW_median={_fmt(item['groups']['LOW']['median_return_pct'])}"
        )

    aggregate = report.get("aggregate") or {}
    if aggregate:
        high = aggregate["groups"]["HIGH"]
        low = aggregate["groups"]["LOW"]
        print(
            "AGGREGATE "
            f"paired={aggregate['paired']} "
            f"spearman={_fmt(aggregate['spearman'])} "
            f"HIGH_n={high['n']} LOW_n={low['n']} "
            f"HIGH_median={_fmt(high['median_return_pct'])} "
            f"LOW_median={_fmt(low['median_return_pct'])} "
            f"HIGH_PF={_fmt(high['profit_factor'])} "
            f"LOW_PF={_fmt(low['profit_factor'])} "
            f"HIGH_mean_wo_best={_fmt(high['mean_without_best_pct'])} "
            f"LOW_mean_wo_best={_fmt(low['mean_without_best_pct'])} "
            f"HIGH_tail={_fmt(high['catastrophic_loss_rate_pct'])} "
            f"LOW_tail={_fmt(low['catastrophic_loss_rate_pct'])}"
        )

    for key, value in (report.get("support_checks") or {}).items():
        print(f"SUPPORT_CHECK {key}={value}")
    for key, value in (report.get("effect_checks") or {}).items():
        print(f"EFFECT_CHECK {key}={value}")
    if report.get("artifact"):
        print(f"report={report['artifact']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run-key", required=True)
    parser.add_argument(
        "--memory-report",
        required=True,
        type=Path,
    )
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

    report = run_holdout(
        base_run_key=args.base_run_key,
        memory_report=args.memory_report,
        bootstrap_report=args.bootstrap_report,
        acquisition_duration_seconds=args.duration_seconds,
    )
    print_summary(report)
    return 0 if str(report.get("classification", "")).startswith(
        ("KEEP_", "KILL_")
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
