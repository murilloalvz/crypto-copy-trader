from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from websockets.asyncio.client import connect

from benchmarks.post_transition_reacceleration_v0.systems_probe import (
    resolve_wss,
)
from src.market_observation_store import inspect_known_market_lifecycle
from src.post_transition_reacceleration_v0 import PostTransitionResearchState
from src.post_transition_snapshot_journal_v0 import (
    ImmutableSnapshotJournalV0,
    verify_snapshot_journal,
)
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_stream import (
    build_logs_subscribe_request,
    parse_logs_notification,
)


VERSION = "post_transition_research_readiness_v0"
PASS = "PASS_POST_TRANSITION_RESEARCH_READINESS_V0"
INCONCLUSIVE = "INCONCLUSIVE_POST_TRANSITION_RESEARCH_READINESS_V0"
FAIL = "FAIL_POST_TRANSITION_RESEARCH_READINESS_V0"
DECISION_DELAY_SECONDS = 30


async def run_readiness(
    *,
    duration_seconds: int,
    journal_path: Path,
) -> dict:
    if duration_seconds <= DECISION_DELAY_SECONDS:
        raise ValueError(
            "duration_seconds must exceed the frozen 30s decision delay"
        )

    selected, attempts = await resolve_wss()
    if selected is None:
        return {
            "type": "post_transition_research_readiness_report_v0",
            "version": VERSION,
            "classification": FAIL,
            "reason": "no_wss_candidate_accepted_pumpswap_logs_subscribe",
            "transport_attempts": attempts,
            "economic_outcomes_opened": False,
            "provider_economic_calls_used": False,
        }

    journal = ImmutableSnapshotJournalV0(journal_path)
    counters: Counter[str] = Counter()
    states: dict[str, PostTransitionResearchState] = {}
    arrival_by_pool: dict[str, int] = {}
    decision_due_at: dict[str, int] = {}
    decision_emitted: set[str] = set()
    transition_token_by_pool: dict[str, str] = {}
    started = time.monotonic()
    deadline = started + float(duration_seconds)
    transport_error = None
    journal_error = None

    def freeze_due(now_wall_second: int) -> None:
        nonlocal journal_error
        for pool, due_at in sorted(decision_due_at.items()):
            if pool in decision_emitted or due_at > now_wall_second:
                continue
            state = states[pool]
            if not state._available_rows(due_at):
                counters["decision_snapshot_missing_no_trade"] += 1
                decision_emitted.add(pool)
                continue

            max_arrival = arrival_by_pool.get(pool, 0) - 1
            try:
                snapshot = state.snapshot(
                    as_of_observed_at=due_at,
                    max_arrival_index=max_arrival,
                )
                inserted, _record = journal.append(snapshot)
            except Exception as exc:
                journal_error = f"{type(exc).__name__}:{exc}"[:320]
                return

            decision_emitted.add(pool)
            counters["decision_snapshots_frozen"] += 1
            if inserted:
                counters["decision_snapshots_persisted"] += 1
            else:
                counters["decision_snapshot_idempotent_replays"] += 1
            if snapshot.pullback_observed:
                counters["decision_snapshots_with_pullback"] += 1
            if snapshot.structural_reacceleration_candidate:
                counters["decision_snapshots_with_structural_reacceleration"] += 1

    try:
        async with connect(
            selected,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=16 * 1024 * 1024,
        ) as ws:
            await ws.send(
                json.dumps(
                    build_logs_subscribe_request(
                        request_id=1,
                        commitment="processed",
                    ),
                    separators=(",", ":"),
                )
            )
            ack = json.loads(
                await asyncio.wait_for(ws.recv(), timeout=10)
            )
            if "error" in ack or not isinstance(ack.get("result"), int):
                raise RuntimeError(
                    f"invalid PumpSwap subscribe ack: {ack}"
                )

            while time.monotonic() < deadline:
                freeze_due(int(time.time()))
                if journal_error is not None:
                    break

                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(),
                        timeout=min(2.0, max(0.05, remaining)),
                    )
                except asyncio.TimeoutError:
                    continue

                observed_at = int(time.time())
                try:
                    message = json.loads(raw)
                    notification = parse_logs_notification(
                        message,
                        observed_at=observed_at,
                    )
                except (ValueError, json.JSONDecodeError):
                    counters["notification_decode_errors"] += 1
                    continue
                if notification is None:
                    continue
                counters["notifications"] += 1

                for event in notification.lifecycle_events:
                    counters["create_pool_events"] += 1
                    role = classify_pumpswap_opportunity_asset(
                        base_mint=event.base_mint,
                        quote_mint=event.quote_mint,
                    )
                    if role is None:
                        counters["transition_asset_role_ambiguous"] += 1
                        continue
                    counters["role_valid_transition_events"] += 1

                    lineage = inspect_known_market_lifecycle(
                        token_mint=role.opportunity_mint,
                        as_of=notification.observed_at,
                        venue="pump_bonding_curve",
                    )
                    counters[
                        f"pump_lineage_{lineage.status.lower()}"
                    ] += 1
                    if lineage.status != "FOUND" or lineage.lifecycle is None:
                        continue

                    birth = lineage.lifecycle.observation
                    if birth.market_started_at > event.timestamp:
                        counters["pump_lineage_chronology_invalid"] += 1
                        continue
                    if birth.observed_at > notification.observed_at:
                        counters["pump_lineage_availability_invalid"] += 1
                        continue

                    try:
                        state = PostTransitionResearchState.from_create_event(
                            event,
                            observed_at=notification.observed_at,
                            pump_birth_market_started_at=birth.market_started_at,
                            pump_birth_observed_at=birth.observed_at,
                        )
                    except ValueError:
                        counters["eligible_transition_state_errors"] += 1
                        continue

                    states[event.pool] = state
                    arrival_by_pool[event.pool] = 0
                    transition_token_by_pool[event.pool] = role.opportunity_mint
                    decision_due_at[event.pool] = (
                        notification.observed_at + DECISION_DELAY_SECONDS
                    )
                    counters["lineage_eligible_transition_states"] += 1

                for event in notification.trade_events:
                    counters["trade_events"] += 1
                    state = states.get(event.pool)
                    if state is None:
                        counters["trade_without_lineage_eligible_transition"] += 1
                        continue
                    if event.pool in decision_emitted:
                        counters["trade_after_decision_freeze"] += 1
                        continue

                    try:
                        arrival_index = arrival_by_pool[event.pool]
                        state.ingest_trade(
                            event,
                            observed_at=notification.observed_at,
                            event_key=(
                                f"pumpswap-{event.side}:"
                                f"{notification.signature}:{event.event_index}"
                            ),
                            transaction_key=notification.signature,
                            arrival_index=arrival_index,
                        )
                        arrival_by_pool[event.pool] = arrival_index + 1
                        counters["eligible_anchored_trades"] += 1
                    except ValueError:
                        counters["eligible_trade_state_errors"] += 1

            freeze_due(int(time.time()))
    except Exception as exc:
        transport_error = f"{type(exc).__name__}:{exc}"[:320]

    elapsed = max(0.0, time.monotonic() - started)
    journal_summary = None
    if journal_error is None:
        try:
            journal_summary = verify_snapshot_journal(journal_path)
        except Exception as exc:
            journal_error = f"{type(exc).__name__}:{exc}"[:320]

    if transport_error is not None or journal_error is not None:
        classification = FAIL
        reason = "transport_or_snapshot_journal_error"
    elif (
        counters["lineage_eligible_transition_states"] > 0
        and counters["decision_snapshots_persisted"] > 0
        and journal_summary is not None
        and journal_summary.get("hash_chain_valid") is True
    ):
        classification = PASS
        reason = "lineage_eligible_transition_and_immutable_snapshot_observed"
    else:
        classification = INCONCLUSIVE
        reason = "no_complete_lineage_eligible_30s_snapshot_observed"

    return {
        "type": "post_transition_research_readiness_report_v0",
        "version": VERSION,
        "classification": classification,
        "reason": reason,
        "duration_seconds_requested": duration_seconds,
        "elapsed_seconds": elapsed,
        "decision_delay_seconds_frozen": DECISION_DELAY_SECONDS,
        "selected_wss_host": str(urlparse(selected).hostname or "unknown"),
        "transport_attempts": attempts,
        "transport_error": transport_error,
        "snapshot_journal_error": journal_error,
        "counters": dict(sorted(counters.items())),
        "lineage_eligible_active_state_count": len(states),
        "decision_pending_count": len(
            set(decision_due_at) - decision_emitted
        ),
        "journal": journal_summary,
        "economic_outcomes_opened": False,
        "provider_economic_calls_used": False,
        "structural_marker_used_as_selector": False,
        "fresh_economic_discovery_authorized": False,
        "interpretation": (
            "Readiness-only causal lineage and immutable snapshot gate. PASS "
            "proves that a prior Pump birth can be causally joined to a direct "
            "PumpSwap transition and frozen once at transition+30s. It opens "
            "no Jupiter economic outcome and is not an edge verdict."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    report = asyncio.run(
        run_readiness(
            duration_seconds=args.duration_seconds,
            journal_path=args.journal,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] in {PASS, INCONCLUSIVE} else 2


if __name__ == "__main__":
    raise SystemExit(main())
