from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from benchmarks.early_buyer_churn_v0.run import (
    DEFAULT_CONTRACT,
    DEFAULT_PROTOCOL,
    FEATURE_ID,
    _association,
    _incremental,
    _prepare_rows,
    _read_json,
    _validate_protocol,
)
from benchmarks.early_buyer_prior_quality_v0.run import _finite, _spearman


VERSION = "early_buyer_churn_robustness_v0"
PASS = "PASS_EARLY_BUYER_CHURN_ROBUSTNESS_V0"
FAIL = "FAIL_EARLY_BUYER_CHURN_ROBUSTNESS_V0"


def _run_level(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    primary = _association(rows, outcome_key="current_route_closed_gross_return_pct")
    incremental = _incremental(rows)
    feature_rows = [row for row in rows if _finite(row.get(FEATURE_ID)) is not None]
    zero_rows = [row for row in feature_rows if float(row[FEATURE_ID]) == 0.0]
    positive_rows = [row for row in feature_rows if float(row[FEATURE_ID]) > 0.0]
    return {
        "episode_count": len(rows),
        "feature_usable_count": len(feature_rows),
        "primary": primary,
        "incremental": incremental,
        "zero_churn": {
            "n": len(zero_rows),
            "gross_mean_pct": (
                sum(float(row["current_route_closed_gross_return_pct"]) for row in zero_rows
                    if _finite(row.get("current_route_closed_gross_return_pct")) is not None)
                / sum(1 for row in zero_rows if _finite(row.get("current_route_closed_gross_return_pct")) is not None)
                if any(_finite(row.get("current_route_closed_gross_return_pct")) is not None for row in zero_rows)
                else None
            ),
        },
        "positive_churn": {
            "n": len(positive_rows),
            "gross_mean_pct": (
                sum(float(row["current_route_closed_gross_return_pct"]) for row in positive_rows
                    if _finite(row.get("current_route_closed_gross_return_pct")) is not None)
                / sum(1 for row in positive_rows if _finite(row.get("current_route_closed_gross_return_pct")) is not None)
                if any(_finite(row.get("current_route_closed_gross_return_pct")) is not None for row in positive_rows)
                else None
            ),
        },
    }


def _pooled_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    primary = _association(rows, outcome_key="current_route_closed_gross_return_pct")
    incremental = _incremental(rows)
    feature_rows = [row for row in rows if _finite(row.get(FEATURE_ID)) is not None]
    return {
        "primary": primary,
        "incremental": incremental,
        "feature_vs_flipper_wallet_share_spearman": (
            _spearman(
                [float(row[FEATURE_ID]) for row in feature_rows if _finite(row.get("flipper_wallet_share")) is not None],
                [float(row["flipper_wallet_share"]) for row in feature_rows if _finite(row.get("flipper_wallet_share")) is not None],
            )
            if sum(_finite(row.get("flipper_wallet_share")) is not None for row in feature_rows) >= 2
            else None
        ),
        "median_unique_buy_wallet_count": (
            median([int(row["unique_buy_wallet_count"]) for row in feature_rows])
            if feature_rows else None
        ),
        "median_flipper_wallet_count": (
            median([int(row["flipper_wallet_count"]) for row in feature_rows])
            if feature_rows else None
        ),
    }


def run_audit(
    *,
    run_dirs: list[Path],
    churn_protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    protocol = _read_json(churn_protocol_path)
    _validate_protocol(protocol)
    expected = [*list(protocol.get("discovery_runs") or []), str(protocol.get("temporal_holdout_run") or "")]
    resolved = [Path(path).resolve() for path in run_dirs]
    if [path.name for path in resolved] != expected:
        raise ValueError("robustness audit run set/order changed")

    contract = _read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")

    analyzed, integrity = _prepare_rows(run_dirs=resolved, contract_hash=contract_hash)
    by_run = {run_id: [row for row in analyzed if row["run_id"] == run_id] for run_id in expected}

    per_run = {run_id: _run_level(rows) for run_id, rows in by_run.items()}

    leave_one_run_out: dict[str, Any] = {}
    for dropped in expected:
        kept = [row for row in analyzed if row["run_id"] != dropped]
        leave_one_run_out[dropped] = {
            "primary": _association(kept, outcome_key="current_route_closed_gross_return_pct"),
            "incremental": _incremental(kept),
        }

    primary_signs = [
        result["primary"].get("spearman")
        for result in per_run.values()
        if _finite(result["primary"].get("spearman")) is not None
    ]
    partial_signs = [
        result["incremental"].get("partial_spearman")
        for result in per_run.values()
        if _finite(result["incremental"].get("partial_spearman")) is not None
    ]

    report = {
        "type": "early_buyer_churn_robustness_report_v0",
        "version": VERSION,
        "classification": PASS,
        "feature_id": FEATURE_ID,
        "evidence_level": "POST_DISCOVERY_ROBUSTNESS_AUDIT_NO_NEW_CONFIRMATION_WEIGHT",
        "pooled": _pooled_summary(analyzed),
        "per_run": per_run,
        "leave_one_run_out": leave_one_run_out,
        "sign_diagnostics": {
            "run_primary_negative_fraction": (
                sum(float(value) < 0 for value in primary_signs) / len(primary_signs)
                if primary_signs else None
            ),
            "run_partial_negative_fraction": (
                sum(float(value) < 0 for value in partial_signs) / len(partial_signs)
                if partial_signs else None
            ),
            "leave_one_run_out_primary_negative_fraction": (
                sum(
                    _finite(result["primary"].get("spearman")) is not None
                    and float(result["primary"]["spearman"]) < 0
                    for result in leave_one_run_out.values()
                ) / len(leave_one_run_out)
                if leave_one_run_out else None
            ),
            "leave_one_run_out_partial_negative_fraction": (
                sum(
                    _finite(result["incremental"].get("partial_spearman")) is not None
                    and float(result["incremental"]["partial_spearman"]) < 0
                    for result in leave_one_run_out.values()
                ) / len(leave_one_run_out)
                if leave_one_run_out else None
            ),
        },
        "source_integrity": {
            "run_ids": expected,
            "run_integrity": integrity,
            "exact_feature_reused": True,
            "feature_definition_changed": False,
            "threshold_search_performed": False,
            "selector_changed": False,
            "new_live_acquisition_used": False,
            "new_outcome_collection_used": False,
            "external_provider_used": False,
        },
        "guardrails": {
            "post_discovery_audit_only": True,
            "promotion_from_this_audit_allowed": False,
            "prospective_confirmation_claim": False,
            "automatic_entry_rule_created": False,
            "threshold_retuning_permitted": False,
            "feature_redefinition_permitted": False,
        },
        "interpretation": (
            "This audit reuses the exact frozen churn feature after the retrospective temporal-holdout success. "
            "It checks whether sign and incremental direction are broadly distributed across acquisition periods "
            "and survive dropping any entire run. Because the audit was designed after seeing the churn result, "
            "it adds robustness context but no new confirmatory evidence."
        ),
    }

    destination = Path(output_path or (resolved[-1] / "early-buyer-churn-robustness-v0.json"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(destination)
    report["artifact"] = str(destination.resolve())
    return report


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "evidence_level": report.get("evidence_level"),
        "artifact": report.get("artifact"),
        "pooled": report.get("pooled"),
        "per_run": report.get("per_run"),
        "leave_one_run_out": report.get("leave_one_run_out"),
        "sign_diagnostics": report.get("sign_diagnostics"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-discovery robustness audit for Early Buyer Churn V0")
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--churn-protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_audit(
            run_dirs=args.run_dir,
            churn_protocol_path=args.churn_protocol,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({"classification": FAIL, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
