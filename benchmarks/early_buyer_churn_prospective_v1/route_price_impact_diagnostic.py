from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks.early_buyer_churn_prospective_v1.run import DEFAULT_CONTRACT
from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    FIX_VERSION,
    patched_price_impact_semantics,
)
from benchmarks.launch_burst_prospective_route_paper_v2.run import (
    run_route_paper_v2,
)


PASS = "PASS_ROUTE_PRICE_IMPACT_SEMANTICS_DIAGNOSTIC_V0"
FAIL = "FAIL_ROUTE_PRICE_IMPACT_SEMANTICS_DIAGNOSTIC_V0"
DEFAULT_OUTPUT_NAME = "route-result-v2-price-impact-fix-diagnostic.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_diagnostic(
    *,
    run_dir: Path,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    input_path = run_dir / "route-input-v2.json"
    original_result_path = run_dir / "route-result-v2.json"
    replay_path = run_dir / "route-result-v2-price-impact-fix-replay.json"
    diagnostic_path = output_path or (run_dir / DEFAULT_OUTPUT_NAME)

    for path in (input_path, original_result_path, contract_path):
        if not Path(path).is_file():
            raise ValueError(f"required source missing: {path}")

    input_hash_before = _sha256(input_path)
    original_result_hash_before = _sha256(original_result_path)

    original = _read_json(original_result_path)
    original_rows = {
        str(row.get("episode_key") or ""): row
        for row in original.get("decisions") or []
        if isinstance(row, dict) and str(row.get("episode_key") or "")
    }

    with patched_price_impact_semantics():
        corrected = run_route_paper_v2(
            contract_path=Path(contract_path),
            input_path=input_path,
            output_path=replay_path,
        )

    input_hash_after = _sha256(input_path)
    original_result_hash_after = _sha256(original_result_path)

    if input_hash_after != input_hash_before:
        raise RuntimeError("route-input-v2.json changed during diagnostic replay")
    if original_result_hash_after != original_result_hash_before:
        raise RuntimeError("original route-result-v2.json changed during diagnostic replay")

    corrected_rows = {
        str(row.get("episode_key") or ""): row
        for row in corrected.get("decisions") or []
        if isinstance(row, dict) and str(row.get("episode_key") or "")
    }
    if set(corrected_rows) != set(original_rows):
        raise RuntimeError("episode identity set changed during replay")

    transitions: Counter[tuple[str, str]] = Counter()
    changed: list[dict[str, Any]] = []
    for episode_key in sorted(original_rows):
        before = str(original_rows[episode_key].get("status") or "")
        after = str(corrected_rows[episode_key].get("status") or "")
        transitions[(before, after)] += 1
        if before != after:
            changed.append(
                {
                    "episode_key": episode_key,
                    "before": before,
                    "after": after,
                }
            )

    original_status_counts = dict(
        Counter(str(row.get("status") or "") for row in original_rows.values())
    )
    corrected_status_counts = dict(
        Counter(str(row.get("status") or "") for row in corrected_rows.values())
    )

    original_route_closed = int(
        original_status_counts.get("ROUTE_CLOSED", 0)
    )
    corrected_route_closed = int(
        corrected_status_counts.get("ROUTE_CLOSED", 0)
    )

    admitted_original = [
        row for row in original_rows.values() if row.get("admitted") is True
    ]
    admitted_corrected = [
        row for row in corrected_rows.values() if row.get("admitted") is True
    ]

    report = {
        "type": "route_price_impact_semantics_diagnostic_v0",
        "classification": PASS,
        "diagnostic_only": True,
        "scientific_verdict_changed": False,
        "early_buyer_churn_decision_changed": False,
        "fresh_sample_extended": False,
        "fresh_sample_repeated": False,
        "price_impact_fix_version": FIX_VERSION,
        "run_dir": str(run_dir),
        "source_integrity": {
            "route_input_sha256_before": input_hash_before,
            "route_input_sha256_after": input_hash_after,
            "route_input_unchanged": input_hash_before == input_hash_after,
            "original_route_result_sha256_before": original_result_hash_before,
            "original_route_result_sha256_after": original_result_hash_after,
            "original_route_result_unchanged": (
                original_result_hash_before == original_result_hash_after
            ),
            "episode_identity_set_unchanged": True,
        },
        "population": {
            "episode_count": len(original_rows),
            "admitted_original": len(admitted_original),
            "admitted_corrected": len(admitted_corrected),
        },
        "original": {
            "status_counts": original_status_counts,
            "route_closed_count": original_route_closed,
        },
        "corrected": {
            "status_counts": corrected_status_counts,
            "route_closed_count": corrected_route_closed,
        },
        "delta": {
            "route_closed_count": corrected_route_closed - original_route_closed,
            "changed_episode_count": len(changed),
            "status_transitions": [
                {
                    "before": before,
                    "after": after,
                    "count": count,
                }
                for (before, after), count in sorted(
                    transitions.items(),
                    key=lambda item: (-item[1], item[0][0], item[0][1]),
                )
            ],
        },
        "changed_rows": changed,
        "artifacts": {
            "original_route_result": str(original_result_path),
            "corrected_replay_result": str(replay_path),
            "diagnostic_report": str(Path(diagnostic_path)),
        },
        "interpretation": (
            "Offline implementation-conformance diagnostic only. It replays the already "
            "captured route-input with the versioned Swap V2 priceImpact semantics fix. "
            "It does not change the frozen Early Buyer Churn prospective verdict and must "
            "not be used as a rescue or replacement fresh sample."
        ),
    }
    _write_json(Path(diagnostic_path), report)
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "diagnostic_only": report.get("diagnostic_only"),
        "scientific_verdict_changed": report.get("scientific_verdict_changed"),
        "population": report.get("population"),
        "original": report.get("original"),
        "corrected": report.get("corrected"),
        "delta": report.get("delta"),
        "source_integrity": report.get("source_integrity"),
        "artifacts": report.get("artifacts"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay one frozen route-input under the versioned Swap V2 priceImpact semantics fix"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_diagnostic(
            run_dir=args.run_dir,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": FAIL,
                    "error": f"{type(exc).__name__}:{exc}",
                    "diagnostic_only": True,
                    "scientific_verdict_changed": False,
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
