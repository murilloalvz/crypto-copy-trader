from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.carbon_stream_bridge_v0.benchmark import run_benchmark

VERSION = "carbon_stream_bridge_v0_diagnostic_matrix"
RATES = (1000.0, 2500.0, 5000.0)
DURATION_SECONDS = 1.0


def run_matrix(*, binary: Path) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for rate in RATES:
        events = int(rate * DURATION_SECONDS)
        report = run_benchmark(binary=binary, events=events, target_rate=rate)
        latency = report["round_trip_latency_ms"]
        scenarios.append(
            {
                "target_ingress_events_per_second": rate,
                "input_events": events,
                "achieved_ingress_events_per_second": report[
                    "achieved_ingress_events_per_second"
                ],
                "decoded_events": report["decoded_events"],
                "decode_failures": report["decode_failures"],
                "input_errors": report["input_errors"],
                "order_violations": report["order_violations"],
                "max_inflight_events": report["max_inflight_events"],
                "round_trip_latency_ms": latency,
                "v0_gate_classification": report["classification"],
            }
        )

    return {
        "type": "carbon_stream_bridge_diagnostic_matrix",
        "version": VERSION,
        "rates_events_per_second": list(RATES),
        "duration_seconds_per_scenario": DURATION_SECONDS,
        "scenarios": scenarios,
        "classification": "DIAGNOSTIC_ONLY_NO_PROMOTION_VERDICT",
        "notes": [
            "This matrix reuses the frozen v0 sidecar and does not alter v0 thresholds.",
            "Its only purpose is to localize load-dependent local IPC/queue behavior before a new transport candidate is preregistered.",
            "Each scenario preserves exact order/accounting checks from v0.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostic rate matrix for frozen Carbon stream bridge v0")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = run_matrix(binary=args.binary)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
