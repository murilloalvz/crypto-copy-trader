from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.burst_selection_diagnostic_v0.run import _metrics_dict
from participant_quality_native_holdout_v1 import CATASTROPHIC_RETURN_PCT

VERSION = "participant_quality_tail_risk_rejection_v0"
PASS_CLASSIFICATION = "PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0"
FAIL_CLASSIFICATION = "FAIL_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0"
INCONCLUSIVE_CLASSIFICATION = (
    "INCONCLUSIVE_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0_SUPPORT"
)

# Frozen per docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md
MIN_LOW_PAIRED = 15
MIN_ALL_PAIRED = 40
MATERIALITY_BAR_PP = 15.0


def _tail_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return 100.0 * sum(v <= CATASTROPHIC_RETURN_PCT for v in values) / len(values)


def evaluate_holdout_report(holdout_report: dict[str, Any]) -> dict[str, Any]:
    """Apply the tail-risk rejection gates to an existing
    participant_quality_native_holdout_v1 report's `rows` field.
    Reads already-computed episode rows; runs no new acquisition."""
    rows_by_cohort = holdout_report["rows"]
    paired = [
        row
        for rows in rows_by_cohort.values()
        for row in rows
        if row.get("feature_value") is not None
        and row.get("outcome_900_return_pct") is not None
        and row.get("group") in {"HIGH", "LOW"}
    ]
    high = [float(r["outcome_900_return_pct"]) for r in paired if r["group"] == "HIGH"]
    low = [float(r["outcome_900_return_pct"]) for r in paired if r["group"] == "LOW"]
    all_values = high + low

    support = {
        "low_paired_gte_15": len(low) >= MIN_LOW_PAIRED,
        "all_paired_gte_40": len(all_values) >= MIN_ALL_PAIRED,
    }

    low_tail = _tail_rate(low)
    all_tail = _tail_rate(all_values)
    high_median = _metrics_dict(high)["median_return_pct"] if high else None
    all_median = _metrics_dict(all_values)["median_return_pct"] if all_values else None

    result: dict[str, Any] = {
        "type": "participant_quality_tail_risk_rejection_report",
        "version": VERSION,
        "source_holdout_report": holdout_report.get("artifact"),
        "support": support,
        "low_n": len(low),
        "all_n": len(all_values),
        "low_catastrophic_loss_rate_pct": low_tail,
        "all_catastrophic_loss_rate_pct": all_tail,
        "high_median_return_pct": high_median,
        "all_median_return_pct": all_median,
        "economic_hypothesis_modified": False,
        "scientific_thresholds_modified": False,
    }

    if not all(support.values()):
        result["classification"] = INCONCLUSIVE_CLASSIFICATION
        result["gates"] = {}
        return result

    gap_pp = low_tail - all_tail
    gates = {
        "low_tail_worse_than_all": low_tail > all_tail,
        "gap_at_least_15pp": gap_pp >= MATERIALITY_BAR_PP,
        "high_only_median_not_worse_than_all": high_median >= all_median,
    }
    result["gap_pp"] = gap_pp
    result["gates"] = gates
    result["classification"] = (
        PASS_CLASSIFICATION if all(gates.values()) else FAIL_CLASSIFICATION
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate an existing participant_quality_native_holdout_v1 report "
            "against the tail-risk rejection preregistration. Reads only; "
            "starts no acquisition."
        )
    )
    parser.add_argument("--holdout-report", required=True, type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/participant_quality_tail_risk_rejection_v0/report.json"
        ),
    )
    args = parser.parse_args()

    holdout_report = json.loads(args.holdout_report.read_text(encoding="utf-8"))
    result = evaluate_holdout_report(holdout_report)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["classification"] == PASS_CLASSIFICATION else 1


def _demo() -> None:
    """ponytail: smallest runnable check for evaluate_holdout_report's gate logic."""
    fake_report = {
        "artifact": "demo",
        "rows": {
            "H1": [
                {"feature_value": 90, "group": "HIGH", "outcome_900_return_pct": -10.0},
                {"feature_value": 90, "group": "HIGH", "outcome_900_return_pct": -20.0},
                {"feature_value": 10, "group": "LOW", "outcome_900_return_pct": -95.0},
                {"feature_value": 10, "group": "LOW", "outcome_900_return_pct": -90.0},
            ]
        },
    }
    out = evaluate_holdout_report(fake_report)
    assert out["classification"] == INCONCLUSIVE_CLASSIFICATION, out
    assert out["support"]["low_paired_gte_15"] is False, out
    print("participant_quality_tail_risk_rejection_v0 self-check OK")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _demo()
        raise SystemExit(0)
    raise SystemExit(main())
