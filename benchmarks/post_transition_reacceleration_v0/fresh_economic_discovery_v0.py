from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
from statistics import median
import time
from urllib.parse import urlparse
import uuid

from dotenv import load_dotenv
from websockets.asyncio.client import connect

from benchmarks.post_transition_reacceleration_v0.economic_collector import (
    TP50,
    TP100,
    TP200,
    assert_fresh_discovery_blocked,
    evaluate_entry,
    evaluate_episode,
    load_and_validate_contract,
)
from benchmarks.post_transition_reacceleration_v0.prospective_lineage_readiness_v1 import (
    _lineage_clock_gate,
    _persist_pump_births,
    _subscription_source,
)
from benchmarks.post_transition_reacceleration_v0.systems_probe import (
    candidate_wss_urls,
)
from src.assets import USDC_MINT
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)
from src.market_observation_store import inspect_known_market_lifecycle
from src.post_transition_reacceleration_v0 import PostTransitionResearchState
from src.post_transition_snapshot_journal_v0 import (
    ImmutableSnapshotJournalV0,
    verify_snapshot_journal,
)
from src.pump_bonding_stream import (
    build_logs_subscribe_request as build_pump_subscribe_request,
    parse_logs_notification as parse_pump_logs_notification,
)
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_stream import (
    build_logs_subscribe_request as build_pumpswap_subscribe_request,
    parse_logs_notification as parse_pumpswap_logs_notification,
)


VERSION = "post_transition_fresh_economic_discovery_v0"
PASS = "PASS_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0"
INCONCLUSIVE = "INCONCLUSIVE_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0"
FAIL = "FAIL_POST_TRANSITION_FRESH_ECONOMIC_DISCOVERY_V0"
VOID = "VOID_PRE_OUTCOME_TRANSPORT_ABORT"
USDC_DECIMALS = 6


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _redact(value: str, *secrets: str) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:1000]


def _route_offsets(contract: dict) -> list[int]:
    interval = int(contract["fresh_run"]["route_observation_interval_seconds"])
    horizon = int(contract["censoring"]["maximum_horizon_seconds"])
    grace = int(contract["fresh_run"]["route_observation_final_grace_seconds"])
    if interval != 5 or horizon != 300 or grace != 5:
        raise ValueError("fresh route grid must remain frozen at 5s / 300s / +5s grace")
    return list(range(interval, horizon + grace + 1, interval))


async def _connect_healthy_dual_candidate(
    *,
    label: str,
    url: str,
    contract: dict,
):
    host = str(urlparse(url).hostname or "unknown")
    health_seconds = int(contract["fresh_run"]["transport_health_seconds"])
    minimum = int(contract["fresh_run"]["transport_min_raw_per_source"])
    counts = {"pump": 0, "pumpswap": 0}
    ws = None
    try:
        ws = await connect(
            url,
            open_timeout=8,
            ping_interval=None,
            close_timeout=3,
            max_size=16 * 1024 * 1024,
        )
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

        ack_by_id = {}
        while len(ack_by_id) < 2:
            raw = await asyncio.wait_for(ws.recv(), timeout=8)
            payload = json.loads(raw)
            if payload.get("id") in {1, 2}:
                ack_by_id[int(payload["id"])] = payload

        for request_id, name in ((1, "pump"), (2, "pumpswap")):
            ack = ack_by_id[request_id]
            if "error" in ack or not isinstance(ack.get("result"), int):
                raise RuntimeError(f"invalid {name} subscribe ack: {ack}")

        pump_id = int(ack_by_id[1]["result"])
        pumpswap_id = int(ack_by_id[2]["result"])
        deadline = time.monotonic() + float(health_seconds)

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=min(1.0, max(0.05, remaining)),
                )
            except asyncio.TimeoutError:
                continue
            payload = json.loads(raw)
            source = _subscription_source(
                payload,
                pump_subscription_id=pump_id,
                pumpswap_subscription_id=pumpswap_id,
            )
            if source in counts:
                counts[source] += 1

        passed = counts["pump"] >= minimum and counts["pumpswap"] >= minimum
        result = {
            "candidate": label,
            "host": host,
            "status": "PASS" if passed else "FAIL",
            "health_seconds": health_seconds,
            "minimum_raw_per_source": minimum,
            "pump_raw": counts["pump"],
            "pumpswap_raw": counts["pumpswap"],
            "reason": (
                "traffic_health_ok_same_connection"
                if passed
                else "traffic_below_frozen_floor"
            ),
            "same_connection_promoted_to_capture": passed,
        }
        if not passed:
            await ws.close()
            return None, None, None, result
        return ws, pump_id, pumpswap_id, result
    except Exception as exc:
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        return None, None, None, {
            "candidate": label,
            "host": host,
            "status": "FAIL",
            "health_seconds": health_seconds,
            "minimum_raw_per_source": minimum,
            "pump_raw": counts["pump"],
            "pumpswap_raw": counts["pumpswap"],
            "reason": f"{type(exc).__name__}:{exc}"[:320],
            "same_connection_promoted_to_capture": False,
        }


