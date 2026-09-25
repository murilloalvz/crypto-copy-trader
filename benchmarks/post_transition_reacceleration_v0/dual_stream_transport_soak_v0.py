from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from websockets.asyncio.client import connect

from benchmarks.post_transition_reacceleration_v0.prospective_lineage_readiness_v1 import (
    _subscription_source,
)
from benchmarks.post_transition_reacceleration_v0.systems_probe import (
    candidate_wss_urls,
)
from src.pump_bonding_stream import (
    build_logs_subscribe_request as build_pump_subscribe_request,
)
from src.pumpswap_stream import (
    build_logs_subscribe_request as build_pumpswap_subscribe_request,
)


VERSION = "post_transition_dual_stream_transport_soak_v0"
PASS = "PASS_POST_TRANSITION_DUAL_STREAM_TRANSPORT_SOAK_V0"
FAIL = "FAIL_POST_TRANSITION_DUAL_STREAM_TRANSPORT_SOAK_V0"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _classify(
    *,
    pump_raw: int,
    pumpswap_raw: int,
    elapsed_seconds: float,
    requested_seconds: int,
    max_idle_seconds: float,
    idle_timeout_seconds: int,
) -> tuple[str, str]:
    if elapsed_seconds < max(0.0, float(requested_seconds) - 1.0):
        return FAIL, "duration_not_completed"
    if max_idle_seconds >= float(idle_timeout_seconds):
        return FAIL, "idle_timeout_reached"
    if pump_raw < 20 or pumpswap_raw < 20:
        return FAIL, "insufficient_dual_stream_traffic"
    return PASS, "dual_stream_transport_soak_completed"


async def _probe_candidate(
    *,
    label: str,
    url: str,
    duration_seconds: int,
    idle_timeout_seconds: int,
) -> dict:
    host = str(urlparse(url).hostname or "unknown")
    counts = {"pump": 0, "pumpswap": 0}
    started = time.monotonic()
    last_raw = started
    max_idle = 0.0
    transport_error = None

    try:
        async with connect(
            url,
            open_timeout=10,
            ping_interval=None,
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

            ack_by_id = {}
            while len(ack_by_id) < 2:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                payload = json.loads(raw)
                if payload.get("id") in {1, 2}:
                    ack_by_id[int(payload["id"])] = payload

            for request_id, name in ((1, "pump"), (2, "pumpswap")):
                ack = ack_by_id[request_id]
                if "error" in ack or not isinstance(ack.get("result"), int):
                    raise RuntimeError(f"invalid {name} subscribe ack: {ack}")

            pump_id = int(ack_by_id[1]["result"])
            pumpswap_id = int(ack_by_id[2]["result"])
            started = time.monotonic()
            last_raw = started
            deadline = started + float(duration_seconds)

            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(),
                        timeout=min(0.5, max(0.05, remaining)),
                    )
                except asyncio.TimeoutError:
                    now = time.monotonic()
                    idle = now - last_raw
                    max_idle = max(max_idle, idle)
                    if idle >= float(idle_timeout_seconds):
                        raise RuntimeError(
                            "transport_idle_timeout_during_soak"
                        )
                    continue

                now = time.monotonic()
                gap = now - last_raw
                max_idle = max(max_idle, gap)
                last_raw = now

                payload = json.loads(raw)
                source = _subscription_source(
                    payload,
                    pump_subscription_id=pump_id,
                    pumpswap_subscription_id=pumpswap_id,
                )
                if source in counts:
                    counts[source] += 1

    except Exception as exc:
        transport_error = f"{type(exc).__name__}:{exc}"[:500]

    elapsed = max(0.0, time.monotonic() - started)
    if transport_error is not None:
        classification, reason = FAIL, "transport_error"
    else:
        classification, reason = _classify(
            pump_raw=counts["pump"],
            pumpswap_raw=counts["pumpswap"],
            elapsed_seconds=elapsed,
            requested_seconds=duration_seconds,
            max_idle_seconds=max_idle,
            idle_timeout_seconds=idle_timeout_seconds,
        )

    return {
        "candidate": label,
        "host": host,
        "classification": classification,
        "reason": reason,
        "duration_seconds_requested": duration_seconds,
        "elapsed_seconds": elapsed,
        "idle_timeout_seconds": idle_timeout_seconds,
        "max_idle_seconds": max_idle,
        "pump_raw": counts["pump"],
        "pumpswap_raw": counts["pumpswap"],
        "transport_error": transport_error,
        "economic_outcomes_opened": False,
        "provider_economic_calls_used": False,
        "live_money": False,
    }


async def run_soak(
    *,
    duration_seconds: int,
    idle_timeout_seconds: int,
) -> dict:
    attempts = []
    for label, url in candidate_wss_urls():
        result = await _probe_candidate(
            label=label,
            url=url,
            duration_seconds=duration_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        attempts.append(result)
        if result["classification"] == PASS:
            return {
                "type": VERSION,
                "version": VERSION,
                "classification": PASS,
                "reason": "at_least_one_candidate_completed_dual_stream_soak",
                "selected_candidate": label,
                "selected_host": result["host"],
                "attempts": attempts,
                "economic_outcomes_opened": False,
                "provider_economic_calls_used": False,
                "live_money": False,
            }

    return {
        "type": VERSION,
        "version": VERSION,
        "classification": FAIL,
        "reason": "no_candidate_completed_dual_stream_soak",
        "selected_candidate": None,
        "selected_host": None,
        "attempts": attempts,
        "economic_outcomes_opened": False,
        "provider_economic_calls_used": False,
        "live_money": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--idle-timeout-seconds", type=int, default=15)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.duration_seconds <= 0:
        raise SystemExit("--duration-seconds must be positive")
    if args.idle_timeout_seconds <= 0:
        raise SystemExit("--idle-timeout-seconds must be positive")

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    report = asyncio.run(
        run_soak(
            duration_seconds=args.duration_seconds,
            idle_timeout_seconds=args.idle_timeout_seconds,
        )
    )

    if args.output is not None:
        _write_json(args.output, report)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
