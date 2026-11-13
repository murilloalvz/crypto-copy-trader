from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

from benchmarks.burst_selection_diagnostic_v0.run import (
    _finite_number,
    _metrics_dict,
    _safe_number,
    _scope_rows,
    spearman_rank_correlation,
    tercile_cutpoints,
    tercile_group,
)
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.route_research_early_opportunity_v55 import (
    build_early_opportunity_dataset_v55,
)


VERSION = "burst_participation_structure_discovery_v0"
CLASSIFICATION = "DIAGNOSTIC_ONLY_NO_FRESH_VERDICT"
PRIMARY_HORIZON_SECONDS = 900
CATASTROPHIC_RETURN_PCT = -80.0
MIN_COVERAGE_PCT_PER_SUBCOHORT = 80.0
MIN_EXTREME_SUPPORT_PER_SUBCOHORT = 5

FEATURE_NAMES = (
    "flow30_top1_wallet_event_share_pct",
    "flow30_top3_wallet_event_share_pct",
    "flow60_top1_wallet_event_share_pct",
    "flow60_top3_wallet_event_share_pct",
    "flow30_buy_sell_wallet_overlap_share_pct",
    "flow60_buy_sell_wallet_overlap_share_pct",
)


def _window_features(row, window_seconds: int) -> dict[str, float | None]:
    episode = get_market_opportunity_episode(row.episode_key)
    if episode is None:
        return {
            "top1": None,
            "top3": None,
            "overlap": None,
        }

    stored = load_market_trades(
        acquisition_run_key=row.acquisition_run_key,
        token_mint=row.token_mint,
        as_of=row.research_decision_as_of,
    )
    chain_as_of = max(
        [episode.first_trigger_chain_time]
        + [item.observation.chain_time for item in stored]
    )
    lower = chain_as_of - int(window_seconds)
    eligible = [
        item
        for item in stored
        if lower < item.observation.chain_time <= chain_as_of
        and item.observation.observed_at <= row.research_decision_as_of
    ]
    if not eligible:
        return {
            "top1": None,
            "top3": None,
            "overlap": None,
        }

    if any(item.observation.wallet_address is None for item in eligible):
        return {
            "top1": None,
            "top3": None,
            "overlap": None,
        }

    wallet_counts = Counter(
        str(item.observation.wallet_address)
        for item in eligible
        if item.observation.wallet_address is not None
    )
    ordered = sorted(wallet_counts.values(), reverse=True)
    total = len(eligible)
    top1 = 100.0 * ordered[0] / total if ordered else None
    top3 = 100.0 * sum(ordered[:3]) / total if ordered else None

    buy_wallets = {
        str(item.observation.wallet_address)
        for item in eligible
        if item.observation.side == "buy"
        and item.observation.wallet_address is not None
    }
    sell_wallets = {
        str(item.observation.wallet_address)
        for item in eligible
        if item.observation.side == "sell"
        and item.observation.wallet_address is not None
    }
    unique_wallets = set(wallet_counts)
    overlap = (
        100.0 * len(buy_wallets & sell_wallets) / len(unique_wallets)
        if unique_wallets
        else None
    )
    return {
        "top1": top1,
        "top3": top3,
        "overlap": overlap,
    }


def _feature_matrix(rows):
    values: dict[str, dict[tuple[str, str], float | None]] = {
        name: {} for name in FEATURE_NAMES
    }
    for row in rows:
        key = (row.acquisition_run_key, row.episode_key)
        w30 = _window_features(row, 30)
        w60 = _window_features(row, 60)
        values["flow30_top1_wallet_event_share_pct"][key] = w30["top1"]
        values["flow30_top3_wallet_event_share_pct"][key] = w30["top3"]
        values["flow60_top1_wallet_event_share_pct"][key] = w60["top1"]
        values["flow60_top3_wallet_event_share_pct"][key] = w60["top3"]
        values["flow30_buy_sell_wallet_overlap_share_pct"][key] = w30["overlap"]
        values["flow60_buy_sell_wallet_overlap_share_pct"][key] = w60["overlap"]
    return values


def _tail_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return 100.0 * sum(
        item <= CATASTROPHIC_RETURN_PCT for item in values
    ) / len(values)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _group_report(values: list[float]) -> dict[str, Any]:
    return {
        **_metrics_dict(values),
        "catastrophic_loss_count": sum(
            item <= CATASTROPHIC_RETURN_PCT for item in values
        ),
        "catastrophic_loss_rate_pct": _tail_rate(values),
    }