async def _resolve_healthy_dual_connection(contract: dict):
    attempts = []
    for label, url in candidate_wss_urls():
        ws, pump_id, pumpswap_id, result = (
            await _connect_healthy_dual_candidate(
                label=label,
                url=url,
                contract=contract,
            )
        )
        attempts.append(result)
        if result["status"] == "PASS":
            return url, ws, pump_id, pumpswap_id, attempts
    return None, None, None, None, attempts

def _transport_idle_action(
    *,
    idle_seconds: float,
    seconds_since_ping: float,
    contract: dict,
) -> str:
    soft_idle = float(
        contract["fresh_run"]["transport_idle_timeout_seconds"]
    )
    hard_silence = float(
        contract["fresh_run"]["transport_hard_silence_seconds"]
    )
    if idle_seconds >= hard_silence:
        return "ABORT_HARD_SILENCE"
    if idle_seconds >= soft_idle and seconds_since_ping >= soft_idle:
        return "PING"
    return "WAIT"


def _classify_completion(
    *,
    transport_error: str | None,
    journal_error: str | None,
    outcomes_opened: bool,
    episode_task_errors: int,
    decision_snapshots_persisted: int,
    contract: dict,
) -> tuple[str, str]:
    if (
        transport_error is not None
        and not outcomes_opened
        and contract["fresh_run"]["pre_outcome_transport_abort_is_void"] is True
    ):
        return VOID, "pre_outcome_transport_abort_void"
    if transport_error is not None or journal_error is not None:
        return FAIL, "transport_or_snapshot_journal_error"
    if episode_task_errors > 0:
        return FAIL, "economic_episode_task_error"
    if decision_snapshots_persisted == 0:
        return INCONCLUSIVE, "no_complete_eligible_transition_plus_30s_snapshot"
    return PASS, "fresh_post_transition_economic_collection_completed"


def _aggregate(values: list[float]) -> dict:
    finite = [float(v) for v in values if math.isfinite(float(v))]
    if not finite:
        return {
            "n": 0,
            "mean_pct": None,
            "median_pct": None,
            "mean_without_best_pct": None,
            "win_rate_pct": None,
            "profit_factor": None,
            "min_pct": None,
            "max_pct": None,
        }
    gains = sum(v for v in finite if v > 0)
    losses = sum(v for v in finite if v < 0)
    without_best = list(finite)
    without_best.remove(max(without_best))
    return {
        "n": len(finite),
        "mean_pct": sum(finite) / len(finite),
        "median_pct": median(finite),
        "mean_without_best_pct": (
            sum(without_best) / len(without_best) if without_best else None
        ),
        "win_rate_pct": 100.0 * sum(v > 0 for v in finite) / len(finite),
        "profit_factor": gains / abs(losses) if losses < 0 else None,
        "min_pct": min(finite),
        "max_pct": max(finite),
    }


