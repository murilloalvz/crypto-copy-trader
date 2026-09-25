from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from src.post_transition_reacceleration_v0 import (
    PostTransitionResearchState,
)
from src.pumpswap_stream import (
    PumpSwapCreatePoolEvent,
    PumpSwapTradeEvent,
)


VERSION = "post_transition_reacceleration_offline_replay_v0"
PASS = "PASS_POST_TRANSITION_REACCELERATION_OFFLINE_REPLAY_V0"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fixture must be a JSON object")
    return payload


def build_state_from_fixture(payload: dict[str, Any]) -> PostTransitionResearchState:
    transition = payload.get("transition") or {}
    birth = payload.get("pump_birth") or {}

    create = PumpSwapCreatePoolEvent(
        pool=str(transition["pool"]),
        creator=str(transition["creator"]),
        base_mint=str(transition["base_mint"]),
        quote_mint=str(transition["quote_mint"]),
        base_mint_decimals=int(transition["base_mint_decimals"]),
        quote_mint_decimals=int(transition["quote_mint_decimals"]),
        timestamp=int(transition["timestamp"]),
    )
    state = PostTransitionResearchState.from_create_event(
        create,
        observed_at=int(transition["observed_at"]),
        pump_birth_market_started_at=(
            int(birth["market_started_at"]) if birth else None
        ),
        pump_birth_observed_at=(
            int(birth["observed_at"]) if birth else None
        ),
    )

    for row in payload.get("trades") or []:
        event = PumpSwapTradeEvent(
            side=str(row["side"]),
            pool=str(row["pool"]),
            user=str(row["user"]),
            timestamp=int(row["timestamp"]),
            base_amount_raw=int(row["base_amount_raw"]),
            quote_amount_raw=int(row["quote_amount_raw"]),
        )
        state.ingest_trade(
            event,
            observed_at=int(row["observed_at"]),
            event_key=str(row["event_key"]),
            transaction_key=str(row["transaction_key"]),
            arrival_index=int(row["arrival_index"]),
        )
    return state


def run_fixture(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema_version") != "post_transition_reacceleration_fixture_v0":
        raise ValueError("unsupported fixture schema")

    state = build_state_from_fixture(payload)
    snapshots = state.snapshots_after_each_trade()
    final = snapshots[-1] if snapshots else state.snapshot(
        as_of_observed_at=state.identity.transition_observed_at
    )

    report = {
        "type": "post_transition_reacceleration_offline_replay_report_v0",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "DISCOVERY_DIAGNOSTIC_ONLY",
        "economic_outcomes_opened": False,
        "provider_calls_used": False,
        "transition_semantics": (
            "pumpswap_create_pool_transition_anchor_not_proven_pump_graduation"
        ),
        "pump_origin_confirmed": state.identity.pump_origin_confirmed,
        "snapshot_count": len(snapshots),
        "structural_candidate_seen": any(
            snapshot.structural_reacceleration_candidate
            for snapshot in snapshots
        ),
        "final_snapshot": asdict(final),
        "snapshots": [asdict(snapshot) for snapshot in snapshots],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_fixture(args.fixture)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL_POST_TRANSITION_REACCELERATION_OFFLINE_REPLAY_V0",
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    compact = {
        "classification": report["classification"],
        "inference_role": report["inference_role"],
        "economic_outcomes_opened": report["economic_outcomes_opened"],
        "provider_calls_used": report["provider_calls_used"],
        "transition_semantics": report["transition_semantics"],
        "pump_origin_confirmed": report["pump_origin_confirmed"],
        "snapshot_count": report["snapshot_count"],
        "structural_candidate_seen": report["structural_candidate_seen"],
        "final_snapshot": report["final_snapshot"],
    }
    print(json.dumps(compact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
