from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from benchmarks.market_first_capacity_harness_v0.shadow_signal_plane import TriggerRecordingKernelV0
from benchmarks.market_first_signal_plane_v0 import replay as base_replay
from src.market_signal_kernel_v3 import (
    MARKET_SIGNAL_KERNEL_V3_VERSION,
    TriggerRecordingMarketSignalKernelV3,
)


PASS_CLASSIFICATION = "PASS_MARKET_FIRST_SIGNAL_PLANE_V0_KERNEL_V3_REPLAY"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_SIGNAL_PLANE_V0_KERNEL_V3_REPLAY"


def run_signal_plane_kernel_v3_replay_v0(**kwargs):
    signal_kernel = TriggerRecordingMarketSignalKernelV3()
    shadow_kernel = TriggerRecordingKernelV0()
    with patch.object(
        base_replay,
        "TriggerRecordingKernelV0",
        side_effect=[signal_kernel, shadow_kernel],
    ):
        result = base_replay.run_signal_plane_replay_v0(**kwargs)
    passed = all(result.get("gates", {}).values())
    result["type"] = "market_first_signal_plane_v0_kernel_v3_replay"
    result["signal_kernel_version"] = MARKET_SIGNAL_KERNEL_V3_VERSION
    result["shadow_reference_kernel_version"] = "indexed_market_signal_kernel_v2_clock_domains"
    result["classification"] = PASS_CLASSIFICATION if passed else FAIL_CLASSIFICATION
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acceptance replay for deferred continuation durability plus Signal Kernel V3."
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-identities", type=Path, required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_signal_plane_kernel_v3_replay_v0(
        live_report_path=args.live_report,
        raw_dir=args.raw_dir,
        processed_root=args.processed_dir,
        bootstrap_identities_path=args.bootstrap_identities,
        database_source_path=args.database_source,
        max_chunks=args.max_chunks,
        cargo=args.cargo,
    )
    text = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
