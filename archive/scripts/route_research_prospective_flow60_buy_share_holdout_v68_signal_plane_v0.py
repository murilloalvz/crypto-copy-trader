from __future__ import annotations

import argparse
from pathlib import Path

import route_research_prospective_flow60_buy_share_holdout_v68 as legacy_v68
import signal_plane_v68_promotion_v0 as promotion
from src.database import connection
from src.route_research_early_opportunity_v55 import (
    V55_MIN_ROWS_PER_SUBCOHORT,
    build_early_opportunity_dataset_v55,
)
from src.route_research_prospective_flow60_buy_share_v68 import (
    primary_gate_v68,
)
from src.signal_plane_forward_cohort_v0 import (
    SUBCOHORT_CAP,
    SUBCOHORT_MIN_DECISIONS,
    run_signal_plane_forward_cohort_v0,
)


VERSION = "v68_signal_plane_prospective_v0"
AUTHORIZATION = "fresh_economic_only_after_release_promotion"


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _strict_run_keys_fresh(run_keys: tuple[str, ...]) -> tuple[bool, str]:
    residue: list[str] = []
    with connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for table_row in tables:
            table = str(table_row["name"])
            quoted = _quote_identifier(table)
            columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
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
                    residue.append(f"{run_key}:{table}:{count}")
    return not residue, ("none" if not residue else ";".join(sorted(residue)))


