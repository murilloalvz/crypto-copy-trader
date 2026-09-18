from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID,
    _association,
    _finite,
    _mean,
    _pct,
    _spearman,
)

PASS = "PASS_EARLY_BUYER_PRIOR_QUALITY_MATURITY_V0"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _run_summary(run_id: str, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("observed_t0") or 0),
            str(row.get("episode_key") or ""),
        ),
    )
    feature_rows = [row for row in ordered if _finite(row.get(FEATURE_ID)) is not None]
    primary = _association(
        list(ordered),
        "current_route_closed_gross_return_pct",
    )

    coverage_values = [
        float(value)
        for row in feature_rows
        if (value := _finite(row.get("history_coverage_pct"))) is not None
    ]
    association_counts = [
        float(value)
        for row in feature_rows
        if (value := _finite(row.get("prior_association_count"))) is not None
    ]
    unique_episode_counts = [
        float(value)
        for row in feature_rows
        if (value := _finite(row.get("prior_unique_episode_count"))) is not None
    ]
    wallets_with_history = [
        float(value)
        for row in feature_rows
        if (value := _finite(row.get("wallets_with_history"))) is not None
    ]

    depth_per_covered_wallet: list[float] = []
    for row in feature_rows:
        associations = _finite(row.get("prior_association_count"))
        covered = _finite(row.get("wallets_with_history"))
        if associations is None or covered is None or covered <= 0:
            continue
        depth_per_covered_wallet.append(float(associations) / float(covered))

    return {
        "run_id": run_id,
        "first_observed_t0": (
            int(ordered[0].get("observed_t0") or 0) if ordered else None
        ),
        "last_observed_t0": (
            int(ordered[-1].get("observed_t0") or 0) if ordered else None
        ),
        "population_n": len(ordered),
        "feature_available_n": len(feature_rows),
        "feature_availability_pct": _pct(len(feature_rows), len(ordered)),
        "mean_history_coverage_pct": _mean(coverage_values),
        "median_history_coverage_pct": median(coverage_values) if coverage_values else None,
        "mean_prior_association_count": _mean(association_counts),
        "median_prior_association_count": (
            median(association_counts) if association_counts else None
        ),
        "mean_prior_unique_episode_count": _mean(unique_episode_counts),
        "median_prior_unique_episode_count": (
            median(unique_episode_counts) if unique_episode_counts else None
        ),
        "mean_wallets_with_history": _mean(wallets_with_history),
        "median_wallets_with_history": (
            median(wallets_with_history) if wallets_with_history else None
        ),
        "mean_prior_associations_per_covered_wallet": _mean(
            depth_per_covered_wallet
        ),
        "median_prior_associations_per_covered_wallet": (
            median(depth_per_covered_wallet)
            if depth_per_covered_wallet
            else None
        ),
        "primary_signal_quality": primary,
    }


def _chronological_half(rows: list[Mapping[str, Any]], *, later: bool) -> dict[str, Any]:
    run_firsts: dict[str, int] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        observed = int(row.get("observed_t0") or 0)
        if not run_id:
            continue
        run_firsts[run_id] = min(run_firsts.get(run_id, observed), observed)
    ordered_runs = [
        run_id
        for run_id, _ in sorted(run_firsts.items(), key=lambda item: (item[1], item[0]))
    ]
    midpoint = len(ordered_runs) // 2
    selected = set(ordered_runs[midpoint:] if later else ordered_runs[:midpoint])
    selected_rows = [row for row in rows if str(row.get("run_id") or "") in selected]
    return {
        "run_ids": [run_id for run_id in ordered_runs if run_id in selected],
        "association": _association(
            selected_rows,
            "current_route_closed_gross_return_pct",
        ),
    }


