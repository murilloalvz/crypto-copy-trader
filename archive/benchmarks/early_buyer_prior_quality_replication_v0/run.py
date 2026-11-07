from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID,
    _association,
    _episode_sources,
    _finite,
    _history_feature,
    _incremental_partial,
    _read_json,
)

PASS = "PASS_EARLY_BUYER_PRIOR_QUALITY_REPLICATION_V0"
FAIL = "FAIL_EARLY_BUYER_PRIOR_QUALITY_REPLICATION_V0"
DEFAULT_PROTOCOL = (
    Path("benchmarks")
    / "early_buyer_prior_quality_replication_v0"
    / "protocol.frozen.json"
)
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {key: value for key, value in dict(protocol).items() if key != "protocol_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("early-buyer prior-quality replication protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_FRESH_CONFIRMATION":
        raise ValueError("replication protocol is not preregistered")
    if (protocol.get("hypothesis") or {}).get("feature_id") != FEATURE_ID:
        raise ValueError("unexpected replication feature")


def _route_input_sha256(run_dir: Path) -> str:
    path = Path(run_dir) / "route-input-v2.json"
    if not path.is_file():
        raise ValueError(f"route input missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_fresh_live_report(
    *,
    report: Mapping[str, Any],
    expected_duration_seconds: int,
) -> dict[str, Any]:
    requested = report.get("requested_duration_seconds")
    capture = report.get("capture") or {}
    if int(requested or 0) != int(expected_duration_seconds):
        raise ValueError(
            f"fresh requested duration mismatch: {requested} != {expected_duration_seconds}"
        )
    if str(capture.get("stop_reason") or "") != "duration_elapsed":
        raise ValueError(
            f"fresh capture did not complete requested duration: {capture.get('stop_reason')}"
        )
    if report.get("economic_outcomes_opened") is not True:
        raise ValueError("fresh report did not open route-paper economic outcomes")
    if str(report.get("mode") or "") != "route_paper_economic":
        raise ValueError("fresh report is not route-paper economic mode")
    if not str(report.get("classification") or "").startswith("PASS_"):
        raise ValueError("fresh live report is not PASS")
    return {
        "requested_duration_seconds": int(requested),
        "capture_stop_reason": str(capture.get("stop_reason") or ""),
        "capture_elapsed_seconds": _finite(capture.get("elapsed_seconds")),
        "mode": str(report.get("mode") or ""),
        "classification": str(report.get("classification") or ""),
    }


def _fresh_rows(
    *,
    history_rows: list[dict[str, Any]],
    fresh_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    universe = [*history_rows, *fresh_rows]
    universe.sort(
        key=lambda row: (
            int(row.get("observed_t0_wall_ns") or 0),
            str(row.get("run_id") or ""),
            str(row.get("episode_key") or ""),
        )
    )

    output: list[dict[str, Any]] = []
    for row in fresh_rows:
        if row.get("baseline_admitted") is not True:
            continue
        if row.get("is_default_sol_quote") is not True:
            continue
        history = _history_feature(row, universe)
        output.append(
            {
                "run_id": row["run_id"],
                "episode_key": row["episode_key"],
                "token_mint": row["token_mint"],
                "observed_t0": row["observed_t0"],
                "route_status": row["route_status"],
                "buy_identity_complete": row["buy_identity_complete"],
                "buy_wallet_count": row["buy_wallet_count"],
                FEATURE_ID: history[FEATURE_ID],
                "history_coverage_pct": history["history_coverage_pct"],
                "wallets_with_history": history["wallets_with_history"],
                "prior_association_count": history["prior_association_count"],
                "prior_unique_episode_count": history["prior_unique_episode_count"],
                "prior_positive_association_share_pct": history[
                    "prior_positive_association_share_pct"
                ],
                "mf_buy_event_rate_acceleration_per_s2": row[
                    "mf_buy_event_rate_acceleration_per_s2"
                ],
                "signed_flow_over_event_reserve": row[
                    "signed_flow_over_event_reserve"
                ],
                "current_route_closed_gross_return_pct": row[
                    "current_route_closed_gross_return_pct"
                ],
                "current_route_closed_net_return_pct": row[
                    "current_route_closed_net_return_pct"
                ],
                "current_route_usable_fixed_return_pct": row[
                    "current_route_usable_fixed_return_pct"
                ],
            }
        )
    return output


def _decision(
    *,
    protocol: Mapping[str, Any],
    primary: Mapping[str, Any],
    incremental: Mapping[str, Any],
) -> tuple[str, list[str], dict[str, bool | None]]:
    minimum = int(
        (protocol.get("fresh_capture_contract") or {}).get(
            "minimum_primary_route_closed_feature_pairs"
        )
        or 0
    )
    rho = _finite(primary.get("spearman"))
    without_best = _finite(primary.get("spearman_without_best_trade"))
    loo = _finite(primary.get("leave_one_out_sign_consistency_fraction"))
    partial = _finite(incremental.get("partial_spearman"))
    lower = primary.get("lower_or_equal_feature_half") or {}
    higher = primary.get("higher_feature_half") or {}
    lower_median = _finite(lower.get("median_outcome_pct"))
    higher_median = _finite(higher.get("median_outcome_pct"))

    checks: dict[str, bool | None] = {
        "minimum_sample_met": int(primary.get("usable_pair_count") or 0) >= minimum,
        "spearman_positive": rho is not None and rho > 0,
        "spearman_nonpositive": rho is not None and rho <= 0,
        "spearman_without_best_positive": without_best is not None and without_best > 0,
        "spearman_without_best_nonpositive": without_best is not None and without_best <= 0,
        "leave_one_out_sign_consistency_gte_0_90": loo is not None and loo >= 0.90,
        "partial_spearman_positive_if_estimable": partial is None or partial > 0,
        "partial_spearman_nonpositive_if_estimable": partial is None or partial <= 0,
        "higher_half_median_gross_gt_lower_half": (
            higher_median is not None
            and lower_median is not None
            and higher_median > lower_median
        ),
        "higher_half_median_gross_lte_lower_half": (
            higher_median is not None
            and lower_median is not None
            and higher_median <= lower_median
        ),
    }

    rules = protocol.get("decision_rule") or {}
    if all(checks.get(name) is True for name in rules.get("keep_if_all") or []):
        return "KEEP", ["all_preregistered_fresh_confirmation_keep_conditions_passed"], checks
    if all(checks.get(name) is True for name in rules.get("kill_if_all") or []):
        return "KILL", ["all_preregistered_fresh_confirmation_kill_conditions_passed"], checks

    reasons: list[str] = []
    if not checks["minimum_sample_met"]:
        reasons.append("fresh_primary_pair_count_below_preregistered_minimum")
    if partial is None:
        reasons.append("partial_spearman_not_estimable_but_not_auto_failure")
    if not reasons:
        reasons.append("fresh_confirmation_evidence_mixed_no_retuning_allowed")
    return "ITERATE", reasons, checks


def run_replication(
    *,
    history_run_dirs: list[Path],
    fresh_run_dir: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol)
    contract = _read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")

    expected_history_ids = list(
        (protocol.get("mature_history_contract") or {}).get("frozen_history_run_ids")
        or []
    )
    resolved_history = [Path(path).resolve() for path in history_run_dirs]
    supplied_ids = [path.name for path in resolved_history]
    if supplied_ids != expected_history_ids:
        raise ValueError(
            "history run ids must exactly match frozen mature-history order: "
            + ",".join(expected_history_ids)
        )

    fresh_run_dir = Path(fresh_run_dir).resolve()
    if fresh_run_dir.name in set(expected_history_ids):
        raise ValueError("fresh run id matches a frozen history run")

    fresh_report_path = fresh_run_dir / "report.json"
    if not fresh_report_path.is_file():
        raise ValueError(f"fresh live report missing: {fresh_report_path}")
    expected_duration = int(
        (protocol.get("fresh_capture_contract") or {}).get("duration_seconds") or 0
    )
    fresh_live_attestation = _validate_fresh_live_report(
        report=_read_json(fresh_report_path),
        expected_duration_seconds=expected_duration,
    )

    history_shas = [_route_input_sha256(path) for path in resolved_history]
    if len(set(history_shas)) != len(history_shas):
        raise ValueError("frozen history route-input identities are not unique")
    fresh_sha = _route_input_sha256(fresh_run_dir)
    if fresh_sha in set(history_shas):
        raise ValueError("fresh route-input identity matches a frozen history run")

    history_rows: list[dict[str, Any]] = []
    integrity: list[dict[str, Any]] = []
    for run_dir in resolved_history:
        rows, meta = _episode_sources(run_dir=run_dir, contract_hash=contract_hash)
        history_rows.extend(rows)
        integrity.append(meta)

    fresh_rows, fresh_integrity = _episode_sources(
        run_dir=fresh_run_dir,
        contract_hash=contract_hash,
    )
    integrity.append(fresh_integrity)

    history_max_t0 = max(
        (int(row.get("observed_t0") or 0) for row in history_rows),
        default=0,
    )
    fresh_min_t0 = min(
        (int(row.get("observed_t0") or 0) for row in fresh_rows),
        default=0,
    )
    if history_max_t0 <= 0 or fresh_min_t0 <= history_max_t0:
        raise ValueError(
            f"fresh capture is not strictly after frozen history captures: "
            f"history_max_t0={history_max_t0} fresh_min_t0={fresh_min_t0}"
        )

    rows = _fresh_rows(history_rows=history_rows, fresh_rows=fresh_rows)
    primary = _association(rows, "current_route_closed_gross_return_pct")
    secondary = _association(rows, "current_route_closed_net_return_pct")
    copyability = _association(rows, "current_route_usable_fixed_return_pct")
    incremental = _incremental_partial(rows)
    decision, reasons, checks = _decision(
        protocol=protocol,
        primary=primary,
        incremental=incremental,
    )

    feature_available = [row for row in rows if _finite(row.get(FEATURE_ID)) is not None]
    report = {
        "type": "early_buyer_prior_quality_replication_report_v0",
        "classification": PASS,
        "decision": decision,
        "decision_reasons": reasons,
        "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
        "inference_role": "FRESH_SIGNAL_QUALITY_CONFIRMATION_NOT_AUTONOMOUS_ALPHA",
        "feature_id": FEATURE_ID,
        "population": {
            "fresh_baseline_default_sol_episode_count": len(rows),
            "fresh_feature_available_episode_count": len(feature_available),
            "fresh_feature_availability_pct": (
                100.0 * len(feature_available) / len(rows) if rows else None
            ),
            "fresh_primary_route_closed_feature_pairs": primary.get("usable_pair_count"),
            "minimum_primary_pairs": (
                protocol.get("fresh_capture_contract") or {}
            ).get("minimum_primary_route_closed_feature_pairs"),
        },
        "signal_quality": {
            "primary_route_closed_gross_plus_60s": primary,
            "secondary_route_closed_net_plus_60s": secondary,
            "incremental_vs_existing_flow": incremental,
        },
        "copyability_sensitive_reference": {
            "route_usable_fixed_plus_60s_including_unroutable_exit_minus_100": copyability,
            "role": "REFERENCE_ONLY_NOT_PRIMARY_SIGNAL_ENDPOINT",
        },
        "decision_rule_checks": checks,
        "source_integrity": {
            "route_contract_hash_sha256": contract_hash,
            "frozen_history_run_ids": expected_history_ids,
            "supplied_history_run_ids_match_exactly": supplied_ids == expected_history_ids,
            "history_route_input_sha256s": history_shas,
            "fresh_route_input_sha256": fresh_sha,
            "fresh_identity_differs_from_all_history": fresh_sha not in set(history_shas),
            "fresh_run_strictly_after_history": fresh_min_t0 > history_max_t0,
            "history_max_observed_t0": history_max_t0,
            "fresh_min_observed_t0": fresh_min_t0,
            "all_exact_reconstruction_parity": all(
                item.get("exact_reconstruction_parity") is True
                for item in integrity
            ),
            "all_feature_snapshots_frozen_before_provider_quotes": all(
                item.get("feature_snapshot_frozen_before_provider_quotes") is True
                for item in integrity
            ),
            "numeric_history_support_threshold_used": False,
            "strict_pre_t0_history": True,
            "same_second_history_excluded": True,
            "same_token_prior_history_excluded": True,
            "wallet_realized_pnl_claim": False,
            "fresh_live_attestation": fresh_live_attestation,
        },
        "guardrails": protocol.get("guardrails"),
        "rows": rows,
        "interpretation": (
            "This is one preregistered fresh confirmation of early-buyer prior-opportunity quality "
            "with mature pre-T0 memory supplied by exactly four frozen historical captures. KEEP "
            "retains Participant Quality as a Signal Engine dimension; it does not claim landed fills, "
            "wallet realized PnL, an automatic entry rule, or autonomous trading alpha."
        ),
    }

    destination = output_path or (
        fresh_run_dir / "early-buyer-prior-quality-replication-v0.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["artifact"] = str(destination.resolve())
    return report


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "decision": report.get("decision"),
        "decision_reasons": report.get("decision_reasons"),
        "population": report.get("population"),
        "primary_signal_quality": (
            (report.get("signal_quality") or {}).get(
                "primary_route_closed_gross_plus_60s"
            )
        ),
        "incremental_vs_existing_flow": (
            (report.get("signal_quality") or {}).get(
                "incremental_vs_existing_flow"
            )
        ),
        "copyability_sensitive_reference": report.get(
            "copyability_sensitive_reference"
        ),
        "decision_rule_checks": report.get("decision_rule_checks"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fresh confirmation of early-buyer prior opportunity quality"
    )
    parser.add_argument("--history-run-dir", type=Path, action="append", required=True)
    parser.add_argument("--fresh-run-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_replication(
            history_run_dirs=args.history_run_dir,
            fresh_run_dir=args.fresh_run_dir,
            protocol_path=args.protocol,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": FAIL,
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
