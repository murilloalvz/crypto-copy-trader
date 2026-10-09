from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
from typing import Any, Iterable

from benchmarks.helius_standard_wss_shadow_v0.reconcile_finalized_blocks import (
    PROGRAMS,
    _jsonl,
    reconcile_finalized_blocks,
    reconcile_signature_sets,
    wss_signature_sets,
)

VERSION = "helius_standard_wss_boundary_safe_finalized_recall_v0"
LABEL_TO_PROGRAM = {"pump_logs": "pump", "pumpswap_logs": "pumpswap"}


def _truth_rows_in_window(
    rows: Iterable[dict[str, Any]], *, min_slot: int, max_slot: int
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("slot"), int)
        and not isinstance(row.get("slot"), bool)
        and min_slot <= int(row["slot"]) <= max_slot
    ]


def _slot_signature_sets(
    shadow_rows: Iterable[dict[str, Any]], *, min_slot: int, max_slot: int
) -> dict[int, dict[str, set[str]]]:
    result: dict[int, dict[str, set[str]]] = defaultdict(
        lambda: {name: set() for name in PROGRAMS}
    )
    for row in shadow_rows:
        if row.get("type") != "logs_notification":
            continue
        program = LABEL_TO_PROGRAM.get(str(row.get("subscription_label", "")))
        slot = row.get("slot")
        signature = row.get("signature")
        if (
            program is None
            or not isinstance(slot, int)
            or isinstance(slot, bool)
            or not min_slot <= slot <= max_slot
            or not isinstance(signature, str)
            or not signature
        ):
            continue
        result[slot][program].add(signature)
    return result


def _truth_slot_signature_sets(
    truth_rows: Iterable[dict[str, Any]], *, min_slot: int, max_slot: int
) -> dict[int, dict[str, set[str]]]:
    result: dict[int, dict[str, set[str]]] = defaultdict(
        lambda: {name: set() for name in PROGRAMS}
    )
    for row in truth_rows:
        slot = row.get("slot")
        signature = row.get("signature")
        mentioned = row.get("programs_mentioned")
        if (
            not isinstance(slot, int)
            or isinstance(slot, bool)
            or not min_slot <= slot <= max_slot
            or not isinstance(signature, str)
            or not signature
            or not isinstance(mentioned, list)
        ):
            continue
        for program in PROGRAMS:
            if program in mentioned:
                result[slot][program].add(signature)
    return result


