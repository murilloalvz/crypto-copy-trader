from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID as PARTICIPANT_QUALITY_FEATURE_ID,
    _episode_sources,
    _finite,
    _history_feature,
    _partial_spearman,
    _read_json,
    _spearman,
)
from benchmarks.launch_burst_prospective_route_paper_v2.live import _paired_rows


VERSION = "early_balance_concentration_v0"
FEATURE_ID = "mf_early_net_acquired_token_hhi_t0_5s"
PASS = "PASS_EARLY_BALANCE_CONCENTRATION_V0"
FAIL = "FAIL_EARLY_BALANCE_CONCENTRATION_V0"
DEFAULT_PROTOCOL = Path("benchmarks") / "early_balance_concentration_v0" / "protocol.frozen.json"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)
EXPECTED_PROTOCOL_HASH = "fb31f536d816d47a2974271d44d8584022dc5acf57e7ed6bad6b7bf9487ac2ec"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {key: value for key, value in dict(protocol).items() if key != "protocol_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != EXPECTED_PROTOCOL_HASH or actual != EXPECTED_PROTOCOL_HASH:
        raise ValueError("early balance concentration protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_RETROSPECTIVE_DISCOVERY":
        raise ValueError("early balance concentration protocol status changed")
    feature = protocol.get("feature_contract") or {}
    if feature.get("primary_feature_id") != FEATURE_ID:
        raise ValueError("early balance concentration feature changed")
    if feature.get("expected_direction") != "negative":
        raise ValueError("early balance concentration direction changed")


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a non-negative integer")
    if out < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return out


def _load_trade_evidence(run_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    processed_root = Path(run_dir) / "processed-chunks"
    if not processed_root.is_dir():
        raise ValueError(f"processed-chunks directory missing: {processed_root}")

    anchors: dict[str, dict[str, Any]] = {}
    trades: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    processed_chunk_count = 0
    decoded_trade_count = 0

    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        carbon = chunk_dir / "carbon-canonical.jsonl"
        manifest = chunk_dir / "target-manifest.jsonl"
        if not carbon.is_file():
            continue
        processed_chunk_count += 1
        ordered, errors = _paired_rows(carbon, manifest)
        if errors:
            raise ValueError(
                f"trade evidence pairing failed for {chunk_dir}: " + ";".join(errors[:5])
            )
        for row, manifest_row in ordered:
            event_key = str(row.get("event_key") or "")
            if not event_key or event_key in seen:
                continue
            seen.add(event_key)
            if row.get("status") != "decoded":
                continue
            event_type = str(row.get("event_type") or "")
            wall_ns = _nonnegative_int(
                manifest_row.get("first_received_wall_ns"),
                "first_received_wall_ns",
            )
            if event_type == "pump_create":
                mint = str(row.get("mint") or "").strip()
                chain_t0 = _nonnegative_int(row.get("timestamp"), "pump_create.timestamp")
                if mint and mint not in anchors:
                    anchors[mint] = {
                        "observed_wall_ns": wall_ns,
                        "chain_t0": chain_t0,
                        "event_key": event_key,
                    }
                continue
            if event_type != "pump_trade":
                continue

            mint = str(row.get("mint") or "").strip()
            wallet = str(row.get("wallet") or "").strip()
            side = str(row.get("side") or "").strip()
            chain_time = _nonnegative_int(row.get("timestamp"), "pump_trade.timestamp")
            token_amount_raw = _nonnegative_int(
                row.get("token_amount_raw"),
                "pump_trade.token_amount_raw",
            )
            if not mint or not wallet or side not in {"buy", "sell"} or token_amount_raw <= 0:
                raise ValueError(f"invalid decoded pump trade semantics: {event_key}")
            trades.setdefault(mint, []).append(
                {
                    "event_key": event_key,
                    "observed_wall_ns": wall_ns,
                    "chain_time": chain_time,
                    "wallet": wallet,
                    "side": side,
                    "token_amount_raw": token_amount_raw,
                }
            )
            decoded_trade_count += 1

    for rows in trades.values():
        rows.sort(
            key=lambda row: (
                int(row["observed_wall_ns"]),
                int(row["chain_time"]),
                str(row["event_key"]),
            )
        )

    return anchors, trades, {
        "processed_chunk_count": processed_chunk_count,
        "decoded_trade_count": decoded_trade_count,
        "unique_event_key_count": len(seen),
    }


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
    balances: dict[str, int] = {}
    buy_count = 0
    sell_count = 0
    for row in rows:
        wallet = str(row["wallet"])
        amount = int(row["token_amount_raw"])
        if row["side"] == "buy":
            balances[wallet] = balances.get(wallet, 0) + amount
            buy_count += 1
        else:
            balances[wallet] = balances.get(wallet, 0) - amount
            sell_count += 1

    positive = {wallet: amount for wallet, amount in balances.items() if amount > 0}
    total_positive = sum(positive.values())
    if total_positive <= 0:
        return {
            FEATURE_ID: None,
            "status": "MISSING_NO_POSITIVE_OBSERVED_NET_BALANCE",
            "event_count": len(rows),
            "buy_event_count": buy_count,
            "sell_event_count": sell_count,
            "positive_wallet_count": 0,
            "observed_positive_balance_total_raw": 0,
            "largest_positive_wallet_share": None,
        }

    shares = [float(amount) / float(total_positive) for amount in positive.values()]
    hhi = sum(share * share for share in shares)
    if not math.isfinite(hhi) or hhi <= 0.0 or hhi > 1.0000000001:
        raise ValueError("derived early balance HHI outside valid range")
    return {
        FEATURE_ID: hhi,
        "status": "CAUSAL_AVAILABLE",
        "event_count": len(rows),
        "buy_event_count": buy_count,
        "sell_event_count": sell_count,
        "positive_wallet_count": len(positive),
        "observed_positive_balance_total_raw": total_positive,
        "largest_positive_wallet_share": max(shares),
    }


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _association(
    rows: list[Mapping[str, Any]],
    *,
    outcome_key: str,
) -> dict[str, Any]:
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


def run_discovery(
    *,
    run_dirs: list[Path],
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol)
    expected_run_ids = list(protocol.get("discovery_runs") or [])
    resolved_dirs = [Path(path).resolve() for path in run_dirs]
    actual_run_ids = [path.name for path in resolved_dirs]
    if actual_run_ids != expected_run_ids:
        raise ValueError(
            "discovery run set/order changed; expected "
            + ",".join(expected_run_ids)
            + " got "
            + ",".join(actual_run_ids)
        )

    contract = _read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")

    all_rows: list[dict[str, Any]] = []
    run_integrity: list[dict[str, Any]] = []
    trade_evidence_by_run: dict[str, tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]] = {}

    for run_dir in resolved_dirs:
        rows, route_integrity = _episode_sources(run_dir=run_dir, contract_hash=contract_hash)
        anchors, trades, trade_integrity = _load_trade_evidence(run_dir)
        all_rows.extend(rows)
        run_integrity.append({**route_integrity, "trade_evidence": trade_integrity})
        trade_evidence_by_run[run_dir.name] = (anchors, trades)

    universe = sorted(
        all_rows,
        key=lambda row: (
            int(row.get("observed_t0_wall_ns") or 0),
            str(row.get("run_id") or ""),
            str(row.get("episode_key") or ""),
        ),
    )

    analyzed: list[dict[str, Any]] = []
    parity_errors: list[str] = []
    for row in all_rows:
        if row.get("baseline_admitted") is not True or row.get("is_default_sol_quote") is not True:
            continue
        run_id = str(row.get("run_id") or "")
        anchors, trades = trade_evidence_by_run[run_id]
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
                "positive_wallet_count": feature["positive_wallet_count"],
                "largest_positive_wallet_share": feature["largest_positive_wallet_share"],
                "feature_event_count": feature["event_count"],
                PARTICIPANT_QUALITY_FEATURE_ID: participant[PARTICIPANT_QUALITY_FEATURE_ID],
                "mf_buy_event_rate_acceleration_per_s2": row["mf_buy_event_rate_acceleration_per_s2"],
                "signed_flow_over_event_reserve": row["signed_flow_over_event_reserve"],
                "current_route_closed_gross_return_pct": row["current_route_closed_gross_return_pct"],
                "current_route_closed_net_return_pct": row["current_route_closed_net_return_pct"],
                "current_route_usable_fixed_return_pct": row["current_route_usable_fixed_return_pct"],
            }
        )

    if parity_errors:
        raise ValueError(
            "early balance causal reconstruction parity failed: " + ";".join(parity_errors[:12])
        )

    primary = _association(analyzed, outcome_key="current_route_closed_gross_return_pct")
    secondary = _association(analyzed, outcome_key="current_route_closed_net_return_pct")
    copyability = _association(analyzed, outcome_key="current_route_usable_fixed_return_pct")
    incremental = _incremental(analyzed)

    structure_rows = [
        row for row in analyzed
        if _finite(row.get(FEATURE_ID)) is not None
        and isinstance(row.get("positive_wallet_count"), int)
    ]
    structure = {
        "usable_count": len(structure_rows),
        "spearman_feature_vs_positive_wallet_count": _spearman(
            [float(row[FEATURE_ID]) for row in structure_rows],
            [float(row["positive_wallet_count"]) for row in structure_rows],
        ) if len(structure_rows) >= 2 else None,
        "median_positive_wallet_count": (
            median([int(row["positive_wallet_count"]) for row in structure_rows])
            if structure_rows else None
        ),
        "median_largest_positive_wallet_share": (
            median([
                float(row["largest_positive_wallet_share"])
                for row in structure_rows
                if _finite(row.get("largest_positive_wallet_share")) is not None
            ])
            if structure_rows else None
        ),
    }

    minimum_pairs = int(
        (protocol.get("directional_read") or {}).get("minimum_primary_route_closed_pairs") or 0
    )
    enough = int(primary.get("usable_pair_count") or 0) >= minimum_pairs
    decision = "DISCOVERY_COMPLETE_NO_PROMOTION" if enough else "INSUFFICIENT_SAMPLE_NO_EXTENSION"

    report = {
        "type": "early_balance_concentration_report_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": FEATURE_ID,
        "population": {
            "discovery_run_count": len(resolved_dirs),
            "baseline_default_sol_episode_count": len(analyzed),
            "feature_causal_available_episode_count": sum(
                1 for row in analyzed if row.get("feature_status") == "CAUSAL_AVAILABLE"
            ),
            "primary_route_closed_feature_pairs": primary["usable_pair_count"],
            "minimum_primary_pairs_for_directional_read": minimum_pairs,
        },
        "primary_signal_quality": primary,
        "secondary_route_closed_net": secondary,
        "copyability_sensitive_reference": copyability,
        "incremental_vs_existing_evidence": incremental,
        "structure_diagnostics": structure,
        "source_integrity": {
            "run_integrity": run_integrity,
            "exact_discovery_run_set": True,
            "causal_window_reconstructed_from_raw_decoded_pump_trades": True,
            "external_holder_provider_used": False,
            "new_live_acquisition_used": False,
            "new_outcome_collection_used": False,
            "threshold_search_performed": False,
            "selector_changed": False,
            "participant_quality_changed": False,
            "route_contract_changed": False,
        },
        "guardrails": {
            "retrospective_discovery_only": True,
            "promotion_from_this_sample_allowed": False,
            "automatic_entry_decision_created": False,
            "automatic_profitability_claim": False,
            "single_score_created": False,
            "threshold_retuning_permitted": False,
        },
        "interpretation": (
            "This is retrospective discovery on already-captured runs. The feature measures concentration "
            "of observed net token acquisition inside the causal launch window; it is not a full-holder snapshot. "
            "Even a strong result can only justify mechanism/robustness review and a separately frozen prospective confirmation."
        ),
    }

    destination = Path(output_path or (resolved_dirs[-1] / "early-balance-concentration-v0.json"))
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
        "structure_diagnostics": report.get("structure_diagnostics"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrospective discovery evaluator for Early Balance Concentration V0"
    )
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_discovery(
            run_dirs=args.run_dir,
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
