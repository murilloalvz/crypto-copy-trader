from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import time
from urllib.parse import urlparse
import uuid

from dotenv import load_dotenv
from websockets.asyncio.client import connect

from benchmarks.post_transition_reacceleration_v0.systems_probe import (
    candidate_wss_urls,
)
from src.market_observation_store import (
    inspect_known_market_lifecycle,
    record_market_lifecycle,
)
from src.market_opportunity_radar import MarketLifecycleObservation
from src.post_transition_reacceleration_v0 import PostTransitionResearchState
from src.post_transition_snapshot_journal_v0 import (
    ImmutableSnapshotJournalV0,
    verify_snapshot_journal,
)
from src.pump_bonding_stream import (
    PumpLogNotification,
    build_logs_subscribe_request as build_pump_subscribe_request,
    parse_logs_notification as parse_pump_logs_notification,
)
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_stream import (
    build_logs_subscribe_request as build_pumpswap_subscribe_request,
    parse_logs_notification as parse_pumpswap_logs_notification,
)


VERSION = "post_transition_prospective_lineage_readiness_v1"
PASS = "PASS_POST_TRANSITION_PROSPECTIVE_LINEAGE_READINESS_V1"
INCONCLUSIVE = "INCONCLUSIVE_POST_TRANSITION_PROSPECTIVE_LINEAGE_READINESS_V1"
FAIL = "FAIL_POST_TRANSITION_PROSPECTIVE_LINEAGE_READINESS_V1"
DECISION_DELAY_SECONDS = 30


def _subscription_source(
    message: dict,
    *,
    pump_subscription_id: int,
    pumpswap_subscription_id: int,
) -> str | None:
    if message.get("method") != "logsNotification":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    subscription = params.get("subscription")
    if subscription == pump_subscription_id:
        return "pump"
    if subscription == pumpswap_subscription_id:
        return "pumpswap"
    return None


def _persist_pump_births(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
) -> tuple[int, int]:
    seen = 0
    inserted = 0
    for index, event in enumerate(notification.lifecycle_events):
        seen += 1
        created = record_market_lifecycle(
            acquisition_run_key=acquisition_run_key,
            event_key=f"pump-create:{notification.signature}:{index}",
            source_provider="post_transition_dual_stream_v1",
            observation=MarketLifecycleObservation(
                token_mint=event.mint,
                market_started_at=event.timestamp,
                observed_at=notification.observed_at,
                venue="pump_bonding_curve",
            ),
        )
        if created:
            inserted += 1
    return seen, inserted


async def _probe_dual_candidate(label: str, url: str) -> dict:
    host = str(urlparse(url).hostname or "unknown")
    try:
        async with connect(
            url,
            open_timeout=8,
            ping_interval=None,
            close_timeout=3,
            max_size=2 * 1024 * 1024,
        ) as ws:
            await ws.send(
                json.dumps(
                    build_pump_subscribe_request(
                        request_id=1,
                        commitment="processed",
                    ),
                    separators=(",", ":"),
                )
            )
            await ws.send(
                json.dumps(
                    build_pumpswap_subscribe_request(
                        request_id=2,
                        commitment="processed",
                    ),
                    separators=(",", ":"),
                )
            )

            ack_by_id: dict[int, dict] = {}
            while len(ack_by_id) < 2:
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
                payload = json.loads(raw)
                if payload.get("id") in {1, 2}:
                    ack_by_id[int(payload["id"])] = payload

            for request_id, name in ((1, "pump"), (2, "pumpswap")):
                ack = ack_by_id[request_id]
                if "error" in ack:
                    raise RuntimeError(
                        f"{name} subscription RPC error: {ack['error']}"
                    )
                if not isinstance(ack.get("result"), int):
                    raise RuntimeError(
                        f"{name} subscription acknowledgement missing id"
                    )

        return {
            "candidate": label,
            "host": host,
            "status": "PASS",
            "pump_ack": True,
            "pumpswap_ack": True,
        }
    except Exception as exc:
        return {
            "candidate": label,
            "host": host,
            "status": "FAIL",
            "error": f"{type(exc).__name__}:{exc}"[:320],
        }


async def resolve_dual_wss() -> tuple[str | None, list[dict]]:
    attempts: list[dict] = []
    for label, url in candidate_wss_urls():
        result = await _probe_dual_candidate(label, url)
        attempts.append(result)
        if result["status"] == "PASS":
            return url, attempts
    return None, attempts


