from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from benchmarks.launch_burst_replay_v0.run import run_replay


TRAJECTORY_AUDIT_VERSION = "launch_burst_trajectory_audit_v0_outcome_blind"
DEFAULT_WINDOWS_SECONDS = (5, 10, 30)
COUNT_FEATURES = (
    "event_count",
    "buy_count",
    "sell_count",
    "unique_wallet_count",
    "unique_transaction_count",
)


def _pct(num: float, den: float) -> float | None:
    if den == 0:
        return None
    return 100.0 * num / den


def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * fraction
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    w = pos - lo
    return ordered[lo] * (1.0 - w) + ordered[hi] * w


def _dist(values: Iterable[float | int | None]) -> dict[str, float | int | None]:
    xs = [float(v) for v in values if v is not None]
    return {
        "count": len(xs),
        "min": min(xs) if xs else None,
        "p25": _percentile(xs, 0.25),
        "p50": _percentile(xs, 0.50),
        "p75": _percentile(xs, 0.75),
        "p90": _percentile(xs, 0.90),
        "max": max(xs) if xs else None,
    }


def _imbalance(snapshot: dict[str, Any]) -> float | None:
    events = int(snapshot.get("event_count") or 0)
    if events <= 0:
        return None
    buys = int(snapshot.get("buy_count") or 0)
    sells = int(snapshot.get("sell_count") or 0)
    return 100.0 * (buys - sells) / events


def _wallets_per_event(snapshot: dict[str, Any]) -> float | None:
    events = int(snapshot.get("event_count") or 0)
    if events <= 0:
        return None
    return float(snapshot.get("unique_wallet_count") or 0) / events


