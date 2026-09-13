from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema


RUN_INVENTORY_VERSION = "launch_burst_run_inventory_v0_fail_closed"
UNKNOWN_COMPLETION = "UNKNOWN_NOT_PROVEN_FROM_MARKET_OBSERVATION_STORE"


def _rows_for_table(table_name: str) -> dict[str, dict]:
    if table_name not in {"market_trade_observations", "market_lifecycle_observations"}:
        raise ValueError("unsupported inventory table")
    ensure_market_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT acquisition_run_key,
                       COUNT(*) AS row_count,
                       COUNT(DISTINCT token_mint) AS token_count,
                       MIN(observed_at) AS min_observed_at,
                       MAX(observed_at) AS max_observed_at,
                       GROUP_CONCAT(DISTINCT venue) AS venues
                FROM {table_name}
                GROUP BY acquisition_run_key
                ORDER BY MAX(observed_at) DESC, acquisition_run_key"""
        ).fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        venues = tuple(
            sorted(
                item
                for item in str(row["venues"] or "").split(",")
                if item.strip()
            )
        )
        result[str(row["acquisition_run_key"])] = {
            "row_count": int(row["row_count"]),
            "token_count": int(row["token_count"]),
            "min_observed_at": int(row["min_observed_at"]),
            "max_observed_at": int(row["max_observed_at"]),
            "venues": venues,
        }
    return result


def build_run_inventory() -> dict:
    trades = _rows_for_table("market_trade_observations")
    lifecycles = _rows_for_table("market_lifecycle_observations")
    run_keys = sorted(
        set(trades) | set(lifecycles),
        key=lambda key: max(
            trades.get(key, {}).get("max_observed_at", -1),
            lifecycles.get(key, {}).get("max_observed_at", -1),
        ),
        reverse=True,
    )

    runs = []
    for key in run_keys:
        trade = trades.get(key)
        lifecycle = lifecycles.get(key)
        maxima = [
            item["max_observed_at"]
            for item in (trade, lifecycle)
            if item is not None
        ]
        minima = [
            item["min_observed_at"]
            for item in (trade, lifecycle)
            if item is not None
        ]
        venues = sorted(
            set(trade["venues"] if trade else ())
            | set(lifecycle["venues"] if lifecycle else ())
        )
        runs.append(
            {
                "acquisition_run_key": key,
                "trade_rows": trade["row_count"] if trade else 0,
                "trade_tokens": trade["token_count"] if trade else 0,
                "lifecycle_rows": lifecycle["row_count"] if lifecycle else 0,
                "lifecycle_tokens": lifecycle["token_count"] if lifecycle else 0,
                "min_observed_at": min(minima) if minima else None,
                "max_observed_at": max(maxima) if maxima else None,
                "venues": venues,
                "has_launch_lifecycle": bool(lifecycle and lifecycle["row_count"] > 0),
                "completion_status": UNKNOWN_COMPLETION,
                "eligible_for_auto_select": False,
            }
        )

    return {
        "type": "launch_burst_run_inventory",
        "version": RUN_INVENTORY_VERSION,
        "run_count": len(runs),
        "auto_selection_performed": False,
        "auto_selection_reason": (
            "market observation tables do not carry authoritative acquisition completion state"
        ),
        "runs": runs,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed inventory of acquisition runs visible to Launch Burst"
    )
    parser.add_argument(
        "--output",
        default="artifacts/launch_burst_run_inventory_v0/report.json",
    )
    args = parser.parse_args()
    report = build_run_inventory()
    output = Path(args.output)
    _write_json(output, report)
    print(f"Launch Burst Run Inventory V0 runs={report['run_count']}")
    for item in report["runs"]:
        print(
            f"{item['acquisition_run_key']} trades={item['trade_rows']} "
            f"lifecycle={item['lifecycle_rows']} venues={item['venues']} "
            f"completion={item['completion_status']}"
        )
    print("auto_select=DISABLED")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
