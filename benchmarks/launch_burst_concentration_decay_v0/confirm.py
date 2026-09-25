from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_concentration_decay_v0.run import (
    DEFAULT_CONTRACT,
    DEFAULT_POLICY,
    run_evaluation,
)


VERSION = "launch_burst_concentration_decay_confirmation_v1"
KEEP = "KEEP_CONCENTRATION_DECAY_SELECTION_EDGE_CANDIDATE"
KILL = "KILL_CONCENTRATION_DECAY_SELECTION_EDGE_CANDIDATE"
INCONCLUSIVE = "INCONCLUSIVE_CONCENTRATION_DECAY_CONFIRMATION_SUPPORT"

DISCOVERY_RUN_ID = (
    "launch_burst_prospective_route_live_v4-"
    "1790305374-3b6738bb33"
)
DISCOVERY_CAPTURE_STARTED_UNIX_SECONDS = 1790305374

RUN_ID_RE = re.compile(
    r"^launch_burst_prospective_route_live_v4-(\d+)-[0-9a-f]+$"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp.replace(path)


def _fresh_run_guard(run_dir: Path) -> dict[str, Any]:
    name = run_dir.resolve().name
    if name == DISCOVERY_RUN_ID:
        raise ValueError("discovery run cannot be reused as fresh confirmation")
    match = RUN_ID_RE.fullmatch(name)
    if match is None:
        raise ValueError("unexpected fresh capture run directory identity")
    started = int(match.group(1))
    if started <= DISCOVERY_CAPTURE_STARTED_UNIX_SECONDS:
        raise ValueError(
            "fresh confirmation capture must start after the discovery capture"
        )

    route_input = _read_json(run_dir / "route-input-v2.json")
    capture_started_wall_ns = int(
        route_input.get("capture_started_wall_ns") or 0
    )
    if capture_started_wall_ns <= DISCOVERY_CAPTURE_STARTED_UNIX_SECONDS * 1_000_000_000:
        raise ValueError(
            "route-input capture clock does not postdate discovery"
        )

    return {
        "run_id": name,
        "run_id_started_unix_seconds": started,
        "route_input_capture_started_wall_ns": capture_started_wall_ns,
        "postdates_discovery_capture": True,
    }


def classify_confirmation(evaluation: dict[str, Any]) -> tuple[str, str]:
    checks = evaluation.get("decision_rule_checks") or {}
    support_ok = checks.get("minimum_sample_and_frequency_met") is True
    if not support_ok:
        return (
            INCONCLUSIVE,
            "fresh_support_below_preregistered_sample_or_frequency_gate",
        )

    decision = str(evaluation.get("decision") or "")
    if decision == "KEEP":
        return (
            KEEP,
            "all_frozen_keep_conditions_passed_on_fresh_confirmation",
        )

    return (
        KILL,
        (
            "fresh_support_sufficient_but_all_frozen_absolute_keep_"
            "conditions_did_not_pass"
        ),
    )


def run_confirmation(
    *,
    run_dir: Path,
    policy_path: Path = DEFAULT_POLICY,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    freshness = _fresh_run_guard(run_dir)

    evaluation = run_evaluation(
        run_dir=run_dir,
        policy_path=policy_path,
        contract_path=contract_path,
        output_path=run_dir / "concentration-decay-evaluation-v0.json",
    )
    if evaluation.get("classification") != (
        "PASS_LAUNCH_BURST_CONCENTRATION_DECAY_V0_EVALUATION"
    ):
        raise ValueError("underlying concentration evaluation did not PASS")
    if evaluation.get("threshold_search_performed") is not False:
        raise ValueError("threshold search must remain disabled")
    if evaluation.get("selector_changed") is not False:
        raise ValueError("selector mutation is forbidden")

    classification, reason = classify_confirmation(evaluation)

    report = {
        "type": "launch_burst_concentration_decay_confirmation_report_v1",
        "version": VERSION,
        "classification": classification,
        "classification_reason": reason,
        "hypothesis_id": evaluation.get("hypothesis_id"),
        "policy_hash_sha256": evaluation.get("policy_hash_sha256"),
        "freshness": freshness,
        "feature": evaluation.get("feature"),
        "population": evaluation.get("population"),
        "routeability": evaluation.get("routeability"),
        "economics": evaluation.get("economics"),
        "decision_rule_checks": evaluation.get("decision_rule_checks"),
        "underlying_discovery_evaluator_decision": evaluation.get("decision"),
        "threshold_search_performed": False,
        "selector_changed": False,
        "automatic_edge_claim": False,
        "live_money_authorized": False,
        "independent_replication_required_if_keep": True,
        "second_iterate_authorized": False,
        "interpretation": (
            "This is the single preregistered fresh confirmation of the "
            "unchanged concentration-decay <= 0 pp rule. KEEP promotes only "
            "to a selection-edge candidate requiring independent replication. "
            "KILL closes the exact selector. INCONCLUSIVE means support was "
            "insufficient and does not authorize an automatic extra capture."
        ),
    }

    destination = output_path or (
        run_dir / "concentration-decay-confirmation-v1.json"
    )
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    economics = report.get("economics") or {}
    return {
        "classification": report.get("classification"),
        "classification_reason": report.get("classification_reason"),
        "hypothesis_id": report.get("hypothesis_id"),
        "policy_hash_sha256": report.get("policy_hash_sha256"),
        "freshness": report.get("freshness"),
        "population": report.get("population"),
        "baseline": economics.get(
            "feature_available_baseline_comparator"
        ),
        "candidate": economics.get("candidate"),
        "decision_rule_checks": report.get("decision_rule_checks"),
        "underlying_discovery_evaluator_decision": report.get(
            "underlying_discovery_evaluator_decision"
        ),
        "independent_replication_required_if_keep": report.get(
            "independent_replication_required_if_keep"
        ),
        "second_iterate_authorized": report.get(
            "second_iterate_authorized"
        ),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Single fresh confirmation of the frozen "
            "H_ORGANICITY_CONCENTRATION_DECAY_V0 rule."
        )
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_confirmation(
            run_dir=args.run_dir,
            policy_path=args.policy,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": (
                        "FAIL_CONCENTRATION_DECAY_CONFIRMATION_V1"
                    ),
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0 if report.get("classification") in {
        KEEP,
        KILL,
        INCONCLUSIVE,
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
