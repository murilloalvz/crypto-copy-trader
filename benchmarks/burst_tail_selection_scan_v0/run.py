from __future__ import annotations

import argparse
from dataclasses import asdict
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
from src.route_research_early_opportunity_v55 import (
    FEATURE_DEFINITIONS_V55,
    build_early_opportunity_dataset_v55,
)
from src.route_research_feature_review_v47 import FEATURE_DEFINITIONS_V47


VERSION = "burst_tail_selection_scan_v0"
CLASSIFICATION = "DIAGNOSTIC_ONLY_NO_FRESH_VERDICT"
PRIMARY_HORIZON_SECONDS = 900
CATASTROPHIC_RETURN_PCT = -80.0
MIN_COVERAGE_PCT_PER_SUBCOHORT = 80.0
MIN_EXTREME_GROUP_SUPPORT_PER_SUBCOHORT = 5

CLOSED_FEATURES = {
    "flow60_buy_share_pct",
}
DERIVED_FEATURES = {
    "entry_price_impact_closeness_to_zero",
}


def _numeric_feature_names() -> list[str]:
    names: list[str] = []
    for definition in (*FEATURE_DEFINITIONS_V47, *FEATURE_DEFINITIONS_V55):
        if definition.kind != "numeric":
            continue
        if definition.name in CLOSED_FEATURES:
            continue
        if definition.name not in names:
            names.append(definition.name)
    for name in sorted(DERIVED_FEATURES):
        if name not in names:
            names.append(name)
    return names


def _value_for(row, feature_name: str) -> float | None:
    if feature_name == "entry_price_impact_closeness_to_zero":
        signed = _finite_number(
            row.features.get("entry_price_impact_pct_points")
        )
        return -abs(signed) if signed is not None else None
    return _finite_number(row.features.get(feature_name))


def _tail_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return (
        100.0
        * sum(value <= CATASTROPHIC_RETURN_PCT for value in values)
        / len(values)
    )


def _sign(value: float | None) -> int:
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def _greater(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and float(left) > float(right)
    )


def _less(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and float(left) < float(right)
    )


