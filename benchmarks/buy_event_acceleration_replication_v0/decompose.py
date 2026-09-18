from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

PASS = "PASS_BUY_EVENT_ACCELERATION_DECOMPOSITION_V0"
FEATURE_ID = "mf_buy_event_rate_acceleration_per_s2"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


def _group_summary(rows: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    all_net: list[float] = []
    closed_net: list[float] = []
    closed_gross: list[float] = []
    exit_failed_net: list[float] = []

    for row in rows:
        episode_key = str(row.get("episode_key") or "")
        decision = decisions.get(episode_key) or {}
        status = str(decision.get("status") or row.get("route_status") or "MISSING")
        statuses[status] = statuses.get(status, 0) + 1

        net = _finite(row.get("fixed_return_pct"))
        if net is not None:
            all_net.append(net)

        if status == "ROUTE_CLOSED":
            if net is not None:
                closed_net.append(net)
            gross = _finite(decision.get("gross_route_return_pct"))
            if gross is not None:
                closed_gross.append(gross)
        elif status.startswith("UNROUTABLE_EXIT"):
            if net is not None:
                exit_failed_net.append(net)

    route_closed_count = statuses.get("ROUTE_CLOSED", 0)
    exit_failure_count = sum(
        count for status, count in statuses.items() if status.startswith("UNROUTABLE_EXIT")
    )
    return {
        "n": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "route_closed_count": route_closed_count,
        "exit_failure_count": exit_failure_count,
        "exit_failure_rate_pct": _pct(exit_failure_count, len(rows)),
        "overall_mean_net_return_pct": _mean(all_net),
        "overall_median_net_return_pct": median(all_net) if all_net else None,
        "route_closed_mean_net_return_pct": _mean(closed_net),
        "route_closed_median_net_return_pct": median(closed_net) if closed_net else None,
        "route_closed_mean_gross_return_pct": _mean(closed_gross),
        "route_closed_gross_return_available_n": len(closed_gross),
        "unroutable_exit_mean_net_return_pct": _mean(exit_failed_net),
    }


def run_decomposition(*, run_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    replication_path = run_dir / "buy-event-acceleration-replication-v0.json"
    discovery_path = run_dir / "market-first-feature-discovery-v1.json"
    route_result_path = run_dir / "route-result-v2.json"
    for path in (replication_path, discovery_path, route_result_path):
        if not path.is_file():
            raise ValueError(f"required decomposition source missing: {path}")

    replication = _read_json(replication_path)
    discovery = _read_json(discovery_path)
    route_result = _read_json(route_result_path)

    if replication.get("classification") != "PASS_BUY_EVENT_ACCELERATION_REPLICATION_V0":
        raise ValueError("replication artifact is not PASS")
    if replication.get("decision") != "ITERATE":
        raise ValueError("decomposition v0 is defined only for the ITERATE replication outcome")
    if discovery.get("classification") != "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1":
        raise ValueError("feature discovery artifact is not PASS")

    split = _finite((replication.get("population") or {}).get("fresh_median_feature_value"))
    if split is None:
        raise ValueError("replication median split missing")

    decisions = {
        str(row.get("episode_key") or ""): row
        for row in route_result.get("decisions") or []
        if isinstance(row, dict) and str(row.get("episode_key") or "")
    }

    eligible: list[dict[str, Any]] = []
    for row in discovery.get("rows") or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("route_status") or "")
        if (
            row.get("baseline_admitted") is not True
            or row.get("is_default_sol_quote") is not True
            or not (status == "ROUTE_CLOSED" or status.startswith("UNROUTABLE_EXIT"))
        ):
            continue
        feature = _finite((row.get("features") or {}).get(FEATURE_ID))
        outcome = _finite(row.get("fixed_return_pct"))
        if feature is None or outcome is None:
            continue
        eligible.append(
            {
                "episode_key": str(row.get("episode_key") or ""),
                "feature": feature,
                "fixed_return_pct": outcome,
                "route_status": status,
            }
        )

    expected_n = int((replication.get("population") or {}).get("fresh_feature_route_usable_default_sol_n") or 0)
    if len(eligible) != expected_n:
        raise ValueError(f"eligible population parity mismatch: {len(eligible)} != {expected_n}")

    lower = [row for row in eligible if row["feature"] <= split]
    upper = [row for row in eligible if row["feature"] > split]
    lower_summary = _group_summary(lower, decisions)
    upper_summary = _group_summary(upper, decisions)

    exit_failure_gap = None
    if (
        lower_summary["exit_failure_rate_pct"] is not None
        and upper_summary["exit_failure_rate_pct"] is not None
    ):
        exit_failure_gap = (
            upper_summary["exit_failure_rate_pct"]
            - lower_summary["exit_failure_rate_pct"]
        )

    closed_net_gap = None
    if (
        lower_summary["route_closed_mean_net_return_pct"] is not None
        and upper_summary["route_closed_mean_net_return_pct"] is not None
    ):
        closed_net_gap = (
            lower_summary["route_closed_mean_net_return_pct"]
            - upper_summary["route_closed_mean_net_return_pct"]
        )

    overall_gap = None
    if (
        lower_summary["overall_mean_net_return_pct"] is not None
        and upper_summary["overall_mean_net_return_pct"] is not None
    ):
        overall_gap = (
            lower_summary["overall_mean_net_return_pct"]
            - upper_summary["overall_mean_net_return_pct"]
        )

    report = {
        "classification": PASS,
        "inference_role": "POSTHOC_MECHANISM_DECOMPOSITION_ONLY_NO_SELECTOR_CHANGE",
        "replication_decision_unchanged": "ITERATE",
        "feature_id": FEATURE_ID,
        "split_reused_from_preregistered_supporting_analysis": split,
        "threshold_search_performed": False,
        "selector_changed": False,
        "population_parity_n": len(eligible),
        "lower_half_more_negative_acceleration": lower_summary,
        "upper_half_less_negative_or_positive_acceleration": upper_summary,
        "decomposition": {
            "upper_minus_lower_exit_failure_rate_pct_points": exit_failure_gap,
            "lower_minus_upper_route_closed_mean_net_return_pct_points": closed_net_gap,
            "lower_minus_upper_overall_mean_net_return_pct_points": overall_gap,
            "interpretation_rule": (
                "If the overall gap is much larger than the route-closed-only gap while the upper half "
                "has materially more unroutable exits, the feature behaves more like a copyability/tail-risk "
                "discriminator than pure post-entry price alpha. This is diagnostic only."
            ),
        },
    }

    destination = output_path or (run_dir / "buy-event-acceleration-decomposition-v0.json")
    destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["artifact"] = str(destination.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Decompose BUY-acceleration ITERATE result into price-vs-exitability effects")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_decomposition(run_dir=args.run_dir, output_path=args.output)
    except Exception as exc:
        print(json.dumps({
            "classification": "FAIL_BUY_EVENT_ACCELERATION_DECOMPOSITION_V0",
            "error": f"{type(exc).__name__}:{exc}",
        }, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