def _summarize(episodes: list[dict]) -> dict:
    evaluations = [item["evaluation"] for item in episodes]
    usable = [
        item
        for item in evaluations
        if item.get("included_in_conditional_economics") is True
    ]
    fixed60 = [
        float(item["fixed_60"]["net_return_pct"])
        for item in usable
        if item.get("fixed_60")
        and item["fixed_60"].get("net_return_pct") is not None
    ]
    fixed300 = [
        float(item["fixed_300"]["net_return_pct"])
        for item in usable
        if item.get("fixed_300")
        and item["fixed_300"].get("net_return_pct") is not None
    ]

    tp_summary = {}
    for name in (TP50, TP100, TP200):
        rows = [item.get(name) for item in usable if item.get(name)]
        reached = [row for row in rows if row.get("threshold_reached") is True]
        tp_summary[name] = {
            "eligible_n": len(rows),
            "reached_n": len(reached),
            "reach_rate_pct": (
                100.0 * len(reached) / len(rows) if rows else None
            ),
            "time_to_threshold_seconds": _aggregate(
                [
                    float(row["time_to_threshold_seconds"])
                    for row in reached
                    if row.get("time_to_threshold_seconds") is not None
                ]
            ),
            "net_return_if_exited_pct": _aggregate(
                [
                    float(row["net_return_if_exited_pct"])
                    for row in reached
                    if row.get("net_return_if_exited_pct") is not None
                ]
            ),
        }

    path_rows = [
        item["market_path"]["metrics"]
        for item in usable
        if item.get("market_path")
    ]
    mfe = [
        float(row["mfe_pct"])
        for row in path_rows
        if row.get("mfe_pct") is not None
    ]
    mae = [
        float(row["mae_pct"])
        for row in path_rows
        if row.get("mae_pct") is not None
    ]

    entry_counts = Counter(
        str(item.get("entry", {}).get("status") or "UNKNOWN")
        for item in evaluations
    )
    return {
        "episode_count": len(episodes),
        "entry_status_counts": dict(sorted(entry_counts.items())),
        "conditional_economic_n": len(usable),
        "fixed_60_primary": _aggregate(fixed60),
        "fixed_300_exploratory": _aggregate(fixed300),
        "take_profit": tp_summary,
        "market_path": {
            "mfe": _aggregate(mfe),
            "mae": _aggregate(mae),
            "routeable_mark_count_total": sum(
                int(row.get("routeable_mark_count") or 0) for row in path_rows
            ),
        },
        "edge_claim": "NONE_DISCOVERY_ONLY",
    }


