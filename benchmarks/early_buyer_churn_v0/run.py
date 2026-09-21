from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from benchmarks.early_balance_concentration_v0.run import _load_trade_evidence
from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID as PARTICIPANT_QUALITY_FEATURE_ID,
    _episode_sources,
    _finite,
    _history_feature,
    _partial_spearman,
    _read_json,
    _spearman,
)

VERSION = "early_buyer_churn_v0"
FEATURE_ID = "mf_early_buyer_roundtrip_sellback_fraction_t0_5s"
PASS = "PASS_EARLY_BUYER_CHURN_V0"
FAIL = "FAIL_EARLY_BUYER_CHURN_V0"
DEFAULT_PROTOCOL = Path("benchmarks") / "early_buyer_churn_v0" / "protocol.frozen.json"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)
EXPECTED_PROTOCOL_HASH = "5c9389bfd1954cddd0528916d933d6d4495906826d45689c424282a402996d3e"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {k: v for k, v in dict(protocol).items() if k != "protocol_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != EXPECTED_PROTOCOL_HASH or actual != EXPECTED_PROTOCOL_HASH:
        raise ValueError("early buyer churn protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_RETROSPECTIVE_TEMPORAL_HOLDOUT":
        raise ValueError("early buyer churn protocol status changed")
    feature = protocol.get("feature_contract") or {}
    if feature.get("primary_feature_id") != FEATURE_ID:
        raise ValueError("early buyer churn feature changed")
    if feature.get("expected_direction") != "negative":
        raise ValueError("early buyer churn direction changed")


def _derive_feature(
    *,
    token_mint: str,
    anchor_wall_ns: int,
    cutoff_wall_ns: int,
    chain_t0: int,
    trades: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    rows = [
        row
        for row in trades.get(token_mint, [])
        if anchor_wall_ns <= int(row["observed_wall_ns"]) <= cutoff_wall_ns
        and chain_t0 <= int(row["chain_time"]) <= chain_t0 + 5
    ]
    rows.sort(
        key=lambda row: (
            int(row["observed_wall_ns"]),
            int(row["chain_time"]),
            str(row["event_key"]),
        )
    )

    observed_inventory: dict[str, int] = {}
    buy_wallets: set[str] = set()
    flipper_wallets: set[str] = set()
    total_bought_raw = 0
    matched_sellback_raw = 0
    unmatched_sell_raw = 0
    buy_events = 0
    sell_events = 0

    for row in rows:
        wallet = str(row["wallet"])
        amount = int(row["token_amount_raw"])
        if row["side"] == "buy":
            observed_inventory[wallet] = observed_inventory.get(wallet, 0) + amount
            total_bought_raw += amount
            buy_wallets.add(wallet)
            buy_events += 1
            continue

        sell_events += 1
        available = max(0, observed_inventory.get(wallet, 0))
        matched = min(available, amount)
        if matched > 0:
            observed_inventory[wallet] = available - matched
            matched_sellback_raw += matched
            flipper_wallets.add(wallet)
        unmatched_sell_raw += amount - matched

    if total_bought_raw <= 0:
        return {
            FEATURE_ID: None,
            "status": "MISSING_NO_OBSERVED_BUY",
            "event_count": len(rows),
            "buy_event_count": buy_events,
            "sell_event_count": sell_events,
            "unique_buy_wallet_count": 0,
            "flipper_wallet_count": 0,
            "flipper_wallet_share": None,
            "total_bought_raw": 0,
            "matched_sellback_raw": 0,
            "unmatched_sell_raw": unmatched_sell_raw,
        }

    value = float(matched_sellback_raw) / float(total_bought_raw)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError("derived early buyer churn fraction outside 0..1")

    return {
        FEATURE_ID: value,
        "status": "CAUSAL_AVAILABLE",
        "event_count": len(rows),
        "buy_event_count": buy_events,
        "sell_event_count": sell_events,
        "unique_buy_wallet_count": len(buy_wallets),
        "flipper_wallet_count": len(flipper_wallets),
        "flipper_wallet_share": (
            float(len(flipper_wallets)) / float(len(buy_wallets))
            if buy_wallets else None
        ),
        "total_bought_raw": total_bought_raw,
        "matched_sellback_raw": matched_sellback_raw,
        "unmatched_sell_raw": unmatched_sell_raw,
    }


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _association(rows: list[Mapping[str, Any]], *, outcome_key: str) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        feature = _finite(row.get(FEATURE_ID))
        outcome = _finite(row.get(outcome_key))
        if feature is not None and outcome is not None:
            pairs.append((feature, outcome))

    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    rho = _spearman(xs, ys)

    without_best = None
    if len(pairs) >= 3:
        best_index = max(range(len(pairs)), key=lambda index: pairs[index][1])
        kept = [item for index, item in enumerate(pairs) if index != best_index]
        without_best = _spearman([x for x, _ in kept], [y for _, y in kept])

    loo: list[float] = []
    if len(pairs) >= 4:
        for drop_index in range(len(pairs)):
            kept = [item for index, item in enumerate(pairs) if index != drop_index]
            value = _spearman([x for x, _ in kept], [y for _, y in kept])
            if value is not None:
                loo.append(value)

    sign_consistency = None
    if rho is not None and rho != 0 and loo:
        nonzero = [value for value in loo if value != 0]
        if nonzero:
            sign_consistency = sum((value > 0) == (rho > 0) for value in nonzero) / len(nonzero)

    split = median(xs) if xs else None
    lower = [y for x, y in pairs if split is not None and x <= split]
    higher = [y for x, y in pairs if split is not None and x > split]

    return {
        "usable_pair_count": len(pairs),
        "spearman": rho,
        "spearman_without_best_trade": without_best,
        "leave_one_out_spearman_min": min(loo) if loo else None,
        "leave_one_out_spearman_median": median(loo) if loo else None,
        "leave_one_out_spearman_max": max(loo) if loo else None,
        "leave_one_out_sign_consistency_fraction": sign_consistency,
        "expected_direction": "negative",
        "direction_matches_preregistered": (rho < 0) if rho is not None else None,
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


def _incremental(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
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
        return {"usable_pair_count": len(complete), "partial_spearman": None, "controls": controls}

    xs = [row[0] for row in complete]
    ys = [row[1] for row in complete]
    columns = [
        [row[2] for row in complete],
        [row[3] for row in complete],
        [row[4] for row in complete],
    ]
    return {
        "usable_pair_count": len(complete),
        "partial_spearman": _partial_spearman(xs, ys, columns),
        "controls": controls,
        "spearman_feature_vs_participant_quality": _spearman(xs, columns[0]),
        "spearman_feature_vs_buy_acceleration": _spearman(xs, columns[1]),
        "spearman_feature_vs_signed_flow": _spearman(xs, columns[2]),
    }


def _analyze_group(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "population": {
            "episode_count": len(rows),
            "feature_causal_available_episode_count": sum(
                1 for row in rows if row.get("feature_status") == "CAUSAL_AVAILABLE"
            ),
        },
        "primary_signal_quality": _association(
            rows, outcome_key="current_route_closed_gross_return_pct"
        ),
        "secondary_route_closed_net": _association(
            rows, outcome_key="current_route_closed_net_return_pct"
        ),
        "copyability_sensitive_reference": _association(
            rows, outcome_key="current_route_usable_fixed_return_pct"
        ),
        "incremental_vs_existing_evidence": _incremental(rows),
    }


def _prepare_rows(
    *,
    run_dirs: list[Path],
    contract_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows: list[dict[str, Any]] = []
    integrity: list[dict[str, Any]] = []
    trade_by_run: dict[str, tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]] = {}

    for run_dir in run_dirs:
        rows, route_integrity = _episode_sources(run_dir=run_dir, contract_hash=contract_hash)
        anchors, trades, trade_integrity = _load_trade_evidence(run_dir)
        raw_rows.extend(rows)
        integrity.append({**route_integrity, "trade_evidence": trade_integrity})
        trade_by_run[run_dir.name] = (anchors, trades)

    universe = sorted(
        raw_rows,
        key=lambda row: (
            int(row.get("observed_t0_wall_ns") or 0),
            str(row.get("run_id") or ""),
            str(row.get("episode_key") or ""),
        ),
    )

    analyzed: list[dict[str, Any]] = []
    parity_errors: list[str] = []
    for row in raw_rows:
        if row.get("baseline_admitted") is not True or row.get("is_default_sol_quote") is not True:
            continue
        run_id = str(row.get("run_id") or "")
        anchors, trades = trade_by_run[run_id]
        token_mint = str(row.get("token_mint") or "")
        anchor = anchors.get(token_mint)
        if not anchor:
            parity_errors.append(f"missing_create_anchor:{row.get('episode_key')}")
            continue
        anchor_wall_ns = int(row.get("observed_t0_wall_ns") or 0)
        if int(anchor.get("observed_wall_ns") or 0) != anchor_wall_ns:
            parity_errors.append(f"create_anchor_clock_mismatch:{row.get('episode_key')}")
            continue

        feature = _derive_feature(
            token_mint=token_mint,
            anchor_wall_ns=anchor_wall_ns,
            cutoff_wall_ns=anchor_wall_ns + 5_000_000_000,
            chain_t0=int(anchor["chain_t0"]),
            trades=trades,
        )
        participant = _history_feature(row, universe)
        analyzed.append(
            {
                "run_id": run_id,
                "episode_key": row["episode_key"],
                "token_mint": token_mint,
                "route_status": row["route_status"],
                FEATURE_ID: feature[FEATURE_ID],
                "feature_status": feature["status"],
                "unique_buy_wallet_count": feature["unique_buy_wallet_count"],
                "flipper_wallet_count": feature["flipper_wallet_count"],
                "flipper_wallet_share": feature["flipper_wallet_share"],
                "matched_sellback_raw": feature["matched_sellback_raw"],
                "total_bought_raw": feature["total_bought_raw"],
                PARTICIPANT_QUALITY_FEATURE_ID: participant[PARTICIPANT_QUALITY_FEATURE_ID],
                "mf_buy_event_rate_acceleration_per_s2": row["mf_buy_event_rate_acceleration_per_s2"],
                "signed_flow_over_event_reserve": row["signed_flow_over_event_reserve"],
                "current_route_closed_gross_return_pct": row["current_route_closed_gross_return_pct"],
                "current_route_closed_net_return_pct": row["current_route_closed_net_return_pct"],
                "current_route_usable_fixed_return_pct": row["current_route_usable_fixed_return_pct"],
            }
        )

    if parity_errors:
        raise ValueError("early buyer churn causal reconstruction failed: " + ";".join(parity_errors[:12]))

    return analyzed, integrity


def _decision(
    *,
    discovery: Mapping[str, Any],
    holdout: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[str, dict[str, bool]]:
    rule = protocol.get("decision_rule") or {}
    d_primary = discovery.get("primary_signal_quality") or {}
    d_inc = discovery.get("incremental_vs_existing_evidence") or {}
    h_primary = holdout.get("primary_signal_quality") or {}
    h_inc = holdout.get("incremental_vs_existing_evidence") or {}

    enough_discovery = int(d_primary.get("usable_pair_count") or 0) >= int(
        rule.get("minimum_discovery_primary_pairs") or 0
    )
    enough_holdout = int(h_primary.get("usable_pair_count") or 0) >= int(
        rule.get("minimum_holdout_primary_pairs") or 0
    )
    checks = {
        "enough_discovery_pairs": enough_discovery,
        "enough_holdout_pairs": enough_holdout,
        "discovery_negative": (
            _finite(d_primary.get("spearman")) is not None
            and float(d_primary["spearman"]) < 0
            and _finite(d_primary.get("spearman_without_best_trade")) is not None
            and float(d_primary["spearman_without_best_trade"]) < 0
        ),
        "discovery_loo_robust": (
            _finite(d_primary.get("leave_one_out_sign_consistency_fraction")) is not None
            and float(d_primary["leave_one_out_sign_consistency_fraction"]) >= 0.8
        ),
        "discovery_incremental_negative": (
            _finite(d_inc.get("partial_spearman")) is not None
            and float(d_inc["partial_spearman"]) < 0
        ),
        "holdout_negative": (
            _finite(h_primary.get("spearman")) is not None
            and float(h_primary["spearman"]) < 0
        ),
        "holdout_incremental_negative": (
            _finite(h_inc.get("partial_spearman")) is not None
            and float(h_inc["partial_spearman"]) < 0
        ),
    }
    if not enough_discovery or not enough_holdout:
        return str(rule["insufficient_label"]), checks
    if all(checks.values()):
        return str(rule["success_label"]), checks
    return str(rule["failure_label"]), checks


def run_discovery(
    *,
    discovery_run_dirs: list[Path],
    holdout_run_dir: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol)

    discovery_dirs = [Path(path).resolve() for path in discovery_run_dirs]
    holdout_dir = Path(holdout_run_dir).resolve()
    expected_discovery = list(protocol.get("discovery_runs") or [])
    if [path.name for path in discovery_dirs] != expected_discovery:
        raise ValueError("discovery run set/order changed")
    if holdout_dir.name != str(protocol.get("temporal_holdout_run") or ""):
        raise ValueError("temporal holdout run changed")
    if holdout_dir in discovery_dirs:
        raise ValueError("holdout cannot overlap discovery runs")

    contract = _read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")

    all_dirs = [*discovery_dirs, holdout_dir]
    analyzed, integrity = _prepare_rows(run_dirs=all_dirs, contract_hash=contract_hash)
    discovery_rows = [row for row in analyzed if row["run_id"] in set(expected_discovery)]
    holdout_rows = [row for row in analyzed if row["run_id"] == holdout_dir.name]

    discovery = _analyze_group(discovery_rows)
    holdout = _analyze_group(holdout_rows)
    decision, decision_checks = _decision(
        discovery=discovery,
        holdout=holdout,
        protocol=protocol,
    )

    feature_rows = [
        row for row in analyzed if _finite(row.get(FEATURE_ID)) is not None
    ]
    diagnostics = {
        "usable_count": len(feature_rows),
        "zero_churn_fraction": (
            sum(float(row[FEATURE_ID]) == 0.0 for row in feature_rows) / len(feature_rows)
            if feature_rows else None
        ),
        "median_feature": (
            median([float(row[FEATURE_ID]) for row in feature_rows]) if feature_rows else None
        ),
        "median_flipper_wallet_share": (
            median([
                float(row["flipper_wallet_share"])
                for row in feature_rows
                if _finite(row.get("flipper_wallet_share")) is not None
            ])
            if feature_rows else None
        ),
    }

    report = {
        "type": "early_buyer_churn_report_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "decision_checks": decision_checks,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": FEATURE_ID,
        "discovery": discovery,
        "temporal_holdout": holdout,
        "structure_diagnostics": diagnostics,
        "source_integrity": {
            "discovery_run_ids": expected_discovery,
            "temporal_holdout_run_id": holdout_dir.name,
            "run_integrity": integrity,
            "causal_window_reconstructed_from_raw_decoded_pump_trades": True,
            "external_provider_used": False,
            "new_live_acquisition_used": False,
            "new_outcome_collection_used": False,
            "threshold_search_performed": False,
            "selector_changed": False,
            "participant_quality_changed": False,
            "route_contract_changed": False,
        },
        "guardrails": {
            "retrospective_only": True,
            "temporal_holdout_is_not_prospective_confirmation": True,
            "promotion_from_this_sample_allowed": False,
            "automatic_entry_decision_created": False,
            "automatic_profitability_claim": False,
            "single_score_created": False,
            "threshold_retuning_permitted": False,
        },
        "interpretation": (
            "The discovery/holdout split was frozen before evaluating this feature. The holdout is temporal "
            "within already-captured research and is not a prospective confirmation. Success may justify "
            "mechanism review and later fresh prospective confirmation only."
        ),
    }

    destination = Path(output_path or (holdout_dir / "early-buyer-churn-v0.json"))
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
        "decision_checks": report.get("decision_checks"),
        "artifact": report.get("artifact"),
        "discovery": report.get("discovery"),
        "temporal_holdout": report.get("temporal_holdout"),
        "structure_diagnostics": report.get("structure_diagnostics"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrospective temporal-holdout evaluator for Early Buyer Churn V0"
    )
    parser.add_argument("--discovery-run-dir", type=Path, action="append", required=True)
    parser.add_argument("--holdout-run-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_discovery(
            discovery_run_dirs=args.discovery_run_dir,
            holdout_run_dir=args.holdout_run_dir,
            protocol_path=args.protocol,
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
