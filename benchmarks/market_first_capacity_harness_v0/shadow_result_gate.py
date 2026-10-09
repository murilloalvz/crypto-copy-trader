from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


GATE_VERSION = "market_first_shadow_signal_gate_v1"
PASS_CLASSIFICATION = "PASS_MARKET_FIRST_SHADOW_SIGNAL_GATE_V1"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_SHADOW_SIGNAL_GATE_V1"

_SIGNAL_PIPELINE_FIELDS = (
    "canonical_events_paired",
    "decoded_events",
    "decode_failures_seen_in_processing",
    "out_of_window_events",
    "lifecycle_events_ingested",
    "market_trade_adapted_events",
    "market_trade_statuses",
    "matched_unit_statuses",
    "kernel_trade_events_ingested",
    "kernel_retained_trade_rows",
    "kernel_tracked_assets",
    "kernel_triggers_emitted",
    "unresolved_pool_event_count",
    "unresolved_unique_pool_count",
)


def _signal_errors(pipeline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("semantic_errors", "persistence_errors", "chunk_errors"):
        values = pipeline.get(key) or []
        errors.extend(f"{key}:{item}" for item in values)
    return errors


def classify_shadow_result_v1(result: dict[str, Any]) -> dict[str, Any]:
    baseline_pipeline = dict(((result.get("baseline") or {}).get("pipeline") or {}))
    shadow_pipeline = dict(((result.get("shadow") or {}).get("pipeline") or {}))
    trigger_parity = dict(result.get("trigger_parity") or {})
    signal_path = dict(result.get("signal_path") or {})

    field_mismatches = {
        field: {
            "baseline": baseline_pipeline.get(field),
            "shadow": shadow_pipeline.get(field),
        }
        for field in _SIGNAL_PIPELINE_FIELDS
        if baseline_pipeline.get(field) != shadow_pipeline.get(field)
    }
    baseline_signal_errors = _signal_errors(baseline_pipeline)
    shadow_signal_errors = _signal_errors(shadow_pipeline)
    baseline_research_errors = list(baseline_pipeline.get("research_errors") or [])
    shadow_research_errors = list(shadow_pipeline.get("research_errors") or [])

    gates = {
        "trigger_ledger_exact_match": bool(trigger_parity.get("exact_match")),
        "unresolved_pool_set_exact_match": bool(result.get("unresolved_pool_set_exact_match")),
        "signal_pipeline_counters_exact_match": not field_mismatches,
        "baseline_signal_errors_empty": not baseline_signal_errors,
        "shadow_signal_errors_empty": not shadow_signal_errors,
        "single_chunk_reference_le_5s": bool(signal_path.get("single_chunk_reference_le_5s")),
    }
    passed = all(gates.values())

    return {
        "type": "market_first_shadow_signal_gate",
        "version": GATE_VERSION,
        "classification": PASS_CLASSIFICATION if passed else FAIL_CLASSIFICATION,
        "gates": gates,
        "trigger_parity": trigger_parity,
        "field_mismatches": field_mismatches,
        "baseline_signal_errors": baseline_signal_errors,
        "shadow_signal_errors": shadow_signal_errors,
        "non_gating_post_signal_research_errors": {
            "baseline": baseline_research_errors,
            "shadow": shadow_research_errors,
        },
        "signal_path": signal_path,
        "source_classification": result.get("classification"),
        "research_errors_are_non_gating_reason": (
            "The shadow experiment measures causal Signal Plane equivalence. Research Plane "
            "work happens after trigger emission and cannot change the already-recorded trigger "
            "ledger. Research errors remain visible but do not invalidate signal parity."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reclassify a Market-First shadow result using Signal-Plane-only gates."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    result = classify_shadow_result_v1(source)
    text = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