async def _capture_episode(
    *,
    snapshot: dict,
    contract: dict,
    api_key: str,
    counters: Counter,
) -> dict:
    identity = snapshot["identity"]
    token_mint = str(identity["opportunity_mint"])
    token_decimals = int(identity["opportunity_decimals"])
    decision_as_of = int(snapshot["as_of_observed_at"])
    interval = int(contract["fresh_run"]["route_observation_interval_seconds"])
    horizon = int(contract["censoring"]["maximum_horizon_seconds"])
    grace = int(contract["fresh_run"]["route_observation_final_grace_seconds"])
    timeout = int(contract["fresh_run"]["provider_timeout_seconds"])
    entry_ready_at = decision_as_of + int(
        contract["entry"]["latency_seconds_after_decision"]
    )
    quotes = []
    provider_attempts: list[dict] = []

    now = time.time()
    if now < entry_ready_at:
        await asyncio.sleep(entry_ready_at - now)

    counters["economic_provider_calls_started"] += 1
    counters["entry_provider_calls_started"] += 1
    started = int(time.time())
    try:
        order = await asyncio.to_thread(
            JupiterSwapV2Client(api_key=api_key, timeout=timeout).order,
            input_mint=USDC_MINT,
            output_mint=token_mint,
            amount_raw=int(
                round(
                    float(contract["position"]["notional_usd"])
                    * (10**USDC_DECIMALS)
                )
            ),
            taker=None,
            slippage_bps=int(contract["costs"]["entry_adverse_slippage_bps"]),
        )
        buy = jupiter_order_to_causal_quote(
            order,
            token_mint=token_mint,
            side="buy",
            token_decimals=token_decimals,
        )
        quotes.append(buy)
        provider_attempts.append(
            {
                "side": "buy",
                "scheduled_at": entry_ready_at,
                "started_at": started,
                "observed_at": buy.observed_at,
                "status": "AVAILABLE",
                "executable": buy.executable,
                "provider_router": buy.provider_router,
                "provider_price_impact_pct_points": (
                    buy.provider_price_impact_pct_points
                ),
            }
        )
    except (JupiterOrderError, ValueError, TypeError) as exc:
        counters["entry_provider_errors"] += 1
        provider_attempts.append(
            {
                "side": "buy",
                "scheduled_at": entry_ready_at,
                "started_at": started,
                "observed_at": int(time.time()),
                "status": "ERROR",
                "error": _redact(str(exc), api_key),
            }
        )
        evaluation = evaluate_episode(
            token_mint=token_mint,
            decision_snapshot=snapshot,
            quotes=quotes,
            contract=contract,
            maximum_horizon_seconds=horizon,
        )
        return {
            "episode_key": f"{identity['pool']}:{decision_as_of}",
            "token_mint": token_mint,
            "snapshot": snapshot,
            "provider_attempts": provider_attempts,
            "evaluation": evaluation,
        }

    entry_eval = evaluate_entry(
        token_mint=token_mint,
        decision_as_of=decision_as_of,
        quotes=quotes,
        contract=contract,
    )
    if entry_eval.status != "ENTRY_USABLE" or entry_eval.quote is None:
        counters["entry_not_usable"] += 1
        evaluation = evaluate_episode(
            token_mint=token_mint,
            decision_snapshot=snapshot,
            quotes=quotes,
            contract=contract,
            maximum_horizon_seconds=horizon,
        )
        return {
            "episode_key": f"{identity['pool']}:{decision_as_of}",
            "token_mint": token_mint,
            "snapshot": snapshot,
            "provider_attempts": provider_attempts,
            "evaluation": evaluation,
        }

    counters["entry_usable"] += 1
    entry_quote = entry_eval.quote
    exact_quantity = int(str(entry_quote.output_amount_raw))
    offsets = _route_offsets(contract)

    for scheduled_offset in offsets:
        target = int(entry_quote.observed_at) + scheduled_offset
        now = time.time()
        if now < target:
            await asyncio.sleep(target - now)

        counters["economic_provider_calls_started"] += 1
        counters["exit_provider_calls_started"] += 1
        attempt_started = int(time.time())
        try:
            order = await asyncio.to_thread(
                JupiterSwapV2Client(api_key=api_key, timeout=timeout).order,
                input_mint=token_mint,
                output_mint=USDC_MINT,
                amount_raw=exact_quantity,
                taker=None,
                slippage_bps=int(
                    contract["costs"]["exit_adverse_slippage_bps"]
                ),
            )
            sell = jupiter_order_to_causal_quote(
                order,
                token_mint=token_mint,
                side="sell",
                token_decimals=token_decimals,
            )
            sell = replace(sell, resolution_seconds=interval)
            quotes.append(sell)
            provider_attempts.append(
                {
                    "side": "sell",
                    "scheduled_offset_seconds": scheduled_offset,
                    "scheduled_at": target,
                    "started_at": attempt_started,
                    "observed_at": sell.observed_at,
                    "actual_offset_seconds": (
                        sell.observed_at - int(entry_quote.observed_at)
                    ),
                    "status": "AVAILABLE",
                    "executable": sell.executable,
                    "provider_router": sell.provider_router,
                    "provider_price_impact_pct_points": (
                        sell.provider_price_impact_pct_points
                    ),
                }
            )
        except (JupiterOrderError, ValueError, TypeError) as exc:
            counters["exit_provider_errors"] += 1
            provider_attempts.append(
                {
                    "side": "sell",
                    "scheduled_offset_seconds": scheduled_offset,
                    "scheduled_at": target,
                    "started_at": attempt_started,
                    "observed_at": int(time.time()),
                    "status": "ERROR",
                    "error": _redact(str(exc), api_key),
                }
            )

    evaluation = evaluate_episode(
        token_mint=token_mint,
        decision_snapshot=snapshot,
        quotes=quotes,
        contract=contract,
        maximum_horizon_seconds=horizon,
    )
    return {
        "episode_key": f"{identity['pool']}:{decision_as_of}",
        "token_mint": token_mint,
        "snapshot": snapshot,
        "provider_attempts": provider_attempts,
        "evaluation": evaluation,
    }


