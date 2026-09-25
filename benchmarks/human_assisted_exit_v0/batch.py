from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.human_assisted_exit_v0.run import (
    DEFAULT_POLICY,
    PASS,
    _aggregate_returns,
    _write_json,
    run_diagnostic,
)


VERSION = "causal_human_exit_historical_batch_v0"
PASS_BATCH = "PASS_CAUSAL_HUMAN_EXIT_HISTORICAL_BATCH_V0"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)


def run_batch(
    *,
    run_dirs: list[Path],
    contract_path: Path,
    policy_path: Path,
    output_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    if not run_dirs:
        raise ValueError("at least one historical run directory is required")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []

    for index, run_dir in enumerate(run_dirs, start=1):
        run_dir = Path(run_dir).resolve()
        route_result = run_dir / "route-result-v2.json"
        market_paths = run_dir / "market-paths-smart-ladder-25-v0.json"
        if not route_result.is_file():
            raise ValueError(f"missing route-result-v2.json: {run_dir}")
        if not market_paths.is_file():
            raise ValueError(
                f"missing market-paths-smart-ladder-25-v0.json: {run_dir}"
            )

        per_run_output = (
            output_dir / f"{index:02d}-{run_dir.name}-human-exit-v0.json"
        )
        report = run_diagnostic(
            contract_path=contract_path,
            policy_path=policy_path,
            route_result_path=route_result,
            market_paths_path=market_paths,
            output_path=per_run_output,
        )
        if report.get("classification") != PASS:
            raise RuntimeError(f"historical diagnostic failed: {run_dir}")

        runs.append(
            {
                "run_dir": str(run_dir),
                "run_name": run_dir.name,
                "result_path": str(per_run_output.resolve()),
                "paired_path_trade_count": report.get(
                    "paired_path_trade_count"
                ),
                "causal_exit_triggered_count": report.get(
                    "causal_exit_triggered_count"
                ),
                "causal_exit_trigger_rate_pct": report.get(
                    "causal_exit_trigger_rate_pct"
                ),
                "exit_reason_counts": report.get("exit_reason_counts"),
                "fixed_60_all_path_entries": report.get(
                    "fixed_60_all_path_entries"
                ),
                "triggered_subset": report.get("triggered_subset"),
                "market_path": report.get("market_path"),
            }
        )
        for trade in report.get("trades") or []:
            all_trades.append(
                {
                    **trade,
                    "historical_run_name": run_dir.name,
                }
            )

    triggered = [
        trade
        for trade in all_trades
        if (trade.get("human_exit") or {}).get("status") == "CLOSED"
    ]
    fixed_all = [
        float(trade["fixed_60_return_pct"])
        for trade in all_trades
    ]
    fixed_triggered = [
        float(trade["fixed_60_return_pct"])
        for trade in triggered
    ]
    human_triggered = [
        float(trade["human_exit"]["simulated_exit_return_pct"])
        for trade in triggered
    ]
    differences = [
        float(trade["human_minus_fixed_pct_points"])
        for trade in triggered
    ]
    better_count = sum(
        trade.get("human_exit_better_than_fixed") is True
        for trade in triggered
    )

    result = {
        "type": "causal_human_exit_historical_batch_report_v0",
        "version": VERSION,
        "classification": PASS_BATCH,
        "historical_run_count": len(runs),
        "total_paired_path_trade_count": len(all_trades),
        "total_causal_exit_triggered_count": len(triggered),
        "total_causal_exit_trigger_rate_pct": (
            100.0 * len(triggered) / len(all_trades)
            if all_trades
            else None
        ),
        "runs": runs,
        "aggregate": {
            "fixed_60_all_path_entries": _aggregate_returns(fixed_all),
            "triggered_subset_fixed_60": _aggregate_returns(
                fixed_triggered
            ),
            "triggered_subset_causal_human_exit": _aggregate_returns(
                human_triggered
            ),
            "human_minus_fixed_mean_pct_points": (
                sum(differences) / len(differences)
                if differences
                else None
            ),
            "human_exit_better_count": better_count,
            "human_exit_better_share_pct": (
                100.0 * better_count / len(triggered)
                if triggered
                else None
            ),
        },
        "guardrails": {
            "retrospective_only": True,
            "same_frozen_policy_all_runs": True,
            "per_run_retuning": False,
            "confirms_signal_edge": False,
            "confirms_human_assisted_edge": False,
            "confirms_autonomous_edge": False,
            "historical_results_can_only_inform_future_preregistration": True,
        },
        "interpretation": (
            "The same frozen causal human-exit policy is applied unchanged "
            "to multiple already-collected real-market route-shadow paths. "
            "Consistency across historical runs is diagnostic only; it does "
            "not replace fresh prospective evaluation."
        ),
    }
    _write_json(output_path, result)
    return result


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": result.get("classification"),
        "historical_run_count": result.get("historical_run_count"),
        "total_paired_path_trade_count": result.get(
            "total_paired_path_trade_count"
        ),
        "total_causal_exit_triggered_count": result.get(
            "total_causal_exit_triggered_count"
        ),
        "total_causal_exit_trigger_rate_pct": result.get(
            "total_causal_exit_trigger_rate_pct"
        ),
        "aggregate": result.get("aggregate"),
        "runs": result.get("runs"),
        "guardrails": result.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        required=True,
        help="Existing real-market V4 run directory; repeat for each run.",
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = run_batch(
            run_dirs=list(args.run_dir),
            contract_path=args.contract,
            policy_path=args.policy,
            output_dir=args.output_dir,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": (
                        "FAIL_CAUSAL_HUMAN_EXIT_HISTORICAL_BATCH_V0"
                    ),
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(_compact(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
