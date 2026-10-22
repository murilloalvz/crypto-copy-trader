from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import participant_quality_native_holdout_v1 as holdout

# Replication of the already-PASSED Participant Quality Tail-Risk Rejection V0
# (docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md;
# commit 3914c6d; artifacts/participant_quality_tail_risk_holdout_v0/
# participant-quality-tail-risk-v0-20260929-04-report.json), per
# docs/participant-quality-tail-risk-replication-v1-preregistration-2026-10-07.md.
#
# Reuses participant_quality_native_holdout_v1's acquisition/evaluation logic
# unchanged (same pattern as the V0 run's own
# participant_quality_tail_risk_holdout_v0.py, left untouched and still
# reproducible). Two differences from that V0 wrapper, both required by the
# replication rule "same frozen rule, new sample":
#
# 1. MEMORY_RUN_KEYS points at a brand-new memory-build lineage (this
#    replication's own M1-M4, built causally from the new period's data) --
#    same mechanism as V0, just a new lineage.
# 2. FROZEN_CUTOFF stays pinned at V0's own realized number
#    (-86.0484432047999) instead of becoming whatever this new sample's own
#    memory build happens to compute. A cutoff that is recomputed from each
#    new sample is a re-applied *procedure*, not a frozen *rule* -- the
#    threshold itself would silently drift sample to sample. Freezing the
#    actual number is what makes this a true replication of the same rule,
#    not a parallel independent discovery that coincidentally reuses the
#    method. Consequently _validate_memory_report's cutoff-equality check
#    (correct for V0, where the cutoff was defined BY that memory build) is
#    replaced below: it must not reject a new memory build merely because
#    its own fresh-sample cutoff differs from the pinned V0 number -- that
#    mismatch is the expected, intentional case here.
V0_FROZEN_CUTOFF = -86.0484432047999
V0_FAVORABLE_GROUP = "HIGH"

holdout.FROZEN_CUTOFF = V0_FROZEN_CUTOFF
holdout.FAVORABLE_GROUP = V0_FAVORABLE_GROUP
holdout.VERSION = "participant_quality_tail_risk_replication_v1"

LAST_FRESH_SAMPLE_CUTOFF: float | None = None


def _validate_memory_report_frozen_cutoff(path: Path) -> dict[str, Any]:
    """Same checks as holdout._validate_memory_report, except it does not
    require this sample's own outcome_blind_median_cutoff to equal the
    pinned V0 cutoff -- see module docstring. Records what the fresh
    sample's own cutoff would have been (audit only, never used for
    grouping)."""
    global LAST_FRESH_SAMPLE_CUTOFF
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("version") != holdout.MEMORY_VERSION:
        raise ValueError("memory report version mismatch")
    if report.get("classification") != holdout.MEMORY_REPORT_CLASSIFICATION:
        raise ValueError("memory report is not holdout-ready")
    if tuple(report.get("run_keys") or ()) != holdout.MEMORY_RUN_KEYS:
        raise ValueError("memory run keys do not match this replication's own lineage")
    audit = report.get("coverage_audit") or {}
    if audit.get("favorable_direction") != holdout.FAVORABLE_GROUP:
        raise ValueError("favorable direction mismatch")
    fresh_cutoff = holdout._finite(audit.get("outcome_blind_median_cutoff"))
    if fresh_cutoff is None:
        raise ValueError("fresh sample produced no outcome-blind cutoff")
    LAST_FRESH_SAMPLE_CUTOFF = fresh_cutoff
    return report


holdout._validate_memory_report = _validate_memory_report_frozen_cutoff


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Holdout acquisition for the PQ-TR-V0 replication, reusing "
            "participant_quality_native_holdout_v1's logic with a new memory "
            "lineage and V0's own pinned (not recomputed) cutoff."
        )
    )
    parser.add_argument(
        "--memory-run-key-base",
        required=True,
        help=(
            "base key of this replication's own fresh memory build "
            "(the M1-M4 lineage), e.g. "
            "participant-quality-tail-risk-replication-v1-20261007-01"
        ),
    )
    parser.add_argument("--base-run-key", required=True)
    parser.add_argument("--memory-report", required=True, type=Path)
    parser.add_argument("--bootstrap-report", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/participant_quality_tail_risk_replication_v1"),
    )
    args = parser.parse_args()

    holdout.MEMORY_RUN_KEYS = tuple(
        f"{args.memory_run_key_base}-M{index}" for index in range(1, 5)
    )

    report = holdout.run_holdout(
        base_run_key=args.base_run_key,
        memory_report=args.memory_report,
        bootstrap_report=args.bootstrap_report,
        acquisition_duration_seconds=args.duration_seconds,
        artifact_root=args.artifact_root,
    )
    holdout.print_summary(report)
    print(f"v0_frozen_cutoff_pinned={V0_FROZEN_CUTOFF}")
    print(f"fresh_sample_own_cutoff_not_used={LAST_FRESH_SAMPLE_CUTOFF}")
    return 0 if str(report.get("classification", "")).startswith(
        ("KEEP_", "KILL_")
    ) else 2


def _self_check() -> None:
    import tempfile

    good = {
        "version": holdout.MEMORY_VERSION,
        "classification": holdout.MEMORY_REPORT_CLASSIFICATION,
        "run_keys": [
            "participant-quality-tail-risk-replication-v1-20261007-01-M1",
            "participant-quality-tail-risk-replication-v1-20261007-01-M2",
            "participant-quality-tail-risk-replication-v1-20261007-01-M3",
            "participant-quality-tail-risk-replication-v1-20261007-01-M4",
        ],
        "coverage_audit": {
            "favorable_direction": "HIGH",
            # Deliberately NOT -86.0484432047999 -- a fresh sample is
            # expected to compute a different median. This must not raise.
            "outcome_blind_median_cutoff": -12.34,
        },
    }
    holdout.MEMORY_RUN_KEYS = tuple(good["run_keys"])
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(good, handle)
        good_path = Path(handle.name)
    try:
        result = _validate_memory_report_frozen_cutoff(good_path)
        assert result["classification"] == holdout.MEMORY_REPORT_CLASSIFICATION
        assert LAST_FRESH_SAMPLE_CUTOFF == -12.34, LAST_FRESH_SAMPLE_CUTOFF
        assert holdout.FROZEN_CUTOFF == V0_FROZEN_CUTOFF, "V0 cutoff must stay pinned"

        bad = dict(good)
        bad["run_keys"] = ["wrong-lineage-M1", "wrong-lineage-M2", "wrong-lineage-M3", "wrong-lineage-M4"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(bad, handle)
            bad_path = Path(handle.name)
        try:
            raised = False
            try:
                _validate_memory_report_frozen_cutoff(bad_path)
            except ValueError:
                raised = True
            assert raised, "mismatched memory lineage must still be rejected"
        finally:
            bad_path.unlink(missing_ok=True)
    finally:
        good_path.unlink(missing_ok=True)

    print("self-check OK: fresh-sample cutoff mismatch tolerated, lineage mismatch still rejected")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