def run_signal_plane_v68_v0(
    *,
    base_run_key: str,
    bootstrap_report: Path,
    promotion_report: Path,
    cargo: str = "cargo",
    acquisition_duration_seconds: float = 120.0,
    hazard_start_interval_ms: int = 650,
    entry_start_interval_ms: int = 1000,
    exit_start_interval_ms: int = 250,
    artifact_root: Path = Path(
        "artifacts/v68_signal_plane_prospective_v0"
    ),
) -> dict:
    base = str(base_run_key).strip()
    if not base:
        raise ValueError("base_run_key cannot be empty")

    promotion_ok, promotion_detail = promotion.validate_promotion_report(
        Path(promotion_report)
    )
    if not promotion_ok:
        return {
            "type": "v68_signal_plane_prospective_report",
            "version": VERSION,
            "classification": "FAIL_V68_SIGNAL_PLANE_PROMOTION_REQUIRED",
            "promotion_detail": promotion_detail,
            "authorization": AUTHORIZATION,
        }

    run_keys = (f"{base}-A", f"{base}-B")

    strict_fresh, residue = _strict_run_keys_fresh(run_keys)
    if not strict_fresh:
        return {
            "type": "v68_signal_plane_prospective_report",
            "version": VERSION,
            "classification": "FAIL_V68_SIGNAL_PLANE_RUN_KEY_NOT_FRESH",
            "run_keys": run_keys,
            "residue": residue,
            "authorization": AUTHORIZATION,
        }

    artifact_root.mkdir(parents=True, exist_ok=True)
    cohort_results = []
    for run_key in run_keys:
        result = run_signal_plane_forward_cohort_v0(
            run_key=run_key,
            bootstrap_report=Path(bootstrap_report),
            promotion_report=Path(promotion_report),
            acquisition_duration_seconds=acquisition_duration_seconds,
            cargo=cargo,
            max_episodes=SUBCOHORT_CAP,
            min_research_decisions=SUBCOHORT_MIN_DECISIONS,
            hazard_start_interval_ms=hazard_start_interval_ms,
            entry_start_interval_ms=entry_start_interval_ms,
            exit_start_interval_ms=exit_start_interval_ms,
            artifact_root=artifact_root / run_key,
        )
        cohort_results.append(result)
        if not result.passed:
            return {
                "type": "v68_signal_plane_prospective_report",
                "version": VERSION,
                "classification": "FAIL_V68_SIGNAL_PLANE_SUBCOHORT",
                "failed_run_key": run_key,
                "run_keys": run_keys,
                "subcohorts": [
                    item.__dict__ for item in cohort_results
                ],
                "authorization": AUTHORIZATION,
            }

    dataset = build_early_opportunity_dataset_v55(
        acquisition_run_keys=run_keys
    )
    rows = dataset.rows
    base_ds = dataset.base
    count_a = sum(1 for row in rows if row.cohort == "A")
    count_b = sum(1 for row in rows if row.cohort == "B")

    causal_checks = {
        "rows_A_ge_minimum": count_a >= V55_MIN_ROWS_PER_SUBCOHORT,
        "rows_B_ge_minimum": count_b >= V55_MIN_ROWS_PER_SUBCOHORT,
        "lineage_violations_zero": base_ds.lineage_violations == 0,
        "missing_decisions_zero": base_ds.missing_decisions == 0,
        "missing_episodes_zero": base_ds.missing_episodes == 0,
        "missing_hazard_attempts_zero": base_ds.missing_hazard_attempts == 0,
        "missing_entry_quotes_zero": base_ds.missing_entry_quotes == 0,
        "official_decision_mutations_zero": (
            base_ds.official_decision_mutations == 0
        ),
        "augmentation_failures_zero": dataset.augmentation_failures == 0,
        "feature_clock_violations_zero": (
            dataset.feature_clock_violations == 0
        ),
    }
    if not all(causal_checks.values()):
        return {
            "type": "v68_signal_plane_prospective_report",
            "version": VERSION,
            "classification": "FAIL_V68_SIGNAL_PLANE_CAUSAL_HOLDOUT_AUDIT",
            "run_keys": run_keys,
            "subcohorts": [item.__dict__ for item in cohort_results],
            "causal_checks": causal_checks,
            "rows_total": len(rows),
            "rows_A": count_a,
            "rows_B": count_b,
            "authorization": AUTHORIZATION,
        }

    gate = primary_gate_v68(rows=rows)
    return {
        "type": "v68_signal_plane_prospective_report",
        "version": VERSION,
        "classification": gate.classification,
        "run_keys": run_keys,
        "subcohorts": [item.__dict__ for item in cohort_results],
        "rows_total": len(rows),
        "rows_A": count_a,
        "rows_B": count_b,
        "causal_checks": causal_checks,
        "primary_gate": {
            "feature_known": gate.feature_known,
            "feature_total": gate.feature_total,
            "feature_coverage_pct": gate.feature_coverage_pct,
            "support_ok": gate.support_ok,
            "same_direction_ok": gate.same_direction_ok,
            "favorable_positive_median_both": (
                gate.favorable_positive_median_both
            ),
            "favorable_pf_gt_one_both": gate.favorable_pf_gt_one_both,
            "aggregate_favorable_pf_gt_one": (
                gate.aggregate_favorable_pf_gt_one
            ),
            "aggregate_favorable_mean_without_best_positive": (
                gate.aggregate_favorable_mean_without_best_positive
            ),
        },
        "economic_contract": {
            "feature": legacy_v68.V68_FEATURE_NAME,
            "low_max": legacy_v68.V68_LOW_MAX,
            "mid_max": legacy_v68.V68_MID_MAX,
            "favorable": legacy_v68.V68_FAVORABLE_GROUP,
            "opposite": legacy_v68.V68_OPPOSITE_GROUP,
            "primary_horizon_seconds": (
                legacy_v68.V68_PRIMARY_HORIZON_SECONDS
            ),
            "minimum_support_per_subcohort": (
                legacy_v68.V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT
            ),
        },
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "authorization": AUTHORIZATION,
        "interpretation": (
            "The classification is the frozen V68 primary gate evaluated on "
            "fresh A/B cohorts acquired through the promoted Signal Plane path. "
            "It remains route-only paper research, not landing/fill or live-money proof."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fresh V68 Flow60 Buy-Share prospective holdout over the promoted "
            "Signal Plane acquisition path. Do not run before release promotion."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--bootstrap-report", required=True, type=Path)
    parser.add_argument("--promotion-report", required=True, type=Path)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--acquisition-duration-seconds", type=float, default=120.0)
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    args = parser.parse_args()

    report = run_signal_plane_v68_v0(
        base_run_key=args.run_key,
        bootstrap_report=args.bootstrap_report,
        promotion_report=args.promotion_report,
        cargo=args.cargo,
        acquisition_duration_seconds=args.acquisition_duration_seconds,
        hazard_start_interval_ms=args.hazard_start_interval_ms,
        entry_start_interval_ms=args.entry_start_interval_ms,
        exit_start_interval_ms=args.exit_start_interval_ms,
    )

    print("Crypto Copy Trader — V68 Signal Plane Prospective V0")
    print(f"version={report['version']}")
    print(f"classification={report['classification']}")
    if "rows_total" in report:
        print(
            f"rows_total={report['rows_total']} "
            f"rows_A={report['rows_A']} rows_B={report['rows_B']}"
        )
    if "primary_gate" in report:
        gate = report["primary_gate"]
        print(
            f"feature_coverage={gate['feature_known']}/{gate['feature_total']}"
            f"({gate['feature_coverage_pct']:.1f}%) "
            f"support_ok={gate['support_ok']} "
            f"same_direction_ok={gate['same_direction_ok']} "
            f"favorable_positive_median_both="
            f"{gate['favorable_positive_median_both']} "
            f"favorable_pf_gt_one_both="
            f"{gate['favorable_pf_gt_one_both']} "
            f"aggregate_favorable_pf_gt_one="
            f"{gate['aggregate_favorable_pf_gt_one']} "
            f"aggregate_favorable_mean_without_best_positive="
            f"{gate['aggregate_favorable_mean_without_best_positive']}"
        )
    print(report.get("interpretation", ""))

    return (
        0
        if report["classification"]
        == "PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
