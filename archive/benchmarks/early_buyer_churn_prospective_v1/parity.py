from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from benchmarks.early_balance_concentration_v0.run import _load_trade_evidence
from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    read_json,
    validate_protocol,
)
from benchmarks.early_buyer_churn_prospective_v1.runtime_enrichment import (
    EXTERNAL_EVIDENCE_KEY,
    OnlinePumpFeatureStateWithChurnV1,
)
from benchmarks.early_buyer_churn_v0.run import FEATURE_ID, _derive_feature


PASS = "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY"
FAIL = "FAIL_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY"


def _same_value(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-15)
    except (TypeError, ValueError):
        return False


def _route_complete_episodes(run_dir: Path) -> list[dict[str, Any]]:
    route_input = read_json(run_dir / "route-input-v2.json")
    episodes = route_input.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError(f"route-input episodes missing: {run_dir}")
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        snapshot = episode.get("feature_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
            continue
        token_mint = str(episode.get("token_mint") or "").strip()
        episode_key = str(episode.get("episode_key") or "").strip()
        if not token_mint or not episode_key:
            raise ValueError("complete route episode missing token_mint/episode_key")
        rows.append(episode)
    return rows


def _prospective_snapshot_map(run_dir: Path) -> dict[str, dict[str, Any]]:
    processed_root = run_dir / "processed-chunks"
    if not processed_root.is_dir():
        raise ValueError(f"processed-chunks directory missing: {processed_root}")
    state = OnlinePumpFeatureStateWithChurnV1()
    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        state.ingest_processed_chunk(chunk_dir)
    snapshots = state.ready_snapshots(coverage_through_wall_ns=(2**63 - 1))
    mapping: dict[str, dict[str, Any]] = {}
    for token_mint, snapshot in snapshots:
        if token_mint in mapping:
            raise ValueError(f"duplicate prospective churn snapshot for {token_mint}")
        mapping[token_mint] = snapshot
    return mapping


def _audit_run(run_dir: Path) -> dict[str, Any]:
    complete = _route_complete_episodes(run_dir)
    online = _prospective_snapshot_map(run_dir)
    anchors, trades, trade_integrity = _load_trade_evidence(run_dir)

    mismatches: list[str] = []
    compared = 0
    available = 0
    missing = 0

    for episode in complete:
        token_mint = str(episode["token_mint"])
        episode_key = str(episode["episode_key"])
        original_snapshot = episode["feature_snapshot"]
        anchor = anchors.get(token_mint)
        prospective_snapshot = online.get(token_mint)

        if not isinstance(anchor, dict):
            mismatches.append(f"missing_anchor:{episode_key}")
            continue
        if not isinstance(prospective_snapshot, dict):
            mismatches.append(f"missing_prospective_snapshot:{episode_key}")
            continue

        expected = _derive_feature(
            token_mint=token_mint,
            anchor_wall_ns=int(original_snapshot["observed_t0_wall_ns"]),
            cutoff_wall_ns=int(original_snapshot["decision_cutoff_wall_ns"]),
            chain_t0=int(anchor["chain_t0"]),
            trades=trades,
        )
        features = prospective_snapshot.get("features") or {}
        external = prospective_snapshot.get("external_evidence") or {}
        evidence = external.get(EXTERNAL_EVIDENCE_KEY) or {}
        actual_value = features.get(FEATURE_ID)
        actual_status = evidence.get("status")

        compared += 1
        if expected["status"] == "CAUSAL_AVAILABLE":
            available += 1
        else:
            missing += 1

        if actual_status != expected["status"]:
            mismatches.append(
                f"status:{episode_key}:expected={expected['status']}:actual={actual_status}"
            )
        if not _same_value(actual_value, expected[FEATURE_ID]):
            mismatches.append(
                f"value:{episode_key}:expected={expected[FEATURE_ID]}:actual={actual_value}"
            )
        if evidence.get("computed_before_provider_quotes") is not True:
            mismatches.append(f"provider_order_guard:{episode_key}")
        if evidence.get("external_provider_used") is not False:
            mismatches.append(f"external_provider_guard:{episode_key}")

    if compared == 0:
        raise ValueError(f"no complete route episodes available for parity: {run_dir}")

    return {
        "run_id": run_dir.name,
        "compared_complete_episode_count": compared,
        "causal_available_count": available,
        "missing_count": missing,
        "mismatch_count": len(mismatches),
        "mismatch_examples": mismatches[:20],
        "exact_status_parity": not any(item.startswith("status:") for item in mismatches),
        "exact_value_parity": not any(item.startswith("value:") for item in mismatches),
        "all_guardrails_valid": not any(
            item.startswith("provider_order_guard:")
            or item.startswith("external_provider_guard:")
            for item in mismatches
        ),
        "trade_evidence": trade_integrity,
    }



def validate_parity_report(
    *,
    parity_report_path: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    report = read_json(parity_report_path)
    if report.get("classification") != PASS:
        raise ValueError("prospective churn parity report did not PASS")
    if report.get("exact_parity") is not True:
        raise ValueError("prospective churn parity is not exact")
    if int(report.get("mismatch_count") or 0) != 0:
        raise ValueError("prospective churn parity has mismatches")
    if report.get("protocol_hash_sha256") != protocol.get("protocol_hash_sha256"):
        raise ValueError("prospective churn parity protocol hash mismatch")
    if report.get("feature_id") != FEATURE_ID:
        raise ValueError("prospective churn parity feature changed")

    expected_runs = list(
        (protocol.get("instrumentation") or {}).get("parity_runs") or []
    )
    actual_rows = [
        row for row in report.get("per_run") or [] if isinstance(row, dict)
    ]
    actual_runs = [str(row.get("run_id") or "") for row in actual_rows]
    if actual_runs != expected_runs:
        raise ValueError("prospective churn parity run set/order changed")
    if not actual_runs:
        raise ValueError("prospective churn parity contains no run attestations")
    if any(row.get("all_guardrails_valid") is not True for row in actual_rows):
        raise ValueError("prospective churn parity guardrail failed")
    if any(int(row.get("mismatch_count") or 0) != 0 for row in actual_rows):
        raise ValueError("prospective churn parity per-run mismatch detected")

    return {
        "classification": report.get("classification"),
        "exact_parity": True,
        "mismatch_count": 0,
        "compared_complete_episode_count": int(
            report.get("compared_complete_episode_count") or 0
        ),
        "protocol_hash_sha256": report.get("protocol_hash_sha256"),
        "run_ids": actual_runs,
        "artifact": str(Path(parity_report_path).resolve()),
    }


def run_parity(
    *,
    run_dirs: list[Path],
    protocol_path: Path = DEFAULT_PROTOCOL,
    output_path: Path | None = None,
) -> dict[str, Any]:
    protocol = read_json(protocol_path)
    validate_protocol(protocol)
    expected = list((protocol.get("instrumentation") or {}).get("parity_runs") or [])
    resolved = [Path(path).resolve() for path in run_dirs]
    if [path.name for path in resolved] != expected:
        raise ValueError("parity run set/order changed")

    per_run = [_audit_run(run_dir) for run_dir in resolved]
    mismatch_count = sum(int(row["mismatch_count"]) for row in per_run)
    compared = sum(int(row["compared_complete_episode_count"]) for row in per_run)
    classification = PASS if mismatch_count == 0 else FAIL

    report = {
        "type": "early_buyer_churn_prospective_v1_parity_report",
        "classification": classification,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": FEATURE_ID,
        "compared_complete_episode_count": compared,
        "mismatch_count": mismatch_count,
        "exact_parity": mismatch_count == 0,
        "per_run": per_run,
        "guardrails": {
            "exact_feature_definition_reused": True,
            "external_provider_used": False,
            "provider_quotes_used": False,
            "outcomes_used_to_modify_feature": False,
            "threshold_search_performed": False,
            "selector_changed": False,
        },
    }
    destination = Path(
        output_path
        or (
            resolved[-1]
            / "early-buyer-churn-prospective-v1-parity.json"
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(destination)
    report["artifact"] = str(destination.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline parity gate for Early Buyer Churn Prospective V1"
    )
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_parity(
            run_dirs=args.run_dir,
            protocol_path=args.protocol,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"classification": FAIL, "error": f"{type(exc).__name__}:{exc}"},
                indent=2,
            )
        )
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
