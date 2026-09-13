from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from src.database import connection
from src.launch_burst_v0 import LaunchBurstConfig, build_launch_burst_snapshot
from src.market_observation_store import ensure_market_observation_schema
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


REPLAY_VERSION = "launch_burst_replay_v0_feature_only"


def _load_rows(acquisition_run_key: str):
    ensure_market_observation_schema()
    with connection() as conn:
        lifecycle_rows = conn.execute(
            """SELECT event_key, source_provider, token_mint, market_started_at,
                      observed_at, venue, id
               FROM market_lifecycle_observations
               WHERE acquisition_run_key=?
               ORDER BY observed_at, market_started_at, id""",
            (acquisition_run_key,),
        ).fetchall()
        trade_rows = conn.execute(
            """SELECT event_key, source_provider, token_mint, side, chain_time,
                      observed_at, wallet_address, notional_usd, price_usd, venue,
                      transaction_key, id
               FROM market_trade_observations
               WHERE acquisition_run_key=?
               ORDER BY observed_at, chain_time, id""",
            (acquisition_run_key,),
        ).fetchall()
        max_observed = conn.execute(
            """SELECT MAX(value) AS max_observed FROM (
                   SELECT MAX(observed_at) AS value
                   FROM market_lifecycle_observations WHERE acquisition_run_key=?
                   UNION ALL
                   SELECT MAX(observed_at) AS value
                   FROM market_trade_observations WHERE acquisition_run_key=?
               )""",
            (acquisition_run_key, acquisition_run_key),
        ).fetchone()
    return lifecycle_rows, trade_rows, (
        int(max_observed["max_observed"])
        if max_observed is not None and max_observed["max_observed"] is not None
        else None
    )


def _first_causal_anchors(lifecycle_rows):
    anchors = {}
    later_rows = {}
    for row in lifecycle_rows:
        venue = str(row["venue"] or "")
        key = (str(row["token_mint"]), venue)
        if key not in anchors:
            anchors[key] = row
        else:
            later_rows.setdefault(key, []).append(row)
    return anchors, later_rows


def _trade_from_row(row) -> MarketTradeObservation:
    return MarketTradeObservation(
        token_mint=str(row["token_mint"]),
        side=str(row["side"]),
        chain_time=int(row["chain_time"]),
        observed_at=int(row["observed_at"]),
        wallet_address=(
            str(row["wallet_address"]) if row["wallet_address"] is not None else None
        ),
        notional_usd=(
            float(row["notional_usd"]) if row["notional_usd"] is not None else None
        ),
        price_usd=(float(row["price_usd"]) if row["price_usd"] is not None else None),
        venue=(str(row["venue"]) if row["venue"] is not None else None),
        transaction_key=(
            str(row["transaction_key"]) if row["transaction_key"] is not None else None
        ),
    )


def run_replay(*, acquisition_run_key: str, window_seconds: int) -> dict:
    if not acquisition_run_key.strip():
        raise ValueError("acquisition_run_key cannot be empty")
    config = LaunchBurstConfig(observation_window_seconds=window_seconds)
    lifecycle_rows, trade_rows, run_max_observed_at = _load_rows(acquisition_run_key)
    anchors, later_rows = _first_causal_anchors(lifecycle_rows)

    trades_by_token = {}
    for row in trade_rows:
        trades_by_token.setdefault(str(row["token_mint"]), []).append(_trade_from_row(row))

    snapshots = []
    right_censored = []
    unsupported_venue = []
    late_earlier_audit = []

    for (token_mint, venue), row in anchors.items():
        observed_t0 = int(row["observed_at"])
        decision_as_of = observed_t0 + window_seconds
        if venue not in {"pump_bonding_curve", "pump_swap"}:
            unsupported_venue.append(
                {
                    "token_mint": token_mint,
                    "venue": venue,
                    "event_key": str(row["event_key"]),
                }
            )
            continue
        if run_max_observed_at is None or run_max_observed_at < decision_as_of:
            right_censored.append(
                {
                    "token_mint": token_mint,
                    "venue": venue,
                    "event_key": str(row["event_key"]),
                    "observed_t0": observed_t0,
                    "required_decision_as_of": decision_as_of,
                }
            )
            continue

        lifecycle = MarketLifecycleObservation(
            token_mint=token_mint,
            market_started_at=int(row["market_started_at"]),
            observed_at=observed_t0,
            venue=venue,
        )
        snapshot = build_launch_burst_snapshot(
            trades_by_token.get(token_mint, ()),
            lifecycle=lifecycle,
            decision_as_of=decision_as_of,
            config=config,
        )
        payload = asdict(snapshot)
        payload["anchor_event_key"] = str(row["event_key"])
        payload["anchor_source_provider"] = str(row["source_provider"])
        snapshots.append(payload)

        for later in later_rows.get((token_mint, venue), ()):
            if int(later["market_started_at"]) < int(row["market_started_at"]):
                late_earlier_audit.append(
                    {
                        "token_mint": token_mint,
                        "venue": venue,
                        "anchor_event_key": str(row["event_key"]),
                        "anchor_market_started_at": int(row["market_started_at"]),
                        "later_event_key": str(later["event_key"]),
                        "later_market_started_at": int(later["market_started_at"]),
                        "later_observed_at": int(later["observed_at"]),
                        "candidate_snapshot_not_mutated": True,
                    }
                )

    snapshots.sort(key=lambda item: (item["observed_t0"], item["token_mint"], item["venue"]))
    strata = {}
    for snapshot in snapshots:
        strata[snapshot["stratum"]] = strata.get(snapshot["stratum"], 0) + 1

    return {
        "type": "launch_burst_replay",
        "version": REPLAY_VERSION,
        "acquisition_run_key": acquisition_run_key,
        "observation_window_seconds": window_seconds,
        "run_max_observed_at": run_max_observed_at,
        "causal_anchor_count": len(anchors),
        "snapshot_count": len(snapshots),
        "right_censored_count": len(right_censored),
        "unsupported_venue_count": len(unsupported_venue),
        "late_earlier_lifecycle_audit_count": len(late_earlier_audit),
        "strata": strata,
        "snapshots": snapshots,
        "right_censored": right_censored,
        "unsupported_venue": unsupported_venue,
        "late_earlier_lifecycle_audit": late_earlier_audit,
        "scientific_scope": {
            "feature_only": True,
            "economic_thresholds_defined": False,
            "automatic_trade_decision": False,
            "future_outcomes_used_for_candidate_selection": False,
            "pump_and_pumpswap_strata_kept_separate": True,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline causal Launch Burst feature replay v0")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument(
        "--output",
        default="artifacts/launch_burst_replay_v0/report.json",
    )
    args = parser.parse_args()
    if args.window_seconds <= 0:
        parser.error("--window-seconds must be positive")

    report = run_replay(
        acquisition_run_key=args.run_key,
        window_seconds=args.window_seconds,
    )
    output = Path(args.output)
    _write_json(output, report)
    print(
        "Launch Burst Replay V0 "
        f"run={args.run_key} snapshots={report['snapshot_count']} "
        f"right_censored={report['right_censored_count']} strata={report['strata']}"
    )
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
