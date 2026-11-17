from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.route_research_feature_review_v47 import return_metrics_v47

FEATURE_ID = "mf_top_wallet_gross_share_delta_pct_points_late_minus_early"
MIN_SUPPORT_N = 10
MIN_COVERAGE_PCT = 80.0
PASS = "PASS_CD_PROMO_V0"
FAIL = "FAIL_CD_PROMO_V0"
INCONCLUSIVE = "INCONCLUSIVE_CD_PROMO_V0_SUPPORT"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def cd_promo_v0_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the CD-PROMO-V0 preregistration criteria (section 4) to discovery rows.

    Frozen, not re-derived here: feature <= 0 is favorable; n>=10 route-usable;
    coverage>=80%; favorable median return and profit factor must both beat the
    unfavorable group. See
    docs/concentration-decay-promotion-v0-preregistration-2026-10-05.md.
    """
    baseline_rows = [row for row in rows if row.get("baseline_admitted") is True]
    outcome_known = [row for row in baseline_rows if _finite(row.get("fixed_return_pct")) is not None]

    favorable: list[float] = []
    unfavorable: list[float] = []
    for row in outcome_known:
        feature_value = _finite((row.get("features") or {}).get(FEATURE_ID))
        if feature_value is None:
            continue
        outcome = _finite(row["fixed_return_pct"])
        (favorable if feature_value <= 0.0 else unfavorable).append(outcome)

    feature_known_count = len(favorable) + len(unfavorable)
    coverage_pct = 100.0 * feature_known_count / len(outcome_known) if outcome_known else 0.0

    favorable_metrics = return_metrics_v47(favorable)
    unfavorable_metrics = return_metrics_v47(unfavorable)

    if coverage_pct < MIN_COVERAGE_PCT or feature_known_count < MIN_SUPPORT_N:
        verdict = INCONCLUSIVE
    else:
        median_ok = (
            favorable_metrics.median_return_pct is not None
            and unfavorable_metrics.median_return_pct is not None
            and favorable_metrics.median_return_pct > unfavorable_metrics.median_return_pct
        )
        pf_ok = favorable_metrics.profit_factor is not None and favorable_metrics.profit_factor > 1.0
        verdict = PASS if (median_ok and pf_ok) else FAIL

    return {
        "hypothesis_id": "CD-PROMO-V0",
        "feature_id": FEATURE_ID,
        "verdict": verdict,
        "baseline_admitted_count": len(baseline_rows),
        "outcome_known_count": len(outcome_known),
        "feature_coverage_pct": coverage_pct,
        "n_favorable_le_0": len(favorable),
        "n_unfavorable_gt_0": len(unfavorable),
        "n_total_route_usable": feature_known_count,
        "favorable_metrics": asdict(favorable_metrics),
        "unfavorable_metrics": asdict(unfavorable_metrics),
    }


def _self_check() -> None:
    synthetic_rows = [
        {"baseline_admitted": True, "fixed_return_pct": 12.0, "features": {FEATURE_ID: -1.5}},
        {"baseline_admitted": True, "fixed_return_pct": 8.0, "features": {FEATURE_ID: -0.1}},
        {"baseline_admitted": True, "fixed_return_pct": 5.0, "features": {FEATURE_ID: 0.0}},
        {"baseline_admitted": True, "fixed_return_pct": -2.0, "features": {FEATURE_ID: -3.0}},
        {"baseline_admitted": True, "fixed_return_pct": -20.0, "features": {FEATURE_ID: 4.0}},
        {"baseline_admitted": True, "fixed_return_pct": -15.0, "features": {FEATURE_ID: 2.0}},
        {"baseline_admitted": True, "fixed_return_pct": -10.0, "features": {FEATURE_ID: 1.0}},
        {"baseline_admitted": False, "fixed_return_pct": 999.0, "features": {FEATURE_ID: -9.0}},
        {"baseline_admitted": True, "fixed_return_pct": None, "features": {FEATURE_ID: -1.0}},
        {"baseline_admitted": True, "fixed_return_pct": 1.0, "features": {}},
    ]
    result = cd_promo_v0_verdict(synthetic_rows)
    assert result["baseline_admitted_count"] == 9, result  # row 8 excluded: baseline_admitted=False
    assert result["outcome_known_count"] == 8, result  # row 9 excluded: fixed_return_pct=None
    assert result["n_total_route_usable"] == 7, result  # row 10 excluded: feature missing
    assert result["n_favorable_le_0"] == 4 and result["n_unfavorable_gt_0"] == 3, result
    assert result["verdict"] == INCONCLUSIVE, result  # n=7 < MIN_SUPPORT_N=10
    print("self-check OK:", result["verdict"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the CD-PROMO-V0 frozen promotion criteria to a market_first_feature_discovery_v1 report."
    )
    parser.add_argument("--report", type=Path, help="market-first-feature-discovery-v1.json path")
    parser.add_argument("--self-check", action="store_true", help="run the synthetic self-check and exit")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if not args.report:
        raise SystemExit("--report is required unless --self-check is passed")

    payload = json.loads(Path(args.report).read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    result = cd_promo_v0_verdict(rows)
    print(json.dumps(result, indent=2, sort_keys=True))
    return {PASS: 0, FAIL: 1, INCONCLUSIVE: 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