def _feature_report(rows, feature_name: str) -> dict[str, Any]:
    values = {
        (row.acquisition_run_key, row.episode_key): _value_for(
            row, feature_name
        )
        for row in rows
    }

    known_all = [value for value in values.values() if value is not None]
    coverage: dict[str, Any] = {}
    for scope in ("A", "B", "ALL"):
        scoped = _scope_rows(rows, scope)
        known = sum(
            values[(row.acquisition_run_key, row.episode_key)] is not None
            for row in scoped
        )
        coverage[scope] = {
            "known": known,
            "total": len(scoped),
            "pct": 100.0 * known / len(scoped) if scoped else None,
        }

    if not known_all:
        return {
            "feature": feature_name,
            "coverage": coverage,
            "cutpoints": None,
            "scopes": {},
            "discovery_direction": None,
            "consistency_checks": {},
            "candidate_discovery_only": False,
        }

    low_cut, high_cut = tercile_cutpoints(
        [float(value) for value in known_all]
    )
    assignments = {
        key: (
            tercile_group(float(value), low_cut, high_cut)
            if value is not None
            else None
        )
        for key, value in values.items()
    }

    scopes: dict[str, Any] = {}
    for scope in ("A", "B", "ALL"):
        scoped = _scope_rows(rows, scope)
        xs: list[float] = []
        ys: list[float] = []
        grouped: dict[str, list[float]] = {
            "LOW": [],
            "MID": [],
            "HIGH": [],
        }
        for row in scoped:
            key = (row.acquisition_run_key, row.episode_key)
            feature = values[key]
            outcome = _finite_number(
                row.labels.get(PRIMARY_HORIZON_SECONDS)
            )
            if feature is None or outcome is None:
                continue
            xs.append(float(feature))
            ys.append(float(outcome))
            group = assignments[key]
            if group is not None:
                grouped[group].append(float(outcome))

        groups: dict[str, Any] = {}
        for group in ("LOW", "MID", "HIGH"):
            group_values = grouped[group]
            groups[group] = {
                **_metrics_dict(group_values),
                "catastrophic_loss_rate_pct": _tail_rate(group_values),
                "catastrophic_loss_count": sum(
                    value <= CATASTROPHIC_RETURN_PCT
                    for value in group_values
                ),
            }

        scopes[scope] = {
            "paired": len(ys),
            "spearman": _safe_number(
                spearman_rank_correlation(xs, ys)
            ),
            "groups": groups,
        }

    rho_all = scopes["ALL"]["spearman"]
    numeric_rho_all = (
        float(rho_all)
        if isinstance(rho_all, (int, float))
        else None
    )
    direction = (
        "HIGH"
        if numeric_rho_all is not None and numeric_rho_all > 0
        else (
            "LOW"
            if numeric_rho_all is not None and numeric_rho_all < 0
            else None
        )
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
    spearman_same_direction = (
        direction is not None
        and _sign(
            float(scopes["A"]["spearman"])
            if isinstance(scopes["A"]["spearman"], (int, float))
            else None
        )
        == _sign(numeric_rho_all)
        and _sign(
            float(scopes["B"]["spearman"])
            if isinstance(scopes["B"]["spearman"], (int, float))
            else None
        )
        == _sign(numeric_rho_all)
        and _sign(numeric_rho_all) != 0
    )

    support_ok = False
    median_better_both = False
    tail_better_both = False
    mean_wo_best_better_both = False
    pf_better_both = False

    if direction is not None and opposite is not None:
        support_ok = all(
            scopes[scope]["groups"][direction]["n"]
            >= MIN_EXTREME_GROUP_SUPPORT_PER_SUBCOHORT
            and scopes[scope]["groups"][opposite]["n"]
            >= MIN_EXTREME_GROUP_SUPPORT_PER_SUBCOHORT
            for scope in ("A", "B")
        )
        median_better_both = all(
            _greater(
                scopes[scope]["groups"][direction]["median_return_pct"],
                scopes[scope]["groups"][opposite]["median_return_pct"],
            )
            for scope in ("A", "B")
        )
        tail_better_both = all(
            _less(
                scopes[scope]["groups"][direction][
                    "catastrophic_loss_rate_pct"
                ],
                scopes[scope]["groups"][opposite][
                    "catastrophic_loss_rate_pct"
                ],
            )
            for scope in ("A", "B")
        )
        mean_wo_best_better_both = all(
            _greater(
                scopes[scope]["groups"][direction][
                    "mean_without_best_pct"
                ],
                scopes[scope]["groups"][opposite][
                    "mean_without_best_pct"
                ],
            )
            for scope in ("A", "B")
        )
        pf_better_both = all(
            _greater(
                scopes[scope]["groups"][direction]["profit_factor"],
                scopes[scope]["groups"][opposite]["profit_factor"],
            )
            for scope in ("A", "B")
        )

    checks = {
        "coverage_gte_80_pct_both": coverage_ok,
        "extreme_group_support_both": support_ok,
        "spearman_same_direction_a_b_all": spearman_same_direction,
        "favorable_extreme_median_better_both": median_better_both,
        "favorable_extreme_catastrophic_tail_lower_both": tail_better_both,
        "favorable_extreme_mean_without_best_better_both": (
            mean_wo_best_better_both
        ),
        "favorable_extreme_pf_better_both": pf_better_both,
    }

    candidate = all(checks.values())

    return {
        "feature": feature_name,
        "coverage": coverage,
        "cutpoints": {
            "low_max": low_cut,
            "mid_max": high_cut,
            "method": "outcome_blind_global_feature_terciles",
        },
        "scopes": scopes,
        "discovery_direction": direction,
        "opposite_extreme": opposite,
        "consistency_checks": checks,
        "candidate_discovery_only": candidate,
    }


def build_report(run_keys: tuple[str, str]) -> dict[str, Any]:
    dataset = build_early_opportunity_dataset_v55(
        acquisition_run_keys=run_keys
    )
    rows = dataset.rows
    features = {
        name: _feature_report(rows, name)
        for name in _numeric_feature_names()
    }
    candidates = [
        name
        for name, report in features.items()
        if report["candidate_discovery_only"]
    ]

    baseline_values = [
        float(row.labels[PRIMARY_HORIZON_SECONDS])
        for row in rows
        if _finite_number(
            row.labels.get(PRIMARY_HORIZON_SECONDS)
        )
        is not None
    ]

    return {
        "type": "burst_tail_selection_scan_report",
        "version": VERSION,
        "classification": CLASSIFICATION,
        "authorization": (
            "read_only_discovery_on_consumed_v68_03_no_selector_no_new_fresh"
        ),
        "run_keys": list(run_keys),
        "rows_total": len(rows),
        "primary_horizon_seconds": PRIMARY_HORIZON_SECONDS,
        "catastrophic_return_threshold_pct": CATASTROPHIC_RETURN_PCT,
        "dataset_quality": {
            "lineage_violations": dataset.base.lineage_violations,
            "augmentation_failures": dataset.augmentation_failures,
            "feature_clock_violations": dataset.feature_clock_violations,
        },
        "baseline_900": {
            **_metrics_dict(baseline_values),
            "catastrophic_loss_rate_pct": _tail_rate(baseline_values),
            "catastrophic_loss_count": sum(
                value <= CATASTROPHIC_RETURN_PCT
                for value in baseline_values
            ),
        },
        "closed_features_excluded_from_candidate_scan": sorted(
            CLOSED_FEATURES
        ),
        "feature_reports": features,
        "candidate_features_discovery_only": candidates,
        "scientific_note": (
            "This is a retrospective discovery scan on the already-consumed "
            "V68 -03 cohort. Feature values and tercile cutpoints are causal "
            "and outcome-blind, but candidate selection uses observed outcomes "
            "and therefore cannot establish edge. Any chosen candidate must be "
            "frozen before a new independent fresh cohort."
        ),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_summary(report: dict[str, Any]) -> None:
    print("Crypto Copy Trader — Burst Tail Selection Scan V0")
    print(f"classification={report['classification']}")
    print(f"rows_total={report['rows_total']}")
    q = report["dataset_quality"]
    print(
        "dataset_quality="
        f"lineage_violations={q['lineage_violations']} "
        f"augmentation_failures={q['augmentation_failures']} "
        f"feature_clock_violations={q['feature_clock_violations']}"
    )
    baseline = report["baseline_900"]
    print(
        "BASELINE_900 "
        f"n={_fmt(baseline['n'])} "
        f"median={_fmt(baseline['median_return_pct'])} "
        f"PF={_fmt(baseline['profit_factor'])} "
        f"mean_wo_best={_fmt(baseline['mean_without_best_pct'])} "
        f"catastrophic_count={baseline['catastrophic_loss_count']} "
        f"catastrophic_pct={_fmt(baseline['catastrophic_loss_rate_pct'])}"
    )

    print("\n=== FEATURES ===")
    for name, feature in report["feature_reports"].items():
        cov_a = feature["coverage"]["A"]["pct"]
        cov_b = feature["coverage"]["B"]["pct"]
        scopes = feature["scopes"]
        if not scopes:
            print(
                f"FEATURE={name} coverage_A={_fmt(cov_a)} "
                f"coverage_B={_fmt(cov_b)} DATA=INSUFFICIENT"
            )
            continue
        direction = feature["discovery_direction"]
        opposite = feature["opposite_extreme"]
        if direction is None or opposite is None:
            print(
                f"FEATURE={name} coverage_A={_fmt(cov_a)} "
                f"coverage_B={_fmt(cov_b)} "
                f"rho_A={_fmt(scopes['A']['spearman'])} "
                f"rho_B={_fmt(scopes['B']['spearman'])} "
                f"rho_ALL={_fmt(scopes['ALL']['spearman'])} "
                "direction=NONE"
            )
            continue
        fav_a = scopes["A"]["groups"][direction]
        fav_b = scopes["B"]["groups"][direction]
        opp_a = scopes["A"]["groups"][opposite]
        opp_b = scopes["B"]["groups"][opposite]
        print(
            f"FEATURE={name} "
            f"coverage_A={_fmt(cov_a)} "
            f"coverage_B={_fmt(cov_b)} "
            f"rho_A={_fmt(scopes['A']['spearman'])} "
            f"rho_B={_fmt(scopes['B']['spearman'])} "
            f"rho_ALL={_fmt(scopes['ALL']['spearman'])} "
            f"direction={direction} "
            f"A_{direction}_median={_fmt(fav_a['median_return_pct'])} "
            f"A_{opposite}_median={_fmt(opp_a['median_return_pct'])} "
            f"A_{direction}_tail={_fmt(fav_a['catastrophic_loss_rate_pct'])} "
            f"A_{opposite}_tail={_fmt(opp_a['catastrophic_loss_rate_pct'])} "
            f"B_{direction}_median={_fmt(fav_b['median_return_pct'])} "
            f"B_{opposite}_median={_fmt(opp_b['median_return_pct'])} "
            f"B_{direction}_tail={_fmt(fav_b['catastrophic_loss_rate_pct'])} "
            f"B_{opposite}_tail={_fmt(opp_b['catastrophic_loss_rate_pct'])} "
            f"CANDIDATE={feature['candidate_discovery_only']}"
        )

    print("\n=== DISCOVERY CANDIDATES ===")
    candidates = report["candidate_features_discovery_only"]
    if candidates:
        for name in candidates:
            print(f"CANDIDATE={name}")
    else:
        print("CANDIDATE=NONE")

    print("\nDIAGNOSTIC_ONLY=True")
    print("NO_SELECTOR_FROZEN=True")
    print("NO_NEW_FRESH=True")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only causal scan of predeclared V47/V55 features for "
            "Burst selection and catastrophic-tail reduction."
        )
    )
    parser.add_argument("--run-keys", nargs=2, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/burst_tail_selection_scan_v0/report.json"
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
