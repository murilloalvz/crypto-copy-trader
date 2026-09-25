from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv
from websockets.asyncio.client import connect

from src.post_transition_reacceleration_v0 import PostTransitionResearchState
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_stream import (
    build_logs_subscribe_request,
    parse_logs_notification,
)


VERSION = "post_transition_reacceleration_systems_probe_v0"
PASS = "PASS_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_V0"
INCONCLUSIVE = "INCONCLUSIVE_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_NO_TRANSITION"
FAIL = "FAIL_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_V0"


def _http_to_ws(url: str) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme == "https":
        scheme = "wss"
    elif parsed.scheme == "http":
        scheme = "ws"
    elif parsed.scheme in {"wss", "ws"}:
        scheme = parsed.scheme
    else:
        return None
    if not parsed.netloc:
        return None
    return urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def candidate_wss_urls() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    explicit = _http_to_ws(os.environ.get("SOLANA_LOGS_WSS_URL", ""))
    if explicit:
        candidates.append(("explicit_logs_wss", explicit))

    primary = _http_to_ws(os.environ.get("SOLANA_RPC_URL", ""))
    if primary:
        candidates.append(("solana_rpc_primary", primary))

    for index, raw in enumerate(
        os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(","),
        start=1,
    ):
        url = _http_to_ws(raw)
        if url:
            candidates.append((f"solana_rpc_fallback_{index}", url))

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, url in candidates:
        if url in seen:
            continue
        seen.add(url)
        deduped.append((label, url))
    return deduped


async def _probe_candidate(label: str, url: str) -> dict:
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
                    build_logs_subscribe_request(
                        request_id=1,
                        commitment="processed",
                    ),
                    separators=(",", ":"),
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=8)
            ack = json.loads(raw)
            if "error" in ack:
                raise RuntimeError(f"subscription RPC error: {ack['error']}")
            if not isinstance(ack.get("result"), int):
                raise RuntimeError("subscription acknowledgement missing id")
        return {
            "candidate": label,
            "host": host,
            "status": "PASS",
        }
    except Exception as exc:
        message = f"{type(exc).__name__}:{exc}"
        return {
            "candidate": label,
            "host": host,
            "status": "FAIL",
            "error": message[:320],
        }


async def resolve_wss() -> tuple[str | None, list[dict]]:
    attempts: list[dict] = []
    for label, url in candidate_wss_urls():
        result = await _probe_candidate(label, url)
        attempts.append(result)
        if result["status"] == "PASS":
            return url, attempts
    return None, attempts


async def run_probe(*, duration_seconds: int) -> dict:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    selected, attempts = await resolve_wss()
    if selected is None:
        return {
            "type": "post_transition_reacceleration_systems_probe_report_v0",
            "version": VERSION,
            "classification": FAIL,
            "reason": "no_wss_candidate_accepted_pumpswap_logs_subscribe",
            "transport_attempts": attempts,
            "economic_outcomes_opened": False,
            "provider_economic_calls_used": False,
        }

    counters: Counter[str] = Counter()
    states: dict[str, PostTransitionResearchState] = {}
    structural_pools: set[str] = set()
    started = time.monotonic()
    deadline = started + float(duration_seconds)
    transport_error = None

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
                raise RuntimeError(f"invalid PumpSwap subscribe ack: {ack}")

            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(),
                        timeout=min(5.0, max(0.05, remaining)),
                    )
                except asyncio.TimeoutError:
                    continue

                observed_at = int(time.time())
                message = json.loads(raw)
                notification = parse_logs_notification(
                    message,
                    observed_at=observed_at,
                )
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
                        counters["ambiguous_transition_asset_role"] += 1
                        continue
                    try:
                        states[event.pool] = (
                            PostTransitionResearchState.from_create_event(
                                event,
                                observed_at=notification.observed_at,
                            )
                        )
                        counters["role_valid_transition_states"] += 1
                    except ValueError:
                        counters["transition_state_errors"] += 1

                for event in notification.trade_events:
                    counters["trade_events"] += 1
                    state = states.get(event.pool)
                    if state is None:
                        counters["trade_without_direct_transition_anchor"] += 1
                        continue
                    try:
                        state.ingest_trade(
                            event,
                            observed_at=notification.observed_at,
                            event_key=(
                                f"pumpswap-{event.side}:"
                                f"{notification.signature}:{event.event_index}"
                            ),
                            transaction_key=notification.signature,
                        )
                        counters["anchored_trades"] += 1
                        snapshot = state.snapshot(
                            as_of_observed_at=notification.observed_at
                        )
                        counters["snapshots"] += 1
                        if snapshot.pullback_observed:
                            counters["snapshots_with_pullback"] += 1
                        if snapshot.structural_reacceleration_candidate:
                            structural_pools.add(event.pool)
                    except ValueError:
                        counters["trade_state_errors"] += 1
    except Exception as exc:
        transport_error = f"{type(exc).__name__}:{exc}"[:320]

    elapsed = max(0.0, time.monotonic() - started)
    if transport_error is not None:
        classification = FAIL
        reason = "transport_or_decode_error"
    elif counters["role_valid_transition_states"] == 0:
        classification = INCONCLUSIVE
        reason = "no_role_valid_direct_pumpswap_transition_observed"
    else:
        classification = PASS
        reason = "direct_transition_state_observed"

    return {
        "type": "post_transition_reacceleration_systems_probe_report_v0",
        "version": VERSION,
        "classification": classification,
        "reason": reason,
        "duration_seconds_requested": duration_seconds,
        "elapsed_seconds": elapsed,
        "selected_wss_host": str(urlparse(selected).hostname or "unknown"),
        "transport_attempts": attempts,
        "transport_error": transport_error,
        "counters": dict(sorted(counters.items())),
        "active_transition_state_count": len(states),
        "structural_reacceleration_pool_count": len(structural_pools),
        "economic_outcomes_opened": False,
        "provider_economic_calls_used": False,
        "pump_origin_required_for_this_systems_probe": False,
        "pump_origin_required_before_economic_discovery": True,
        "interpretation": (
            "Systems-only availability probe. PASS proves that at least one "
            "role-valid direct PumpSwap transition can seed the causal research "
            "state. It is not an economic verdict and does not authorize fresh "
            "economic discovery by itself."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    report = asyncio.run(
        run_probe(duration_seconds=args.duration_seconds)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] in {PASS, INCONCLUSIVE} else 2


if __name__ == "__main__":
    raise SystemExit(main())