def _feature_report(rows, feature_name: str, feature_values):
    known = [
        float(value)
        for value in feature_values.values()
        if value is not None
    ]
    coverage: dict[str, Any] = {}
    for scope in ("A", "B", "ALL"):
        scoped = _scope_rows(rows, scope)
        known_count = sum(
            feature_values[
                (row.acquisition_run_key, row.episode_key)
            ]
            is not None
            for row in scoped
        )
        coverage[scope] = {
            "known": known_count,
            "total": len(scoped),
            "pct": (
                100.0 * known_count / len(scoped)
                if scoped else None
            ),
        }

    if not known:
        return {
            "feature": feature_name,
            "coverage": coverage,
            "cutpoints": None,
            "scopes": {},
            "candidate": False,
            "candidate_checks": {},
        }

    low_cut, high_cut = tercile_cutpoints(known)
    assignments = {
        key: (
            tercile_group(float(value), low_cut, high_cut)
            if value is not None
            else None
        )
        for key, value in feature_values.items()
    }

    scopes: dict[str, Any] = {}
    for scope in ("A", "B", "ALL"):
        scoped = _scope_rows(rows, scope)
        xs: list[float] = []
        ys: list[float] = []
        groups = {"LOW": [], "MID": [], "HIGH": []}

        for row in scoped:
            key = (row.acquisition_run_key, row.episode_key)
            feature = feature_values[key]
            outcome = _finite_number(
                row.labels.get(PRIMARY_HORIZON_SECONDS)
            )
            if feature is None or outcome is None:
                continue
            xs.append(float(feature))
            ys.append(float(outcome))
            group = assignments[key]
            if group is not None:
                groups[group].append(float(outcome))

        scopes[scope] = {
            "paired": len(ys),
            "spearman": _safe_number(
                spearman_rank_correlation(xs, ys)
            ),
            "groups": {
                group: _group_report(group_values)
                for group, group_values in groups.items()
            },
        }

    rho_all = _numeric(scopes["ALL"]["spearman"])
    direction = (
        "HIGH" if rho_all is not None and rho_all > 0
        else ("LOW" if rho_all is not None and rho_all < 0 else None)
    )
    opposite = (
        "LOW" if direction == "HIGH"
        else ("HIGH" if direction == "LOW" else None)
    )

    coverage_ok = all(
        coverage[scope]["pct"] is not None
        and coverage[scope]["pct"] >= MIN_COVERAGE_PCT_PER_SUBCOHORT
        for scope in ("A", "B")
    )
    support_ok = False
    same_direction = False
    median_better = False
    tail_better = False
    mean_wo_best_better = False
    pf_better = False

    if direction is not None and opposite is not None and rho_all is not None:
        rho_a = _numeric(scopes["A"]["spearman"])
        rho_b = _numeric(scopes["B"]["spearman"])
        same_direction = (
            rho_a is not None
            and rho_b is not None
            and rho_a * rho_all > 0
            and rho_b * rho_all > 0
        )
        support_ok = all(
            scopes[scope]["groups"][direction]["n"]
            >= MIN_EXTREME_SUPPORT_PER_SUBCOHORT
            and scopes[scope]["groups"][opposite]["n"]
            >= MIN_EXTREME_SUPPORT_PER_SUBCOHORT
            for scope in ("A", "B")
        )
        median_better = all(
            _numeric(scopes[scope]["groups"][direction]["median_return_pct"])
            is not None
            and _numeric(scopes[scope]["groups"][opposite]["median_return_pct"])
            is not None
            and float(scopes[scope]["groups"][direction]["median_return_pct"])
            > float(scopes[scope]["groups"][opposite]["median_return_pct"])
            for scope in ("A", "B")
        )
        tail_better = all(
            _numeric(scopes[scope]["groups"][direction]["catastrophic_loss_rate_pct"])
            is not None
            and _numeric(scopes[scope]["groups"][opposite]["catastrophic_loss_rate_pct"])
            is not None
            and float(scopes[scope]["groups"][direction]["catastrophic_loss_rate_pct"])
            < float(scopes[scope]["groups"][opposite]["catastrophic_loss_rate_pct"])
            for scope in ("A", "B")
        )
        mean_wo_best_better = all(
            _numeric(scopes[scope]["groups"][direction]["mean_without_best_pct"])
            is not None
            and _numeric(scopes[scope]["groups"][opposite]["mean_without_best_pct"])
            is not None
            and float(scopes[scope]["groups"][direction]["mean_without_best_pct"])
            > float(scopes[scope]["groups"][opposite]["mean_without_best_pct"])
            for scope in ("A", "B")
        )
        pf_better = all(
            _numeric(scopes[scope]["groups"][direction]["profit_factor"])
            is not None
            and _numeric(scopes[scope]["groups"][opposite]["profit_factor"])
            is not None
            and float(scopes[scope]["groups"][direction]["profit_factor"])
            > float(scopes[scope]["groups"][opposite]["profit_factor"])
            for scope in ("A", "B")
        )

    checks = {
        "coverage_gte_80_pct_both": coverage_ok,
        "extreme_support_both": support_ok,
        "spearman_same_direction_a_b_all": same_direction,
        "favorable_median_better_both": median_better,
        "favorable_catastrophic_tail_lower_both": tail_better,
        "favorable_mean_without_best_better_both": mean_wo_best_better,
        "favorable_pf_better_both": pf_better,
    }
    candidate = all(checks.values())

    weakest_tail_reduction = None
    weakest_median_separation = None
    weakest_mean_wo_best_improvement = None
    if direction is not None and opposite is not None:
        tail_reductions = []
        median_separations = []
        mean_improvements = []
        for scope in ("A", "B"):
            fav = scopes[scope]["groups"][direction]
            opp = scopes[scope]["groups"][opposite]
            if (
                _numeric(fav["catastrophic_loss_rate_pct"]) is not None
                and _numeric(opp["catastrophic_loss_rate_pct"]) is not None
            ):
                tail_reductions.append(
                    float(opp["catastrophic_loss_rate_pct"])
                    - float(fav["catastrophic_loss_rate_pct"])
                )
            if (
                _numeric(fav["median_return_pct"]) is not None
                and _numeric(opp["median_return_pct"]) is not None
            ):
                median_separations.append(
                    float(fav["median_return_pct"])
                    - float(opp["median_return_pct"])
                )
            if (
                _numeric(fav["mean_without_best_pct"]) is not None
                and _numeric(opp["mean_without_best_pct"]) is not None
            ):
                mean_improvements.append(
                    float(fav["mean_without_best_pct"])
                    - float(opp["mean_without_best_pct"])
                )
        if len(tail_reductions) == 2:
            weakest_tail_reduction = min(tail_reductions)
        if len(median_separations) == 2:
            weakest_median_separation = min(median_separations)
        if len(mean_improvements) == 2:
            weakest_mean_wo_best_improvement = min(mean_improvements)

    return {
        "feature": feature_name,
        "coverage": coverage,
        "cutpoints": {
            "low_max": low_cut,
            "mid_max": high_cut,
            "method": "outcome_blind_global_feature_terciles",
        },
        "scopes": scopes,
        "favorable_extreme": direction,
        "opposite_extreme": opposite,
        "candidate_checks": checks,
        "candidate": candidate,
        "ranking_inputs": {
            "weakest_subcohort_tail_reduction_pct_points": weakest_tail_reduction,
            "weakest_subcohort_median_separation_pct_points": weakest_median_separation,
            "weakest_subcohort_mean_without_best_improvement_pct_points": (
                weakest_mean_wo_best_improvement
            ),
            "abs_aggregate_spearman": (
                abs(rho_all) if rho_all is not None else None
            ),
        },
    }