async def run_prospective_lineage_readiness(
    *,
    duration_seconds: int,
    journal_path: Path,
) -> dict:
    if duration_seconds <= DECISION_DELAY_SECONDS:
        raise ValueError(
            "duration_seconds must exceed the frozen 30s decision delay"
        )

    selected, attempts = await resolve_dual_wss()
    if selected is None:
        return {
            "type": "post_transition_prospective_lineage_readiness_report_v1",
            "version": VERSION,
            "classification": FAIL,
            "reason": "no_wss_candidate_accepted_both_pump_and_pumpswap",
            "transport_attempts": attempts,
            "economic_outcomes_opened": False,
            "provider_economic_calls_used": False,
        }

    acquisition_run_key = (
        f"post-transition-lineage-v1-{int(time.time())}-"
        f"{uuid.uuid4().hex[:10]}"
    )
    journal = ImmutableSnapshotJournalV0(journal_path)
    counters: Counter[str] = Counter()
    states: dict[str, PostTransitionResearchState] = {}
    arrival_by_pool: dict[str, int] = {}
    decision_due_at: dict[str, int] = {}
    decision_emitted: set[str] = set()
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
                counters[
                    "decision_snapshots_with_structural_reacceleration"
                ] += 1

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
                    build_pump_subscribe_request(
                        request_id=1,
                        commitment="processed",
                    ),
                    separators=(",", ":"),
                )
            )
            await ws.send(
                json.dumps(
                    build_pumpswap_subscribe_request(
                        request_id=2,
                        commitment="processed",
                    ),
                    separators=(",", ":"),
                )
            )

            ack_by_id: dict[int, dict] = {}
            while len(ack_by_id) < 2:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                ack = json.loads(raw)
                if ack.get("id") in {1, 2}:
                    ack_by_id[int(ack["id"])] = ack
            for request_id, name in ((1, "pump"), (2, "pumpswap")):
                ack = ack_by_id[request_id]
                if "error" in ack or not isinstance(ack.get("result"), int):
                    raise RuntimeError(
                        f"invalid {name} subscribe ack: {ack}"
                    )

            pump_subscription_id = int(ack_by_id[1]["result"])
            pumpswap_subscription_id = int(ack_by_id[2]["result"])
            counters["dual_subscription_acks"] = 2

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
                except json.JSONDecodeError:
                    counters["json_decode_errors"] += 1
                    continue

                source = _subscription_source(
                    message,
                    pump_subscription_id=pump_subscription_id,
                    pumpswap_subscription_id=pumpswap_subscription_id,
                )
                if source is None:
                    counters["unrouted_messages"] += 1
                    continue

                if source == "pump":
                    counters["pump_notifications_raw"] += 1
                    try:
                        notification = parse_pump_logs_notification(
                            message,
                            observed_at=observed_at,
                        )
                    except ValueError:
                        counters["pump_notification_decode_errors"] += 1
                        continue
                    if notification is None:
                        continue
                    counters["pump_notifications_decoded"] += 1
                    seen, inserted = _persist_pump_births(
                        notification,
                        acquisition_run_key=acquisition_run_key,
                    )
                    counters["pump_create_events"] += seen
                    counters["pump_births_persisted"] += inserted
                    continue

                counters["pumpswap_notifications_raw"] += 1
                try:
                    notification = parse_pumpswap_logs_notification(
                        message,
                        observed_at=observed_at,
                    )
                except ValueError:
                    counters["pumpswap_notification_decode_errors"] += 1
                    continue
                if notification is None:
                    continue
                counters["pumpswap_notifications_decoded"] += 1

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

                    if (
                        lineage.lifecycle.acquisition_run_key
                        == acquisition_run_key
                    ):
                        counters["pump_lineage_found_current_run"] += 1
                    else:
                        counters["pump_lineage_found_preexisting"] += 1

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
                    decision_due_at[event.pool] = (
                        notification.observed_at + DECISION_DELAY_SECONDS
                    )
                    counters["lineage_eligible_transition_states"] += 1

                for event in notification.trade_events:
                    counters["pumpswap_trade_events"] += 1
                    state = states.get(event.pool)
                    if state is None:
                        counters[
                            "trade_without_lineage_eligible_transition"
                        ] += 1
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
        reason = (
            "prospective_pump_birth_to_pumpswap_transition_snapshot_observed"
        )
    else:
        classification = INCONCLUSIVE
        reason = (
            "no_complete_prospective_lineage_eligible_30s_snapshot_observed"
        )

    return {
        "type": "post_transition_prospective_lineage_readiness_report_v1",
        "version": VERSION,
        "classification": classification,
        "reason": reason,
        "acquisition_run_key": acquisition_run_key,
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
        "historical_backfill_used": False,
        "structural_marker_used_as_selector": False,
        "fresh_economic_discovery_authorized": False,
        "interpretation": (
            "Dual-stream readiness only. Pump births are persisted when "
            "observed on the same ordered websocket stream and can qualify "
            "only PumpSwap transitions learned afterward. No historical "
            "backfill, Jupiter outcome, selector mutation or edge claim is "
            "permitted."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    report = asyncio.run(
        run_prospective_lineage_readiness(
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
