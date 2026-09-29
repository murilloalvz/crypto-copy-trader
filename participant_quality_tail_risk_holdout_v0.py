from __future__ import annotations

import argparse
import json
from pathlib import Path

import participant_quality_native_holdout_v1 as holdout

# Frozen for THIS preregistration only — see
# docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md
# Does not touch or reinterpret the closed KILL selector's own frozen
# constants (participant-quality-native-memory-rolefix-20260924-03-*,
# cutoff -65.65233776856643). Reuses the acquisition/evaluation logic
# unchanged, only swapped to this run's own fresh memory lineage/cutoff.
holdout.MEMORY_RUN_KEYS = (
    "participant-quality-tail-risk-v0-20260929-01-M1",
    "participant-quality-tail-risk-v0-20260929-01-M2",
    "participant-quality-tail-risk-v0-20260929-01-M3",
    "participant-quality-tail-risk-v0-20260929-01-M4",
)
holdout.FROZEN_CUTOFF = -86.0484432047999
holdout.VERSION = "participant_quality_tail_risk_holdout_v0"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Holdout acquisition for the tail-risk rejection preregistration, "
            "reusing participant_quality_native_holdout_v1's logic with this "
            "run's own frozen memory lineage and cutoff."
        )
    )
    parser.add_argument("--base-run-key", required=True)
    parser.add_argument("--memory-report", required=True, type=Path)
    parser.add_argument("--bootstrap-report", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/participant_quality_tail_risk_holdout_v0"),
    )
    args = parser.parse_args()

    report = holdout.run_holdout(
        base_run_key=args.base_run_key,
        memory_report=args.memory_report,
        bootstrap_report=args.bootstrap_report,
        acquisition_duration_seconds=args.duration_seconds,
        artifact_root=args.artifact_root,
    )
    holdout.print_summary(report)
    return 0 if str(report.get("classification", "")).startswith(
        ("KEEP_", "KILL_")
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