async def run_fresh_discovery(
    *,
    run_dir: Path,
    api_key: str,
) -> dict:
    contract = load_and_validate_contract()
    assert_fresh_discovery_blocked(contract)

    if not api_key.strip():
        raise ValueError("JUPITER_API_KEY is required")
    admission_seconds = int(
        contract["fresh_run"]["admission_duration_seconds"]
    )
    if admission_seconds != 1800:
        raise ValueError("fresh admission duration must remain frozen at 1800s")
    if int(contract["fresh_run"]["route_observation_interval_seconds"]) != 5:
        raise ValueError("fresh route observation interval must remain frozen at 5s")
    if contract["fresh_run"]["automatic_extension_allowed"] is not False:
        raise ValueError("fresh run automatic extension must remain disabled")

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    episodes_dir = run_dir / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=False)
    journal_path = run_dir / "snapshots.jsonl"
    report_path = run_dir / "report.json"
    manifest_path = run_dir / "manifest.json"

    selected, ws, pump_subscription_id, pumpswap_subscription_id, attempts = (
        await _resolve_healthy_dual_connection(contract)
    )
    run_id = f"{VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"
    started_wall = int(time.time())
    admission_close_wall = started_wall + admission_seconds
    capture_close_wall = admission_close_wall + int(
        contract["discovery_contract"][
            "decision_delay_seconds_from_transition_observed"
        ]
    ) + 2

    manifest = {
        "type": "post_transition_fresh_economic_discovery_manifest_v0",
        "version": VERSION,
        "run_id": run_id,
        "status": "STARTED",
        "started_at": started_wall,
        "admission_close_at": admission_close_wall,
        "capture_close_at": capture_close_wall,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "fresh_run": contract["fresh_run"],
        "censoring": contract["censoring"],
        "selector_predicates": contract["discovery_contract"][
            "selector_predicates"
        ],
        "economic_outcomes_opened": False,
        "transaction_submission_authorized": False,
        "live_money_authorized": False,
    }
    _write_json(manifest_path, manifest)

    if selected is None:
        report = {
            **manifest,
            "status": "FINISHED",
            "classification": VOID,
            "reason": "no_wss_candidate_passed_frozen_traffic_health_gate",
            "transport_attempts": attempts,
        "transport_health_preflight": attempts,
            "fresh_economic_outcomes_opened": False,
            "replacement_run_authorized": True,
        }
        _write_json(report_path, report)
        return report

    acquisition_run_key = f"{run_id}:market"
    journal = ImmutableSnapshotJournalV0(journal_path)
    counters: Counter = Counter()
    states: dict[str, PostTransitionResearchState] = {}
    arrival_by_pool: dict[str, int] = {}
    decision_due_at: dict[str, int] = {}
    decision_emitted: set[str] = set()
    tasks: list[asyncio.Task] = []
    episodes: list[dict] = []
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
                snapshot_obj = state.snapshot(
                    as_of_observed_at=due_at,
                    max_arrival_index=max_arrival,
                )
                inserted, _record = journal.append(snapshot_obj)
            except Exception as exc:
                journal_error = f"{type(exc).__name__}:{exc}"[:1000]
                return

            decision_emitted.add(pool)
            counters["decision_snapshots_frozen"] += 1
            if inserted:
                counters["decision_snapshots_persisted"] += 1
            else:
                counters["decision_snapshot_idempotent_replays"] += 1
                continue

            snapshot = asdict(snapshot_obj)
            if snapshot["structural_reacceleration_candidate"]:
                counters[
                    "decision_snapshots_with_structural_reacceleration"
                ] += 1
            if snapshot["pullback_observed"]:
                counters["decision_snapshots_with_pullback"] += 1

            tasks.append(
                asyncio.create_task(
                    _capture_episode(
                        snapshot=snapshot,
                        contract=contract,
                        api_key=api_key.strip(),
                        counters=counters,
                    )
                )
            )

    try:
        if ws is None or pump_subscription_id is None or pumpswap_subscription_id is None:
            raise RuntimeError("healthy dual-stream connection missing after resolver")
        counters["dual_subscription_acks"] = 2
        last_raw_monotonic = time.monotonic()
        last_liveness_ping_monotonic = last_raw_monotonic
        ping_timeout = float(
            contract["fresh_run"][
                "transport_liveness_ping_timeout_seconds"
            ]
        )

        while int(time.time()) <= capture_close_wall:
            freeze_due(int(time.time()))
            if journal_error is not None:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
            except asyncio.TimeoutError:
                now_monotonic = time.monotonic()
                idle_seconds = now_monotonic - last_raw_monotonic
                seconds_since_ping = (
                    now_monotonic - last_liveness_ping_monotonic
                )
                action = _transport_idle_action(
                    idle_seconds=idle_seconds,
                    seconds_since_ping=seconds_since_ping,
                    contract=contract,
                )
                if action == "ABORT_HARD_SILENCE":
                    counters["transport_hard_silence_aborts"] += 1
                    raise RuntimeError(
                        "transport_hard_silence_before_capture_complete"
                    )
                if action == "PING":
                    counters["transport_liveness_ping_attempts"] += 1
                    last_liveness_ping_monotonic = now_monotonic
                    try:
                        pong_waiter = await ws.ping()
                        await asyncio.wait_for(
                            pong_waiter,
                            timeout=ping_timeout,
                        )
                    except Exception:
                        counters["transport_liveness_ping_failures"] += 1
                        if contract["fresh_run"].get(
                            "transport_ping_failure_is_fatal"
                        ) is True:
                            raise RuntimeError(
                                "transport_liveness_ping_failed"
                            )
                    else:
                        counters["transport_liveness_ping_passes"] += 1
                continue

            last_raw_monotonic = time.monotonic()
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
                if observed_at > admission_close_wall:
                    counters["transition_after_admission_close"] += 1
                    continue
                role = classify_pumpswap_opportunity_asset(
                    base_mint=event.base_mint,
                    quote_mint=event.quote_mint,
                )
                if role is None:
                    counters["transition_asset_role_ambiguous"] += 1
                    continue
                counters["role_valid_transition_events"] += 1
                if event.pool in states:
                    counters["transition_duplicate_pool_replay"] += 1
                    continue

                lineage = inspect_known_market_lifecycle(
                    token_mint=role.opportunity_mint,
                    as_of=notification.observed_at,
                    venue="pump_bonding_curve",
                )
                counters[f"pump_lineage_{lineage.status.lower()}"] += 1
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
                gate = _lineage_clock_gate(
                    birth_chain_time=birth.market_started_at,
                    birth_observed_at=birth.observed_at,
                    transition_chain_time=event.timestamp,
                    transition_observed_at=notification.observed_at,
                )
                if gate != "PASS":
                    counters[f"pump_lineage_{gate.lower()}"] += 1
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
                    notification.observed_at
                    + int(
                        contract["discovery_contract"][
                            "decision_delay_seconds_from_transition_observed"
                        ]
                    )
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
        transport_error = _redact(
            f"{type(exc).__name__}:{exc}",
            api_key,
        )
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    if tasks:
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        for item in completed:
            if isinstance(item, Exception):
                counters["episode_task_errors"] += 1
                episodes.append(
                    {
                        "episode_key": "TASK_ERROR",
                        "error": _redact(
                            f"{type(item).__name__}:{item}",
                            api_key,
                        ),
                    }
                )
                continue
            episodes.append(item)
            episode_path = episodes_dir / (
                str(item["episode_key"]).replace(":", "-") + ".json"
            )
            _write_json(episode_path, item)

    journal_summary = None
    if journal_error is None:
        try:
            journal_summary = verify_snapshot_journal(journal_path)
        except Exception as exc:
            journal_error = f"{type(exc).__name__}:{exc}"[:1000]

    opened = counters["economic_provider_calls_started"] > 0
    classification, reason = _classify_completion(
        transport_error=transport_error,
        journal_error=journal_error,
        outcomes_opened=opened,
        episode_task_errors=int(counters["episode_task_errors"]),
        decision_snapshots_persisted=int(
            counters["decision_snapshots_persisted"]
        ),
        contract=contract,
    )

    report = {
        "type": "post_transition_fresh_economic_discovery_report_v0",
        "version": VERSION,
        "classification": classification,
        "reason": reason,
        "run_id": run_id,
        "acquisition_run_key": acquisition_run_key,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "started_at": started_wall,
        "admission_close_at": admission_close_wall,
        "capture_close_at": capture_close_wall,
        "ended_at": int(time.time()),
        "selected_wss_host": str(urlparse(selected).hostname or "unknown"),
        "transport_attempts": attempts,
        "transport_error": transport_error,
        "snapshot_journal_error": journal_error,
        "journal": journal_summary,
        "counters": dict(sorted(counters.items())),
        "fresh_run": contract["fresh_run"],
        "censoring": contract["censoring"],
        "selector_predicates": contract["discovery_contract"][
            "selector_predicates"
        ],
        "structural_marker_used_as_selector": False,
        "dynamic_exits_armed": False,
        "fresh_economic_discovery_authorized": True,
        "fresh_economic_outcomes_opened": opened,
        "replacement_run_authorized": classification == VOID,
        "transaction_submitted": False,
        "live_money": False,
        "summary": _summarize(
            [item for item in episodes if "evaluation" in item]
        ),
        "episodes": episodes,
        "interpretation": (
            "Fresh prospective Post-Transition discovery under the frozen "
            "empty-selector cohort, +30s decision, +2s route-only paper entry, "
            "US$25 notional, 300s right-censoring and 5s observed Jupiter "
            "route grid. Fixed+60 remains PRIMARY; Fixed+300 remains "
            "EXPLORATORY. TP50/TP100/TP200 are independent. MFE/MAE are "
            "descriptive outcomes only. No live transaction is signed or "
            "submitted and no edge claim is made automatically."
        ),
    }
    _write_json(report_path, report)

    manifest["status"] = "FINISHED"
    manifest["ended_at"] = report["ended_at"]
    manifest["classification"] = classification
    manifest["economic_outcomes_opened"] = opened
    _write_json(manifest_path, manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    try:
        report = asyncio.run(
            run_fresh_discovery(
                run_dir=args.run_dir,
                api_key=os.environ.get("JUPITER_API_KEY", ""),
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": FAIL,
                    "error": _redact(
                        f"{type(exc).__name__}:{exc}",
                        os.environ.get("JUPITER_API_KEY", ""),
                    ),
                    "transaction_submitted": False,
                    "live_money": False,
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] in {PASS, INCONCLUSIVE} else 2


if __name__ == "__main__":
    raise SystemExit(main())