def _candidate_sort_key(item: dict[str, Any]):
    rank = item["ranking_inputs"]
    return (
        -float(rank["weakest_subcohort_tail_reduction_pct_points"]),
        -float(rank["weakest_subcohort_median_separation_pct_points"]),
        -float(rank["weakest_subcohort_mean_without_best_improvement_pct_points"]),
        -float(rank["abs_aggregate_spearman"]),
        str(item["feature"]),
    )


def build_report(run_keys: tuple[str, str]) -> dict[str, Any]:
    dataset = build_early_opportunity_dataset_v55(
        acquisition_run_keys=run_keys
    )
    rows = dataset.rows
    matrix = _feature_matrix(rows)
    reports = {
        feature: _feature_report(rows, feature, matrix[feature])
        for feature in FEATURE_NAMES
    }
    candidates = [
        report for report in reports.values()
        if report["candidate"]
    ]
    candidates.sort(key=_candidate_sort_key)

    return {
        "type": "burst_participation_structure_discovery_report",
        "version": VERSION,
        "classification": CLASSIFICATION,
        "authorization": (
            "retrospective_discovery_on_consumed_v68_03_not_replacement_validation"
        ),
        "run_keys": list(run_keys),
        "rows_total": len(rows),
        "dataset_quality": {
            "lineage_violations": dataset.base.lineage_violations,
            "augmentation_failures": dataset.augmentation_failures,
            "feature_clock_violations": dataset.feature_clock_violations,
        },
        "feature_family": "participant_structure_coordination_descriptive",
        "excluded_prior_features": [
            "flow30_repeated_wallet_event_share_pct",
            "flow60_repeated_wallet_event_share_pct",
            "flow60_buy_share_pct",
            "decision_delay_seconds",
        ],
        "catastrophic_return_threshold_pct": CATASTROPHIC_RETURN_PCT,
        "feature_reports": reports,
        "candidate_ranking": [
            report["feature"] for report in candidates
        ],
        "selected_candidate_for_future_preregistration": (
            candidates[0]["feature"] if candidates else None
        ),
        "scientific_note": (
            "The v68 -03 rows are discovery-only here. No selected feature "
            "is validated. At most rank #1 may be frozen in a separate future "
            "holdout protocol before any new acquisition."
        ),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_summary(report: dict[str, Any]) -> None:
    print("Crypto Copy Trader — Burst Participation Structure Discovery V0")
    print(f"classification={report['classification']}")
    print(f"rows_total={report['rows_total']}")
    q = report["dataset_quality"]
    print(
        "dataset_quality="
        f"lineage_violations={q['lineage_violations']} "
        f"augmentation_failures={q['augmentation_failures']} "
        f"feature_clock_violations={q['feature_clock_violations']}"
    )
    print(
        f"catastrophic_threshold={report['catastrophic_return_threshold_pct']:.1f}%"
    )

    print("\n=== FEATURES ===")
    for name in FEATURE_NAMES:
        feature = report["feature_reports"][name]
        cov_a = feature["coverage"]["A"]["pct"]
        cov_b = feature["coverage"]["B"]["pct"]
        if not feature["scopes"]:
            print(
                f"FEATURE={name} coverage_A={_fmt(cov_a)} "
                f"coverage_B={_fmt(cov_b)} DATA=INSUFFICIENT"
            )
            continue
        direction = feature["favorable_extreme"]
        opposite = feature["opposite_extreme"]
        if direction is None or opposite is None:
            print(
                f"FEATURE={name} coverage_A={_fmt(cov_a)} "
                f"coverage_B={_fmt(cov_b)} "
                f"rho_A={_fmt(feature['scopes']['A']['spearman'])} "
                f"rho_B={_fmt(feature['scopes']['B']['spearman'])} "
                f"rho_ALL={_fmt(feature['scopes']['ALL']['spearman'])} "
                "direction=NONE CANDIDATE=False"
            )
            continue
        a_fav = feature["scopes"]["A"]["groups"][direction]
        a_opp = feature["scopes"]["A"]["groups"][opposite]
        b_fav = feature["scopes"]["B"]["groups"][direction]
        b_opp = feature["scopes"]["B"]["groups"][opposite]
        print(
            f"FEATURE={name} "
            f"coverage_A={_fmt(cov_a)} coverage_B={_fmt(cov_b)} "
            f"rho_A={_fmt(feature['scopes']['A']['spearman'])} "
            f"rho_B={_fmt(feature['scopes']['B']['spearman'])} "
            f"rho_ALL={_fmt(feature['scopes']['ALL']['spearman'])} "
            f"direction={direction} "
            f"A_{direction}_median={_fmt(a_fav['median_return_pct'])} "
            f"A_{opposite}_median={_fmt(a_opp['median_return_pct'])} "
            f"A_{direction}_tail={_fmt(a_fav['catastrophic_loss_rate_pct'])} "
            f"A_{opposite}_tail={_fmt(a_opp['catastrophic_loss_rate_pct'])} "
            f"B_{direction}_median={_fmt(b_fav['median_return_pct'])} "
            f"B_{opposite}_median={_fmt(b_opp['median_return_pct'])} "
            f"B_{direction}_tail={_fmt(b_fav['catastrophic_loss_rate_pct'])} "
            f"B_{opposite}_tail={_fmt(b_opp['catastrophic_loss_rate_pct'])} "
            f"CANDIDATE={feature['candidate']}"
        )

    print("\n=== CANDIDATE RANKING ===")
    if report["candidate_ranking"]:
        for index, name in enumerate(report["candidate_ranking"], start=1):
            print(f"RANK={index} FEATURE={name}")
    else:
        print("RANK=NONE")

    print(
        "SELECTED_FOR_FUTURE_PREREGISTRATION="
        + str(report["selected_candidate_for_future_preregistration"])
    )
    print("\nDIAGNOSTIC_ONLY=True")
    print("V68_REPLACEMENT_VALIDATION=False")
    print("NEW_FRESH=False")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-keys", nargs=2, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/burst_participation_structure_discovery_v0/report.json"
        ),
    )
    args = parser.parse_args()

    report = build_report(
        (
            str(args.run_keys[0]).strip(),
            str(args.run_keys[1]).strip(),
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print_summary(report)
    print(f"report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
