"""Feature-only opening fee dynamics for Pons V2 launches.

Pons documents that ``CurveBuy.fee`` contains the base trade fee plus any opening
snipe tax, while ``CurveBuy.tax`` is the creator tax.  This module deliberately
measures the event-observed combined fee instead of trying to infer a hidden
snipe component without the launch's causal ``feeBps`` state.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from src.robinhood_pons_launch_burst_v0 import (
    WINDOWS_SECONDS,
    PonsLaunchObservationV0,
    PonsTradeObservationV0,
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _bps(numerator: int, denominator: int) -> float | None:
    return 10_000.0 * numerator / denominator if denominator > 0 else None


def _percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    low = int(position)
    high = min(low + 1, len(values) - 1)
    fraction = position - low
    return values[low] * (1 - fraction) + values[high] * fraction


def _summary(values):
    values = [float(value) for value in values if value is not None]
    return {
        "n": len(values),
        "p50": _percentile(values, 0.5),
        "p75": _percentile(values, 0.75),
        "p90": _percentile(values, 0.90),
        "p95": _percentile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
    }


def build_fee_dynamics_snapshot_v0(*, launch, trades, horizon_seconds: int) -> dict:
    if horizon_seconds not in WINDOWS_SECONDS:
        raise ValueError(f"unsupported horizon: {horizon_seconds}")
    cutoff = launch.observed_at_ns + horizon_seconds * 1_000_000_000
    buys = sorted(
        (
            trade
            for trade in trades
            if trade.curve == launch.curve
            and trade.side == "BUY"
            and launch.observed_at_ns <= trade.observed_at_ns <= cutoff
        ),
        key=lambda trade: (trade.observed_at_ns, trade.chain_order),
    )
    rows = []
    for trade in buys:
        fee_bps = _bps(trade.fee_raw, trade.quote_amount_raw)
        creator_tax_bps = _bps(trade.tax_raw, trade.quote_amount_raw)
        total_charge_bps = _bps(trade.fee_raw + trade.tax_raw, trade.quote_amount_raw)
        chain_age_s = None
        if launch.block_timestamp_s is not None and trade.block_timestamp_s is not None:
            chain_age_s = trade.block_timestamp_s - launch.block_timestamp_s
        rows.append(
            {
                "actor": trade.actor,
                "known_deployer_exempt": trade.actor == launch.deployer,
                "local_age_ms": (trade.observed_at_ns - launch.observed_at_ns) / 1_000_000.0,
                "chain_age_s": chain_age_s,
                "fee_bps_observed": fee_bps,
                "creator_tax_bps_observed": creator_tax_bps,
                "total_charge_bps_observed": total_charge_bps,
                "quote_amount_raw": trade.quote_amount_raw,
            }
        )
    non_deployer = [row for row in rows if not row["known_deployer_exempt"]]
    fee_values = [row["fee_bps_observed"] for row in rows if row["fee_bps_observed"] is not None]
    non_deployer_fees = [
        row["fee_bps_observed"]
        for row in non_deployer
        if row["fee_bps_observed"] is not None
    ]
    first_fee = fee_values[0] if fee_values else None
    last_fee = fee_values[-1] if fee_values else None
    return {
        "type": "pons_opening_fee_dynamics_snapshot_v0",
        "token": launch.token,
        "curve": launch.curve,
        "pair_token": launch.pair_token,
        "native_eth_cohort": launch.is_native_eth_quote,
        "horizon_seconds": horizon_seconds,
        "buy_count": len(rows),
        "non_deployer_buy_count": len(non_deployer),
        "first_buy_local_age_ms": rows[0]["local_age_ms"] if rows else None,
        "last_buy_local_age_ms": rows[-1]["local_age_ms"] if rows else None,
        "first_buy_chain_age_s": rows[0]["chain_age_s"] if rows else None,
        "last_buy_chain_age_s": rows[-1]["chain_age_s"] if rows else None,
        "first_buy_fee_bps_observed": first_fee,
        "last_buy_fee_bps_observed": last_fee,
        "min_buy_fee_bps_observed": min(fee_values) if fee_values else None,
        "median_buy_fee_bps_observed": median(fee_values) if fee_values else None,
        "max_buy_fee_bps_observed": max(fee_values) if fee_values else None,
        "fee_drop_first_to_last_bps": (first_fee - last_fee if first_fee is not None and last_fee is not None else None),
        "first_non_deployer_buy_fee_bps_observed": non_deployer_fees[0] if non_deployer_fees else None,
        "min_non_deployer_buy_fee_bps_observed": min(non_deployer_fees) if non_deployer_fees else None,
        "buy_observations": rows,
        "notes": [
            "CurveBuy.fee_is_base_fee_plus_any_snipe_tax_per_Pons_docs",
            "CurveBuy.tax_is_creator_tax_reported_separately",
            "deployer_is_known_snipe_exempt_but_other_exemptions_may_exist",
            "non_deployer_does_not_imply_taxed_because_launch_specific_exemptions_can_exist",
            "no_snipe_component_is_inferred_without_causal_curve_fee_state",
        ],
    }


def build_fee_report_v0(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    events = _read_jsonl(run_dir / "events.jsonl")
    launches = {}
    trades = defaultdict(list)
    for row in events:
        kind = row.get("kind")
        data = {key: value for key, value in row.items() if key != "kind"}
        if kind == "launch":
            launch = PonsLaunchObservationV0(**data)
            launches[launch.curve] = launch
        elif kind == "trade":
            trade = PonsTradeObservationV0(**data)
            trades[trade.curve].append(trade)

    finished_ns = int(report.get("finished_wall_ns") or 0)
    snapshots = []
    for launch in launches.values():
        for horizon in WINDOWS_SECONDS:
            if launch.observed_at_ns + horizon * 1_000_000_000 <= finished_ns:
                snapshots.append(
                    build_fee_dynamics_snapshot_v0(
                        launch=launch,
                        trades=trades.get(launch.curve, ()),
                        horizon_seconds=horizon,
                    )
                )

    summary = {}
    for horizon in WINDOWS_SECONDS:
        cohort = [
            row
            for row in snapshots
            if row["native_eth_cohort"] and row["horizon_seconds"] == horizon
        ]
        summary[str(horizon)] = {
            "n": len(cohort),
            "nonempty": sum(row["buy_count"] > 0 for row in cohort),
            "first_buy_fee_bps_observed": _summary(
                [row["first_buy_fee_bps_observed"] for row in cohort]
            ),
            "min_buy_fee_bps_observed": _summary(
                [row["min_buy_fee_bps_observed"] for row in cohort]
            ),
            "first_non_deployer_buy_fee_bps_observed": _summary(
                [row["first_non_deployer_buy_fee_bps_observed"] for row in cohort]
            ),
            "fee_drop_first_to_last_bps": _summary(
                [row["fee_drop_first_to_last_bps"] for row in cohort]
            ),
            "first_buy_local_age_ms": _summary(
                [row["first_buy_local_age_ms"] for row in cohort]
            ),
            "first_buy_chain_age_s": _summary(
                [row["first_buy_chain_age_s"] for row in cohort]
            ),
        }

    return {
        "type": "robinhood_pons_opening_fee_dynamics_report_v0",
        "feature_only": True,
        "economic_outcomes_opened": False,
        "selector_frozen": False,
        "run_dir": str(run_dir),
        "native_eth_launches": sum(launch.is_native_eth_quote for launch in launches.values()),
        "feature_report_native_eth": summary,
        "snapshots": snapshots,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = build_fee_report_v0(Path(args.run_dir))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    compact = {key: value for key, value in result.items() if key != "snapshots"}
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
