from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report must be a JSON object")
    return payload


def summarize(report: dict) -> dict:
    processing = report.get("processing") or {}
    systems = report.get("systems") or {}
    gates = report.get("gates") or {}
    capture = report.get("capture") or {}
    return {
        "run": report.get("acquisition_run_key"),
        "classification": report.get("classification"),
        "mode": report.get("mode"),
        "provider_calls_enabled": report.get("provider_calls_enabled"),
        "economic_outcomes_opened": report.get("economic_outcomes_opened"),
        "stop_reason": capture.get("stop_reason"),
        "chunks": report.get("chunk_count"),
        "empty_watermark_chunks": report.get("empty_watermark_chunk_count"),
        "processing": {
            "queue_wait_ms": processing.get("queue_wait_ms"),
            "total_service_ms": processing.get("total_service_ms"),
            "decoder_service_ms": processing.get("decoder_service_ms"),
            "max_queue_depth": processing.get("max_queue_depth"),
        },
        "systems": {
            "snapshot_dispatch_lag_ms": systems.get("snapshot_dispatch_lag_ms"),
            "selected_count": systems.get("selected_count"),
            "selected_before_entry_ready": systems.get("selected_before_entry_ready"),
            "selected_before_deadline": systems.get("selected_before_deadline"),
            "selected_missed_deadline": systems.get("selected_missed_deadline"),
        },
        "gates": gates,
    }


def latest_report(root: Path) -> Path:
    candidates = [path for path in root.glob("*/report.json") if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"no V4 report.json under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact Launch Burst V4 report summary")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=Path("C:/lbv4"))
    args = parser.parse_args()
    try:
        path = args.report or latest_report(args.root)
        output = summarize(_read_json(path))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
