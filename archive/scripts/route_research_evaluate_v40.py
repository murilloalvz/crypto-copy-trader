from __future__ import annotations

import argparse
import math

from src.route_research_evaluation import evaluate_route_research_run


def _fmt(value: float | None, suffix: str = "%") -> str:
    if value is None:
        return "n/a"
    if math.isinf(value):
        return "inf"
    return f"{value:+.3f}{suffix}" if suffix else f"{value:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate causal route-only BUY->SELL forward research outcomes without claiming execution."
    )
    parser.add_argument("--run-key", required=True)
    args = parser.parse_args()

    result = evaluate_route_research_run(acquisition_run_key=args.run_key)
    print("Crypto Copy Trader — Route-Only Forward Research Evaluation v40")
    print(
        "Mode: PAPER / RESEARCH — non-executable causal route quotes only. "
        "No landing/fill/profitability claim."
    )
    print(f"run_key={args.run_key} lineage_violations={result.lineage_violations}")
    for row in result.horizons:
        pf = "n/a" if row.profit_factor is None else ("inf" if math.isinf(row.profit_factor) else f"{row.profit_factor:.3f}")
        print(f"\nHORIZON {row.horizon_seconds}s")
        print(
            f"scheduled={row.scheduled} available={row.available} pending={row.pending} "
            f"unavailable_or_error={row.unavailable_or_error} coverage={row.coverage_pct:.1f}%"
        )
        print(
            f"positive_share={_fmt(row.positive_share_pct)} mean={_fmt(row.mean_return_pct)} "
            f"median={_fmt(row.median_return_pct)} profit_factor={pf}"
        )
        print(
            f"best={_fmt(row.best_return_pct)} worst={_fmt(row.worst_return_pct)} "
            f"mean_without_best={_fmt(row.mean_without_best_pct)} "
            f"largest_winner_share_gross_profit={_fmt(row.largest_winner_share_of_gross_profit_pct)}"
        )
        print(f"classification={row.classification}")

    print(
        "\nInterpretation rule: these returns compare causal route-only quote prices for the exact "
        "quoted token amount. They are not realized wallet PnL, do not include landing/fill risk, "
        "and do not establish edge when samples are small."
    )
    return 2 if result.lineage_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