def run_maturity_diagnostic(
    *,
    discovery_artifact: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    artifact = _read_json(discovery_artifact)
    if artifact.get("classification") != "PASS_EARLY_BUYER_PRIOR_QUALITY_V0":
        raise ValueError("early-buyer prior-quality artifact is not PASS")
    if artifact.get("decision") != "ITERATE":
        raise ValueError("maturity diagnostic is defined only for ITERATE discovery")

    rows = [
        row
        for row in artifact.get("rows") or []
        if isinstance(row, dict)
    ]
    if not rows:
        raise ValueError("early-buyer prior-quality rows missing")

    run_ids = sorted(
        {str(row.get("run_id") or "") for row in rows if str(row.get("run_id") or "")}
    )
    per_run = {
        run_id: _run_summary(
            run_id,
            [row for row in rows if str(row.get("run_id") or "") == run_id],
        )
        for run_id in run_ids
    }
    ordered_run_ids = [
        item["run_id"]
        for item in sorted(
            per_run.values(),
            key=lambda item: (
                int(item.get("first_observed_t0") or 0),
                str(item.get("run_id") or ""),
            ),
        )
    ]

    informative = [
        per_run[run_id]
        for run_id in ordered_run_ids
        if int(
            (
                per_run[run_id].get("primary_signal_quality") or {}
            ).get("usable_pair_count")
            or 0
        )
        > 0
        and _finite(
            (per_run[run_id].get("primary_signal_quality") or {}).get("spearman")
        )
        is not None
    ]

    run_rhos = [
        float((item["primary_signal_quality"] or {})["spearman"])
        for item in informative
    ]
    run_median_depth = [
        float(item["median_prior_associations_per_covered_wallet"])
        for item in informative
        if _finite(item.get("median_prior_associations_per_covered_wallet")) is not None
    ]
    run_availability = [
        float(item["feature_availability_pct"])
        for item in informative
        if _finite(item.get("feature_availability_pct")) is not None
    ]

    maturity_vs_rho = None
    if len(run_median_depth) == len(run_rhos) and len(run_rhos) >= 2:
        maturity_vs_rho = _spearman(run_median_depth, run_rhos)
    availability_vs_rho = None
    if len(run_availability) == len(run_rhos) and len(run_rhos) >= 2:
        availability_vs_rho = _spearman(run_availability, run_rhos)

    leave_one_run_out: dict[str, Any] = {}
    for run_id in ordered_run_ids:
        kept = [row for row in rows if str(row.get("run_id") or "") != run_id]
        leave_one_run_out[run_id] = _association(
            kept,
            "current_route_closed_gross_return_pct",
        )

    chronological_index = list(range(len(run_rhos)))
    rho_trend = (
        _spearman([float(index) for index in chronological_index], run_rhos)
        if len(run_rhos) >= 2
        else None
    )

    first_half = _chronological_half(rows, later=False)
    second_half = _chronological_half(rows, later=True)

    report = {
        "classification": PASS,
        "inference_role": "POSTHOC_HISTORY_MATURITY_DIAGNOSTIC_ONLY",
        "discovery_decision_unchanged": "ITERATE",
        "feature_id": FEATURE_ID,
        "run_order": ordered_run_ids,
        "per_run": per_run,
        "cross_run_maturity": {
            "spearman_run_median_history_depth_vs_run_primary_rho": maturity_vs_rho,
            "spearman_run_feature_availability_vs_run_primary_rho": availability_vs_rho,
            "spearman_chronological_run_index_vs_run_primary_rho": rho_trend,
            "run_primary_rhos_in_order": run_rhos,
        },
        "leave_one_run_out_pooled_primary": leave_one_run_out,
        "chronological_halves": {
            "earlier_half": first_half,
            "later_half": second_half,
        },
        "guardrails": {
            "threshold_search_performed": False,
            "selector_changed": False,
            "discovery_decision_changed": False,
            "support_threshold_promoted": False,
            "fresh_confirmation_claim": False,
        },
        "interpretation": (
            "This diagnostic asks whether the mixed cross-run result is plausibly related to historical "
            "memory maturity rather than rescuing the feature with a support threshold. It does not define "
            "a minimum history count, change the ITERATE decision, or authorize selector promotion. If later "
            "runs show both deeper history and stronger positive association, the next step may preregister one "
            "semantic support requirement for fresh confirmation. If maturity does not explain the instability, "
            "this participant-history feature should be deprioritized in favor of a genuinely new information source."
        ),
    }

    destination = output_path or discovery_artifact.with_name(
        "early-buyer-prior-quality-maturity-v0.json"
    )
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Posthoc maturity diagnostic for early-buyer prior quality"
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_maturity_diagnostic(
            discovery_artifact=args.artifact,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL_EARLY_BUYER_PRIOR_QUALITY_MATURITY_V0",
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
