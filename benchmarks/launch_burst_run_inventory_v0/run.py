from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.database import connection
from src.market_activity_discovery_run_v0 import (
    ensure_market_activity_discovery_run_schema_v0,
)
from src.market_observation_store import ensure_market_observation_schema


RUN_INVENTORY_VERSION = "launch_burst_run_inventory_v0_authoritative_closed_only"
UNKNOWN_COMPLETION = "UNKNOWN_NO_DISCOVERY_RUN_REGISTRY_ROW"


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
                item.strip()
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


def _registry_rows() -> dict[str, dict]:
    ensure_market_activity_discovery_run_schema_v0()
    with connection() as conn:
        rows = conn.execute(
            """SELECT acquisition_run_key, cohort_key, method_version, started_at,
                      admission_closes_at, status, closed_at, interruption_reason
               FROM market_activity_discovery_runs_v0
               ORDER BY started_at DESC, acquisition_run_key"""
        ).fetchall()
    return {
        str(row["acquisition_run_key"]): {
            "cohort_key": str(row["cohort_key"]),
            "method_version": str(row["method_version"]),
            "started_at": int(row["started_at"]),
            "admission_closes_at": int(row["admission_closes_at"]),
            "status": str(row["status"]),
            "closed_at": int(row["closed_at"]) if row["closed_at"] is not None else None,
            "interruption_reason": (
                str(row["interruption_reason"])
                if row["interruption_reason"] is not None
                else None
            ),
        }
        for row in rows
    }


def build_run_inventory() -> dict:
    trades = _rows_for_table("market_trade_observations")
    lifecycles = _rows_for_table("market_lifecycle_observations")
    registry = _registry_rows()
    run_keys = set(trades) | set(lifecycles) | set(registry)

    runs = []
    for key in run_keys:
        trade = trades.get(key)
        lifecycle = lifecycles.get(key)
        registered = registry.get(key)
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
        has_launch_lifecycle = bool(lifecycle and lifecycle["row_count"] > 0)
        completion_status = registered["status"] if registered else UNKNOWN_COMPLETION
        authoritative_closed = bool(registered and registered["status"] == "CLOSED")
        eligible = bool(authoritative_closed and has_launch_lifecycle)
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
                "has_launch_lifecycle": has_launch_lifecycle,
                "completion_status": completion_status,
                "completion_status_authoritative": registered is not None,
                "started_at": registered["started_at"] if registered else None,
                "admission_closes_at": (
                    registered["admission_closes_at"] if registered else None
                ),
                "closed_at": registered["closed_at"] if registered else None,
                "interruption_reason": (
                    registered["interruption_reason"] if registered else None
                ),
                "eligible_for_auto_select": eligible,
            }
        )

    runs.sort(
        key=lambda item: (
            item["started_at"] if item["started_at"] is not None else -1,
            item["max_observed_at"] if item["max_observed_at"] is not None else -1,
            item["acquisition_run_key"],
        ),
        reverse=True,
    )
    eligible = [item for item in runs if item["eligible_for_auto_select"]]
    latest = eligible[0]["acquisition_run_key"] if eligible else None

    return {
        "type": "launch_burst_run_inventory",
        "version": RUN_INVENTORY_VERSION,
        "run_count": len(runs),
        "eligible_closed_run_count": len(eligible),
        "latest_eligible_closed_run_key": latest,
        "selection_policy": (
            "only authoritative Market Activity Discovery registry rows with status=CLOSED "
            "and at least one persisted lifecycle observation are eligible"
        ),
        "runs": runs,
    }


def select_latest_closed_launch_run_key() -> str:
    inventory = build_run_inventory()
    key = inventory["latest_eligible_closed_run_key"]
    if not key:
        raise RuntimeError("no authoritative CLOSED acquisition with launch lifecycle is available")
    return str(key)


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
    print(
        f"Launch Burst Run Inventory V0 runs={report['run_count']} "
        f"eligible_closed={report['eligible_closed_run_count']}"
    )
    for item in report["runs"]:
        print(
            f"{item['acquisition_run_key']} trades={item['trade_rows']} "
            f"lifecycle={item['lifecycle_rows']} venues={item['venues']} "
            f"completion={item['completion_status']} "
            f"eligible={item['eligible_for_auto_select']}"
        )
    print(f"latest_eligible_closed_run_key={report['latest_eligible_closed_run_key']}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