def _index(replay: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in replay["snapshots"]:
        key = (str(item["anchor_event_key"]), str(item["stratum"]))
        if key in result:
            raise RuntimeError(f"duplicate trajectory key: {key}")
        result[key] = item
    return result


def _transition_rows(
    left: dict[tuple[str, str], dict[str, Any]],
    right: dict[tuple[str, str], dict[str, Any]],
    *,
    from_seconds: int,
    to_seconds: int,
    stratum: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    keys = sorted(set(left) & set(right))
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    for key in keys:
        if key[1] != stratum:
            continue
        a = left[key]
        b = right[key]
        for feature in COUNT_FEATURES:
            if int(b.get(feature) or 0) < int(a.get(feature) or 0):
                violations.append(f"{key[0]}:{feature}:{from_seconds}->{to_seconds}")
        event_a = int(a.get("event_count") or 0)
        event_b = int(b.get("event_count") or 0)
        wallet_a = int(a.get("unique_wallet_count") or 0)
        wallet_b = int(b.get("unique_wallet_count") or 0)
        tx_a = int(a.get("unique_transaction_count") or 0)
        tx_b = int(b.get("unique_transaction_count") or 0)
        buy_share_a = a.get("count_buy_share_pct")
        buy_share_b = b.get("count_buy_share_pct")
        imb_a = _imbalance(a)
        imb_b = _imbalance(b)
        wpe_a = _wallets_per_event(a)
        wpe_b = _wallets_per_event(b)
        rows.append(
            {
                "anchor_event_key": key[0],
                "stratum": stratum,
                "events_from": event_a,
                "events_to": event_b,
                "new_events": event_b - event_a,
                "event_growth_ratio": (event_b / event_a) if event_a > 0 else None,
                "activated_after_from_window": event_a == 0 and event_b > 0,
                "new_wallets": wallet_b - wallet_a,
                "new_transactions": tx_b - tx_a,
                "buy_share_delta_pp": (
                    float(buy_share_b) - float(buy_share_a)
                    if buy_share_a is not None and buy_share_b is not None
                    else None
                ),
                "imbalance_delta_pp": (
                    float(imb_b) - float(imb_a)
                    if imb_a is not None and imb_b is not None
                    else None
                ),
                "wallets_per_event_delta": (
                    float(wpe_b) - float(wpe_a)
                    if wpe_a is not None and wpe_b is not None
                    else None
                ),
            }
        )
    return rows, violations


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "paired_launch_count": len(rows),
        "activated_after_from_window_count": sum(
            1 for row in rows if row["activated_after_from_window"]
        ),
        "activated_after_from_window_pct": _pct(
            sum(1 for row in rows if row["activated_after_from_window"]), len(rows)
        ),
        "features": {
            name: _dist(row[name] for row in rows)
            for name in (
                "new_events",
                "event_growth_ratio",
                "new_wallets",
                "new_transactions",
                "buy_share_delta_pp",
                "imbalance_delta_pp",
                "wallets_per_event_delta",
            )
        },
    }


def run_trajectory_audit(
    *, run_a: str, run_b: str, windows_seconds: tuple[int, ...]
) -> dict[str, Any]:
    windows = tuple(sorted(set(int(w) for w in windows_seconds)))
    if len(windows) < 2 or any(w <= 0 for w in windows):
        raise ValueError("at least two positive windows are required")
    cohorts: dict[str, Any] = {}
    all_violations: list[str] = []
    for label, run_key in (("A", run_a), ("B", run_b)):
        replays = {w: run_replay(acquisition_run_key=run_key, window_seconds=w) for w in windows}
        indexes = {w: _index(replay) for w, replay in replays.items()}
        transitions: dict[str, Any] = {}
        strata = sorted(
            set().union(
                *({item["stratum"] for item in replay["snapshots"]} for replay in replays.values())
            )
        )
        for left_w, right_w in zip(windows, windows[1:]):
            tkey = f"{left_w}->{right_w}"
            transitions[tkey] = {}
            for stratum in strata:
                rows, violations = _transition_rows(
                    indexes[left_w], indexes[right_w],
                    from_seconds=left_w, to_seconds=right_w, stratum=stratum,
                )
                all_violations.extend(f"{label}:{item}" for item in violations)
                if rows:
                    transitions[tkey][stratum] = _summary(rows)
        cohorts[label] = {
            "acquisition_run_key": run_key,
            "transitions": transitions,
        }
    return {
        "type": "launch_burst_trajectory_audit",
        "version": TRAJECTORY_AUDIT_VERSION,
        "windows_seconds": list(windows),
        "cohorts": cohorts,
        "monotonicity_violation_count": len(all_violations),
        "monotonicity_violations": all_violations,
        "scientific_lock": {
            "outcome_blind": True,
            "future_outcomes_loaded": False,
            "economic_thresholds_defined": False,
            "trajectory_thresholds_selected": False,
            "pnl_reported": False,
            "anchor_join_key": "anchor_event_key+stratum",
        },
        "interpretation_guardrails": [
            "Use trajectory features for hypothesis generation only.",
            "Do not infer sub-second timing from this DB-shadow.",
            "Do not select economic thresholds from this report.",
            "Absolute level features may shift across cohorts; within-launch deltas are the primary object here.",
        ],
    }


def _parse_windows(text: str) -> tuple[int, ...]:
    values = tuple(sorted({int(x.strip()) for x in text.split(",") if x.strip()}))
    if len(values) < 2 or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("windows must contain at least two positive integers")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Outcome-blind within-launch Burst trajectory audit")
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--windows", type=_parse_windows, default=DEFAULT_WINDOWS_SECONDS)
    parser.add_argument("--output", default="artifacts/launch_burst_trajectory_audit_v0/report.json")
    args = parser.parse_args()
    report = run_trajectory_audit(
        run_a=args.run_a, run_b=args.run_b, windows_seconds=tuple(args.windows)
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(output)
    print(
        "Launch Burst Trajectory Audit V0 "
        f"A={args.run_a} B={args.run_b} windows={list(args.windows)} "
        f"monotonicity_violations={report['monotonicity_violation_count']}"
    )
    print(f"output={output}")
    return 0 if report["monotonicity_violation_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