def analyze_boundary_safe_recall(
    *,
    shadow_rows: list[dict[str, Any]],
    truth_rows: list[dict[str, Any]],
    full_report: dict[str, Any],
) -> dict[str, Any]:
    complete_truth = full_report.get("complete_truth_enumeration") is True
    min_slot = full_report.get("min_slot")
    max_slot = full_report.get("max_slot")
    if (
        not complete_truth
        or not isinstance(min_slot, int)
        or isinstance(min_slot, bool)
        or not isinstance(max_slot, int)
        or isinstance(max_slot, bool)
        or max_slot - min_slot < 2
    ):
        return {
            "type": "helius_standard_wss_boundary_safe_finalized_recall",
            "version": VERSION,
            "classification": "INCOMPLETE_BOUNDARY_SAFE_REFERENCE",
            "valid_boundary_safe_audit": False,
            "complete_truth_enumeration": complete_truth,
            "min_slot": min_slot,
            "max_slot": max_slot,
            "notes": [
                "Boundary-safe recall is withheld unless the underlying finalized reference is complete and at least one interior slot exists."
            ],
        }

    interior_min_slot = min_slot + 1
    interior_max_slot = max_slot - 1
    interior_truth = _truth_rows_in_window(
        truth_rows, min_slot=interior_min_slot, max_slot=interior_max_slot
    )
    interior_wss = wss_signature_sets(
        shadow_rows, min_slot=interior_min_slot, max_slot=interior_max_slot
    )
    per_program = reconcile_signature_sets(
        wss_sets=interior_wss,
        truth_rows=interior_truth,
        complete_truth_enumeration=True,
    )

    full_per_program = full_report.get("per_program")
    boundary_effect: dict[str, Any] = {}
    for program in PROGRAMS:
        full_item = (
            full_per_program.get(program, {})
            if isinstance(full_per_program, dict)
            else {}
        )
        full_missed = full_item.get("finalized_truth_missed_by_wss")
        interior_missed = per_program[program]["finalized_truth_missed_by_wss"]
        boundary_effect[program] = {
            "full_window_missed": full_missed,
            "interior_window_missed": interior_missed,
            "misses_removed_by_boundary_trim": (
                full_missed - interior_missed
                if isinstance(full_missed, int) and isinstance(interior_missed, int)
                else None
            ),
        }

    wss_by_slot = _slot_signature_sets(
        shadow_rows, min_slot=interior_min_slot, max_slot=interior_max_slot
    )
    truth_by_slot = _truth_slot_signature_sets(
        interior_truth, min_slot=interior_min_slot, max_slot=interior_max_slot
    )
    slots_with_misses: list[dict[str, Any]] = []
    for slot in range(interior_min_slot, interior_max_slot + 1):
        program_rows: dict[str, Any] = {}
        any_missed = False
        for program in PROGRAMS:
            truth = truth_by_slot.get(slot, {}).get(program, set())
            wss = wss_by_slot.get(slot, {}).get(program, set())
            missed = truth - wss
            if missed:
                any_missed = True
            program_rows[program] = {
                "truth": len(truth),
                "seen": len(truth & wss),
                "missed": len(missed),
            }
        if any_missed:
            slots_with_misses.append({"slot": slot, "per_program": program_rows})

    any_interior_missed = any(
        int(per_program[program]["finalized_truth_missed_by_wss"]) > 0
        for program in PROGRAMS
    )
    return {
        "type": "helius_standard_wss_boundary_safe_finalized_recall",
        "version": VERSION,
        "classification": (
            "MEASURED_BOUNDARY_SAFE_WSS_FINALIZED_SIGNATURE_GAPS"
            if any_interior_missed
            else "PASS_BOUNDARY_SAFE_FINALIZED_SIGNATURE_RECALL_REFERENCE"
        ),
        "valid_boundary_safe_audit": True,
        "complete_truth_enumeration": True,
        "full_min_slot": min_slot,
        "full_max_slot": max_slot,
        "excluded_boundary_slots": [min_slot, max_slot],
        "interior_min_slot": interior_min_slot,
        "interior_max_slot": interior_max_slot,
        "interior_slot_span_inclusive": interior_max_slot - interior_min_slot + 1,
        "per_program": per_program,
        "boundary_effect": boundary_effect,
        "interior_slots_with_misses": len(slots_with_misses),
        "slots_with_misses": slots_with_misses,
        "chain_complete_coverage_claimed_for_wss": False,
        "economic_edge_evaluated": False,
        "notes": [
            "The first and last observed log slots are excluded because collection can begin or end mid-slot.",
            "This audit isolates obvious slot-boundary truncation but still does not prove chain-complete WSS coverage.",
            "Program-account mention recall is not target instruction/event semantic recall.",
            "Any remaining interior misses require signature-level diagnosis before replacing the provider.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boundary-safe finalized signature recall audit for Standard WSS"
    )
    parser.add_argument("--shadow", type=Path, required=True)
    parser.add_argument("--candidates-out", type=Path, required=True)
    parser.add_argument("--rps", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    api_key = os.environ.get("HELIUS_API_KEY")
    if not api_key:
        raise SystemExit("HELIUS_API_KEY is required")

    full_report = reconcile_finalized_blocks(
        shadow_path=args.shadow,
        candidates_out=args.candidates_out,
        api_key=api_key,
        rps=args.rps,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
    )
    shadow_rows = _jsonl(args.shadow)
    truth_rows = _jsonl(args.candidates_out)
    report = analyze_boundary_safe_recall(
        shadow_rows=shadow_rows,
        truth_rows=truth_rows,
        full_report=full_report,
    )
    report["underlying_full_classification"] = full_report.get("classification")
    report["underlying_request_errors"] = full_report.get("request_errors")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("valid_boundary_safe_audit") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
