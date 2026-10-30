from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from benchmarks.deployer_prior_quality_v0.runtime_enrichment import FEATURE_ID
from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID as PARTICIPANT_QUALITY_FEATURE_ID,
    _episode_sources,
    _finite,
    _history_feature,
    _partial_spearman,
    _read_json,
    _spearman,
)


VERSION = "deployer_prior_quality_v0"
PASS = "PASS_DEPLOYER_PRIOR_QUALITY_V0"
FAIL = "FAIL_DEPLOYER_PRIOR_QUALITY_V0"
DEFAULT_PROTOCOL = Path("benchmarks") / "deployer_prior_quality_v0" / "protocol.frozen.json"
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
        raise ValueError("deployer prior-quality protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_PROSPECTIVE_DISCOVERY":
        raise ValueError("deployer prior-quality protocol is not preregistered discovery")
    if (protocol.get("feature_contract") or {}).get("primary_feature_id") != FEATURE_ID:
        raise ValueError("unexpected deployer primary feature")


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _association(
    rows: list[Mapping[str, Any]],
    *,
    feature_key: str,
    outcome_key: str,
) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        feature = _finite(row.get(feature_key))
        outcome = _finite(row.get(outcome_key))
        if feature is not None and outcome is not None:
            pairs.append((feature, outcome))

    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    rho = _spearman(xs, ys)

    without_best = None
    if len(pairs) >= 3:
        best_index = max(range(len(pairs)), key=lambda index: pairs[index][1])
        kept = [item for index, item in enumerate(pairs) if index != best_index]
        without_best = _spearman(
            [item[0] for item in kept],
            [item[1] for item in kept],
        )

    loo: list[float] = []
    if len(pairs) >= 4:
        for drop_index in range(len(pairs)):
            kept = [item for index, item in enumerate(pairs) if index != drop_index]
            value = _spearman(
                [item[0] for item in kept],
                [item[1] for item in kept],
            )
            if value is not None:
                loo.append(value)

    sign_consistency = None
    if rho is not None and rho != 0 and loo:
        nonzero = [value for value in loo if value != 0]
        if nonzero:
            sign_consistency = sum((value > 0) == (rho > 0) for value in nonzero) / len(nonzero)

    split = median(xs) if xs else None
    lower = [outcome for feature, outcome in pairs if split is not None and feature <= split]
    higher = [outcome for feature, outcome in pairs if split is not None and feature > split]

    return {
        "usable_pair_count": len(pairs),
        "spearman": rho,
        "spearman_without_best_trade": without_best,
        "leave_one_out_spearman_min": min(loo) if loo else None,
        "leave_one_out_spearman_median": median(loo) if loo else None,
        "leave_one_out_spearman_max": max(loo) if loo else None,
        "leave_one_out_sign_consistency_fraction": sign_consistency,
        "feature_median_supporting_split": split,
        "lower_or_equal_feature_half": {
            "n": len(lower),
            "mean_outcome_pct": _mean(lower),
            "median_outcome_pct": median(lower) if lower else None,
        },
        "higher_feature_half": {
            "n": len(higher),
            "mean_outcome_pct": _mean(higher),
            "median_outcome_pct": median(higher) if higher else None,
        },
    }


def _incremental_partial(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    complete: list[tuple[float, float, float, float, float]] = []
    for row in rows:
        feature = _finite(row.get(FEATURE_ID))
        outcome = _finite(row.get("current_route_closed_gross_return_pct"))
        participant = _finite(row.get(PARTICIPANT_QUALITY_FEATURE_ID))
        acceleration = _finite(row.get("mf_buy_event_rate_acceleration_per_s2"))
        signed_flow = _finite(row.get("signed_flow_over_event_reserve"))
        if None not in (feature, outcome, participant, acceleration, signed_flow):
            complete.append(
                (
                    float(feature),
                    float(outcome),
                    float(participant),
                    float(acceleration),
                    float(signed_flow),
                )
            )

    controls = [
        PARTICIPANT_QUALITY_FEATURE_ID,
        "mf_buy_event_rate_acceleration_per_s2",
        "signed_flow_over_event_reserve",
    ]
    if len(complete) < 5:
        return {
            "usable_pair_count": len(complete),
            "partial_spearman": None,
            "controls": controls,
        }

    xs = [item[0] for item in complete]
    ys = [item[1] for item in complete]
    columns = [
        [item[2] for item in complete],
        [item[3] for item in complete],
        [item[4] for item in complete],
    ]
    return {
        "usable_pair_count": len(complete),
        "partial_spearman": _partial_spearman(xs, ys, columns),
        "controls": controls,
        "spearman_feature_vs_participant_quality": _spearman(xs, columns[0]),
        "spearman_feature_vs_buy_acceleration": _spearman(xs, columns[1]),
        "spearman_feature_vs_signed_flow": _spearman(xs, columns[2]),
    }


def _load_deployer_snapshot_map(run_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    route_input = _read_json(Path(run_dir) / "route-input-v2.json")
    mapping: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    status_counts: dict[str, int] = {}

    for episode in route_input.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        episode_key = str(episode.get("episode_key") or "")
        snapshot = episode.get("feature_snapshot") or {}
        features = snapshot.get("features") or {}
        external = snapshot.get("external_evidence") or {}
        evidence = external.get("deployer_prior_quality_v0") or {}
        if not episode_key:
            continue

        status = str(evidence.get("status") or "MISSING")
        status_counts[status] = status_counts.get(status, 0) + 1
        feature = _finite(features.get(FEATURE_ID))
        cutoff_ns = int(snapshot.get("decision_cutoff_wall_ns") or 0)

        if status == "CAUSAL_AVAILABLE":
            total_created = evidence.get("total_created_snapshot")
            if isinstance(total_created, bool) or not isinstance(total_created, int) or total_created < 0:
                errors.append(f"invalid_total_created:{episode_key}")
            expected_feature = max(int(total_created or 0) - 1, 0)
            if feature is None or feature != float(expected_feature):
                errors.append(f"feature_derivation_mismatch:{episode_key}")
            for call_name in ("token_info", "created_tokens"):
                call = evidence.get(call_name) or {}
                response_after = call.get("response_after_wall_ns")
                if (
                    isinstance(response_after, bool)
                    or not isinstance(response_after, int)
                    or response_after <= 0
                    or response_after > cutoff_ns
                ):
                    errors.append(f"late_or_missing_{call_name}:{episode_key}")
                if call.get("private_key_used") is not False:
                    errors.append(f"private_key_guardrail:{episode_key}:{call_name}")
                if int(call.get("retry_count") or 0) != 0:
                    errors.append(f"retry_guardrail:{episode_key}:{call_name}")
        elif feature is not None:
            errors.append(f"noncausal_feature_backfilled:{episode_key}")

        mapping[episode_key] = {
            "status": status,
            FEATURE_ID: feature,
            "evidence": evidence,
        }

    if errors:
        raise ValueError("deployer evidence integrity failed: " + ";".join(errors[:12]))

    return mapping, {
        "feature_snapshot_frozen_before_provider_quotes": (
            route_input.get("feature_snapshot_frozen_before_provider_quotes") is True
        ),
        "episode_count": len(mapping),
        "status_counts": status_counts,
        "late_evidence_backfilled": False,
        "private_key_used": False,
        "retry_spam": False,
    }


def _validate_fresh_capture(run_dir: Path) -> dict[str, Any]:
    report_path = Path(run_dir) / "simulation-report-v4-sniper-v1.json"
    report = _read_json(report_path)
    base_v4 = report.get("base_v4_report") or {}
    capture = base_v4.get("capture") or {}
    requested = base_v4.get("requested_duration_seconds")
    if report.get("classification") != "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SNIPER_V1":
        raise ValueError("fresh deployer discovery wrapper did not PASS")
    if int(requested or 0) != 900:
        raise ValueError("fresh deployer discovery must request exactly 900 seconds")
    if capture.get("stop_reason") != "duration_elapsed":
        raise ValueError("fresh deployer discovery did not complete by duration")
    deployer = report.get("deployer_prior_quality_v0") or {}
    guardrails = deployer.get("guardrails") or {}
    status_counts = deployer.get("status_counts") or {}
    invalid_system_statuses = {
        "TASK_CANCELLED_AFTER_CAPTURE",
        "TASK_UNRESOLVED_AFTER_CAPTURE",
        "INTERNAL_ERROR",
    }
    invalid_counts = {
        status: int(status_counts.get(status) or 0)
        for status in invalid_system_statuses
        if int(status_counts.get(status) or 0) > 0
    }
    if invalid_counts:
        raise ValueError(
            "fresh deployer external-evidence acquisition is systems-invalid: "
            + ",".join(f"{key}={value}" for key, value in sorted(invalid_counts.items()))
        )
    if guardrails.get("gmgn_private_key_used") is not False:
        raise ValueError("deployer capture private-key guardrail failed")
    if guardrails.get("selector_changed") is not False:
        raise ValueError("deployer capture changed selector")
    return {
        "classification": report.get("classification"),
        "requested_duration_seconds": int(requested),
        "capture_stop_reason": capture.get("stop_reason"),
        "deployer_status_counts": status_counts,
        "invalid_system_status_counts": invalid_counts,
        "gmgn_private_key_used": False,
        "selector_changed": False,
    }


def run_discovery(
    *,
    fresh_run_dir: Path,
    history_run_dirs: list[Path],
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

    fresh = Path(fresh_run_dir).resolve()
    history = [Path(path).resolve() for path in history_run_dirs]
    if len(history) != 4:
        raise ValueError("exactly four frozen Participant Quality history runs are required")
    if fresh in history or len(set(map(str, history))) != 4:
        raise ValueError("fresh/history run identities must be distinct")

    live_attestation = _validate_fresh_capture(fresh)
    deployer_map, deployer_integrity = _load_deployer_snapshot_map(fresh)
    if deployer_integrity["feature_snapshot_frozen_before_provider_quotes"] is not True:
        raise ValueError("fresh feature snapshots were not frozen before provider quotes")

    historical_rows: list[dict[str, Any]] = []
    history_integrity: list[dict[str, Any]] = []
    for run_dir in history:
        rows, integrity = _episode_sources(run_dir=run_dir, contract_hash=contract_hash)
        historical_rows.extend(rows)
        history_integrity.append(integrity)

    fresh_rows, fresh_integrity = _episode_sources(
        run_dir=fresh,
        contract_hash=contract_hash,
    )
    universe = [*historical_rows, *fresh_rows]
    universe.sort(
        key=lambda row: (
            int(row.get("observed_t0_wall_ns") or 0),
            str(row.get("run_id") or ""),
            str(row.get("episode_key") or ""),
        )
    )

    analyzed: list[dict[str, Any]] = []
    for row in fresh_rows:
        if row.get("baseline_admitted") is not True or row.get("is_default_sol_quote") is not True:
            continue
        episode_key = str(row["episode_key"])
        deployer = deployer_map.get(episode_key) or {}
        participant = _history_feature(row, universe)
        analyzed.append(
            {
                "episode_key": episode_key,
                "token_mint": row["token_mint"],
                "observed_t0": row["observed_t0"],
                "route_status": row["route_status"],
                "deployer_evidence_status": deployer.get("status"),
                FEATURE_ID: deployer.get(FEATURE_ID),
                PARTICIPANT_QUALITY_FEATURE_ID: participant[PARTICIPANT_QUALITY_FEATURE_ID],
                "mf_buy_event_rate_acceleration_per_s2": row[
                    "mf_buy_event_rate_acceleration_per_s2"
                ],
                "signed_flow_over_event_reserve": row["signed_flow_over_event_reserve"],
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

    primary = _association(
        analyzed,
        feature_key=FEATURE_ID,
        outcome_key="current_route_closed_gross_return_pct",
    )
    secondary = _association(
        analyzed,
        feature_key=FEATURE_ID,
        outcome_key="current_route_closed_net_return_pct",
    )
    copyability = _association(
        analyzed,
        feature_key=FEATURE_ID,
        outcome_key="current_route_usable_fixed_return_pct",
    )
    incremental = _incremental_partial(analyzed)

    minimum_pairs = int(
        (protocol.get("directional_read") or {}).get("minimum_primary_route_closed_pairs") or 0
    )
    enough = int(primary.get("usable_pair_count") or 0) >= minimum_pairs
    decision = (
        "DISCOVERY_COMPLETE_NO_PROMOTION"
        if enough
        else "INSUFFICIENT_SAMPLE_NO_EXTENSION"
    )

    causal_available = [
        row for row in analyzed if row.get("deployer_evidence_status") == "CAUSAL_AVAILABLE"
    ]
    report = {
        "type": "deployer_prior_quality_report_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": FEATURE_ID,
        "population": {
            "fresh_baseline_default_sol_episode_count": len(analyzed),
            "deployer_causal_available_episode_count": len(causal_available),
            "deployer_causal_availability_pct": (
                100.0 * len(causal_available) / len(analyzed) if analyzed else None
            ),
            "primary_route_closed_feature_pairs": primary["usable_pair_count"],
            "minimum_primary_pairs_for_directional_read": minimum_pairs,
        },
        "primary_signal_quality": primary,
        "secondary_route_closed_net": secondary,
        "copyability_sensitive_reference": copyability,
        "incremental_vs_existing_evidence": incremental,
        "source_integrity": {
            "fresh_live_attestation": live_attestation,
            "deployer_snapshot_integrity": deployer_integrity,
            "fresh_route_integrity": fresh_integrity,
            "history_route_integrity": history_integrity,
            "strict_participant_history_reconstruction": True,
            "late_gmgn_evidence_backfilled": False,
            "gmgn_private_key_used": False,
            "threshold_search_performed": False,
            "selector_changed": False,
            "participant_quality_changed": False,
            "route_contract_changed": False,
        },
        "guardrails": {
            "promotion_from_this_sample_allowed": False,
            "automatic_entry_decision_created": False,
            "automatic_profitability_claim": False,
            "single_score_created": False,
            "manual_exit_instruction": False,
            "landed_fill_claim": False,
            "threshold_retuning_permitted": False,
        },
        "interpretation": (
            "This is prospective discovery of one deployer evidence family. "
            "A sufficient sample permits mechanism/robustness review only; it cannot promote "
            "a selector or validated signal from this same sample."
        ),
    }

    destination = output_path or (fresh / "deployer-prior-quality-v0.json")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(destination)
    report["artifact"] = str(destination.resolve())
    return report


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "decision": report.get("decision"),
        "artifact": report.get("artifact"),
        "population": report.get("population"),
        "primary_signal_quality": report.get("primary_signal_quality"),
        "incremental_vs_existing_evidence": report.get("incremental_vs_existing_evidence"),
        "copyability_sensitive_reference": report.get("copyability_sensitive_reference"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prospective discovery evaluator for Deployer Prior Quality V0"
    )
    parser.add_argument("--fresh-run-dir", type=Path, required=True)
    parser.add_argument("--history-run-dir", type=Path, action="append", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_discovery(
            fresh_run_dir=args.fresh_run_dir,
            history_run_dirs=args.history_run_dir,
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
