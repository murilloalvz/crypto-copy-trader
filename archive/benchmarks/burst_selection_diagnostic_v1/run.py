from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any

from benchmarks.burst_selection_diagnostic_v0.run import (
    HORIZONS_SECONDS,
    _finite_number,
    _metrics_dict,
    _safe_number,
    _scope_rows,
    spearman_rank_correlation,
    tercile_cutpoints,
    tercile_group,
)
from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID as PARTICIPANT_FEATURE_ID,
    _episode_sources,
    _history_feature,
    _read_json,
)
from src.causal_quote_store import load_causal_quotes
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_route_research_store import load_route_research_decision
from src.route_research_early_opportunity_v55 import (
    build_early_opportunity_dataset_v55,
)


VERSION = "burst_selection_diagnostic_v1"
CLASSIFICATION = "DIAGNOSTIC_ONLY_NO_FRESH_VERDICT"
PRIMARY_HORIZON_SECONDS = 900

REPLICATION_PROTOCOL = (
    Path("benchmarks")
    / "early_buyer_prior_quality_replication_v0"
    / "protocol.frozen.json"
)
ROUTE_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)

PRICE_IMPACT_SIGNED = "entry_price_impact_pct_points"
PRICE_IMPACT_CLOSENESS = "entry_price_impact_closeness_to_zero"

FEATURE_SPECS = {
    PARTICIPANT_FEATURE_ID: {
        "family": "participant_quality",
        "direction_role": "replicated_higher_is_better",
        "expected_favorable_group": "HIGH",
        "source": (
            "exact frozen early-buyer prior-quality history semantics, "
            "using the four preregistered mature Launch Burst history captures"
        ),
    },
    PRICE_IMPACT_SIGNED: {
        "family": "copyability",
        "direction_role": "diagnostic_signed_no_favorable_direction",
        "expected_favorable_group": None,
        "source": (
            "Jupiter Swap V2 provider priceImpact percentage points; negative "
            "values are valid and must not be treated as invalid or automatically superior"
        ),
    },
    PRICE_IMPACT_CLOSENESS: {
        "family": "copyability",
        "direction_role": "diagnostic_higher_is_closer_to_zero",
        "expected_favorable_group": "HIGH",
        "source": (
            "outcome-blind transform -abs(provider priceImpact percentage points); "
            "higher values mean impact closer to zero"
        ),
    },
}


def _canonical_history_ids(protocol: dict[str, Any]) -> list[str]:
    return list(
        (protocol.get("mature_history_contract") or {}).get(
            "frozen_history_run_ids"
        )
        or []
    )


def validate_history_dirs(
    history_run_dirs: list[Path],
    protocol_path: Path = REPLICATION_PROTOCOL,
) -> tuple[list[Path], list[str]]:
    protocol = _read_json(Path(protocol_path))
    expected_ids = _canonical_history_ids(protocol)
    resolved = [Path(path).resolve() for path in history_run_dirs]
    supplied_ids = [path.name for path in resolved]
    if supplied_ids != expected_ids:
        raise ValueError(
            "history run ids must exactly match frozen order: "
            + ",".join(expected_ids)
        )
    for path in resolved:
        if not path.is_dir():
            raise ValueError(f"history run directory missing: {path}")
    return resolved, expected_ids


def load_frozen_history_rows(
    history_run_dirs: list[Path],
    *,
    contract_path: Path = ROUTE_CONTRACT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contract = _read_json(Path(contract_path))
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")
    universe: list[dict[str, Any]] = []
    integrity: list[dict[str, Any]] = []
    for run_dir in history_run_dirs:
        rows, meta = _episode_sources(
            run_dir=Path(run_dir),
            contract_hash=contract_hash,
        )
        universe.extend(rows)
        integrity.append(meta)
    universe.sort(
        key=lambda row: (
            int(row.get("observed_t0_wall_ns") or 0),
            str(row.get("run_id") or ""),
            str(row.get("episode_key") or ""),
        )
    )
    return universe, integrity


def current_early_buy_wallets(row) -> tuple[tuple[str, ...], bool, int]:
    episode = get_market_opportunity_episode(row.episode_key)
    decision = load_route_research_decision(
        acquisition_run_key=row.acquisition_run_key,
        episode_key=row.episode_key,
    )
    if episode is None or decision is None:
        return tuple(), False, 0

    trades = load_market_trades(
        acquisition_run_key=row.acquisition_run_key,
        token_mint=row.token_mint,
        as_of=row.research_decision_as_of,
    )
    window = [
        item
        for item in trades
        if episode.first_trigger_observed_at
        <= item.observation.observed_at
        <= row.research_decision_as_of
        and episode.first_trigger_chain_time
        <= item.observation.chain_time
        <= episode.first_trigger_chain_time + 5
    ]
    buys = [item for item in window if item.observation.side == "buy"]
    identity_complete = bool(buys) and all(
        item.observation.wallet_address is not None
        for item in buys
    )
    wallets = (
        tuple(
            sorted(
                {
                    str(item.observation.wallet_address)
                    for item in buys
                    if item.observation.wallet_address is not None
                }
            )
        )
        if identity_complete
        else tuple()
    )
    return wallets, identity_complete, len(buys)


def participant_feature_values(rows, history_rows):
    values: dict[tuple[str, str], float | None] = {}
    details: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.acquisition_run_key, row.episode_key)
        episode = get_market_opportunity_episode(row.episode_key)
        wallets, identity_complete, buy_event_count = current_early_buy_wallets(
            row
        )
        if episode is None:
            values[key] = None
            details[key] = {
                "status": "MISSING_EPISODE",
                "buy_identity_complete": False,
                "buy_event_count": 0,
                "buy_wallet_count": 0,
            }
            continue
        current = {
            "run_id": row.acquisition_run_key,
            "episode_key": row.episode_key,
            "token_mint": row.token_mint,
            "observed_t0": episode.first_trigger_observed_at,
            "baseline_admitted": True,
            "is_default_sol_quote": True,
            "buy_identity_complete": identity_complete,
            "buy_wallet_count": len(wallets) if identity_complete else None,
            "buy_wallets": wallets,
        }
        history = _history_feature(current, history_rows)
        feature = _finite_number(history.get(PARTICIPANT_FEATURE_ID))
        values[key] = feature
        details[key] = {
            "status": "AVAILABLE" if feature is not None else "MISSING_HISTORY",
            "buy_identity_complete": identity_complete,
            "buy_event_count": buy_event_count,
            "buy_wallet_count": len(wallets) if identity_complete else None,
            "history_coverage_pct": history.get("history_coverage_pct"),
            "wallets_with_history": history.get("wallets_with_history"),
            "prior_association_count": history.get(
                "prior_association_count"
            ),
            "prior_unique_episode_count": history.get(
                "prior_unique_episode_count"
            ),
            "prior_positive_association_share_pct": history.get(
                "prior_positive_association_share_pct"
            ),
        }
    return values, details


def entry_price_impact_values(rows):
    signed: dict[tuple[str, str], float | None] = {}
    closeness: dict[tuple[str, str], float | None] = {}
    for row in rows:
        key = (row.acquisition_run_key, row.episode_key)
        decision = load_route_research_decision(
            acquisition_run_key=row.acquisition_run_key,
            episode_key=row.episode_key,
        )
        value = None
        if decision is not None:
            quotes = load_causal_quotes(
                quote_keys=(decision.entry_quote_key,)
            )
            if len(quotes) == 1:
                value = _finite_number(
                    quotes[0].provider_price_impact_pct_points
                )
        signed[key] = value
        closeness[key] = -abs(value) if value is not None else None
    return signed, closeness


def feature_report(
    rows,
    *,
    feature_name: str,
    values: dict[tuple[str, str], float | None],
) -> dict[str, Any]:
    known = [float(value) for value in values.values() if value is not None]
    coverage = {
        "known": len(known),
        "total": len(rows),
        "pct": 100.0 * len(known) / len(rows) if rows else None,
    }
    if not known:
        return {
            "feature": feature_name,
            "spec": FEATURE_SPECS[feature_name],
            "coverage": coverage,
            "cutpoints": None,
            "horizons": {},
        }

    low_cut, high_cut = tercile_cutpoints(known)
    assignments = {
        key: (
            tercile_group(float(value), low_cut, high_cut)
            if value is not None
            else None
        )
        for key, value in values.items()
    }

    by_horizon: dict[str, Any] = {}
    for horizon in HORIZONS_SECONDS:
        scopes: dict[str, Any] = {}
        for scope in ("A", "B", "ALL"):
            scoped = _scope_rows(rows, scope)
            xs: list[float] = []
            ys: list[float] = []
            grouped: dict[str, list[float]] = {
                "LOW": [],
                "MID": [],
                "HIGH": [],
            }
            for row in scoped:
                key = (row.acquisition_run_key, row.episode_key)
                feature = values.get(key)
                outcome = _finite_number(row.labels.get(horizon))
                if feature is None or outcome is None:
                    continue
                xs.append(float(feature))
                ys.append(float(outcome))
                group = assignments[key]
                if group is not None:
                    grouped[group].append(float(outcome))

            scopes[scope] = {
                "paired": len(ys),
                "spearman": _safe_number(
                    spearman_rank_correlation(xs, ys)
                ),
                "groups": {
                    group: _metrics_dict(grouped[group])
                    for group in ("LOW", "MID", "HIGH")
                },
            }
        by_horizon[str(horizon)] = scopes

    return {
        "feature": feature_name,
        "spec": FEATURE_SPECS[feature_name],
        "coverage": coverage,
        "cutpoints": {
            "low_max": low_cut,
            "mid_max": high_cut,
            "method": "outcome_blind_global_feature_terciles",
        },
        "horizons": by_horizon,
    }


def build_report(
    *,
    run_keys: tuple[str, str],
    history_run_dirs: list[Path],
) -> dict[str, Any]:
    resolved_history, expected_ids = validate_history_dirs(
        history_run_dirs
    )
    history_rows, history_integrity = load_frozen_history_rows(
        resolved_history
    )
    dataset = build_early_opportunity_dataset_v55(
        acquisition_run_keys=run_keys
    )
    rows = dataset.rows

    participant, participant_details = participant_feature_values(
        rows,
        history_rows,
    )
    signed_impact, impact_closeness = entry_price_impact_values(rows)

    baseline: dict[str, Any] = {}
    for horizon in HORIZONS_SECONDS:
        baseline[str(horizon)] = {}
        for scope in ("A", "B", "ALL"):
            vals = [
                float(row.labels[horizon])
                for row in _scope_rows(rows, scope)
                if _finite_number(row.labels.get(horizon)) is not None
            ]
            baseline[str(horizon)][scope] = _metrics_dict(vals)

    feature_values = {
        PARTICIPANT_FEATURE_ID: participant,
        PRICE_IMPACT_SIGNED: signed_impact,
        PRICE_IMPACT_CLOSENESS: impact_closeness,
    }

    return {
        "type": "burst_selection_diagnostic_report",
        "version": VERSION,
        "classification": CLASSIFICATION,
        "authorization": (
            "read_only_discovery_on_consumed_v68_03_no_selector_no_new_fresh"
        ),
        "run_keys": list(run_keys),
        "rows_total": len(rows),
        "dataset_quality": {
            "lineage_violations": dataset.base.lineage_violations,
            "augmentation_failures": dataset.augmentation_failures,
            "feature_clock_violations": dataset.feature_clock_violations,
        },
        "baseline": baseline,
        "features": {
            name: feature_report(
                rows,
                feature_name=name,
                values=values,
            )
            for name, values in feature_values.items()
        },
        "participant_quality_episode_details": [
            {
                "acquisition_run_key": row.acquisition_run_key,
                "cohort": row.cohort,
                "episode_key": row.episode_key,
                "token_mint": row.token_mint,
                "feature_value": participant[
                    (row.acquisition_run_key, row.episode_key)
                ],
                **participant_details[
                    (row.acquisition_run_key, row.episode_key)
                ],
            }
            for row in rows
        ],
        "history_integrity": {
            "expected_frozen_history_run_ids": expected_ids,
            "supplied_history_run_ids": [
                path.name for path in resolved_history
            ],
            "all_exact_reconstruction_parity": all(
                item.get("exact_reconstruction_parity") is True
                for item in history_integrity
            ),
            "all_feature_snapshots_frozen_before_provider_quotes": all(
                item.get(
                    "feature_snapshot_frozen_before_provider_quotes"
                )
                is True
                for item in history_integrity
            ),
            "history_scope": (
                "four_frozen_mature_launch_burst_history_runs_only; "
                "V68 episodes are not backfilled as +60s history"
            ),
        },
        "price_impact_semantics": {
            "signed_value_negative_allowed": True,
            "signed_feature_has_no_preregistered_favorable_direction_here": True,
            "closeness_to_zero_transform": "-abs(priceImpact_pct_points)",
            "closeness_transform_outcome_blind": True,
        },
        "scientific_note": (
            "Consumed V68 -03 remains discovery-only for applicability. "
            "Participant Quality reuses the already replicated frozen feature "
            "semantics and mature-history sources; this report does not create "
            "a new production threshold or a fresh edge verdict. Signed "
            "Jupiter priceImpact is diagnostic because negative values are valid."
        ),
    }


def fmt(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_feature(report: dict[str, Any], feature_name: str) -> None:
    feature = report["features"][feature_name]
    cov = feature["coverage"]
    print(f"\n=== FEATURE {feature_name} ===")
    print(
        f"coverage={cov['known']}/{cov['total']} "
        + (
            f"({cov['pct']:.1f}%)"
            if cov["pct"] is not None
            else ""
        )
    )
    if feature["cutpoints"] is None:
        print("cutpoints=NA")
        return
    print(
        f"terciles_low_max={feature['cutpoints']['low_max']:.6f} "
        f"mid_max={feature['cutpoints']['mid_max']:.6f} "
        f"direction_role={feature['spec']['direction_role']}"
    )
    for scope in ("A", "B", "ALL"):
        current = feature["horizons"]["900"][scope]
        low = current["groups"]["LOW"]
        high = current["groups"]["HIGH"]
        print(
            f"DIAG_900_{scope} "
            f"paired={current['paired']} "
            f"spearman={fmt(current['spearman'])} "
            f"LOW_n={fmt(low['n'])} "
            f"LOW_median={fmt(low['median_return_pct'])} "
            f"LOW_PF={fmt(low['profit_factor'])} "
            f"LOW_mean_wo_best={fmt(low['mean_without_best_pct'])} "
            f"HIGH_n={fmt(high['n'])} "
            f"HIGH_median={fmt(high['median_return_pct'])} "
            f"HIGH_PF={fmt(high['profit_factor'])} "
            f"HIGH_mean_wo_best={fmt(high['mean_without_best_pct'])}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only applicability diagnostic for replicated Participant "
            "Quality and corrected Jupiter price-impact semantics on V68 -03."
        )
    )
    parser.add_argument("--run-keys", nargs=2, required=True)
    parser.add_argument(
        "--history-run-dir",
        action="append",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/burst_selection_diagnostic_v1/report.json"
        ),
    )
    args = parser.parse_args()

    report = build_report(
        run_keys=(
            str(args.run_keys[0]).strip(),
            str(args.run_keys[1]).strip(),
        ),
        history_run_dirs=list(args.history_run_dir),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    print("Crypto Copy Trader — Burst Selection Diagnostic V1")
    print(f"classification={report['classification']}")
    print(f"rows_total={report['rows_total']}")
    quality = report["dataset_quality"]
    print(
        "dataset_quality="
        f"lineage_violations={quality['lineage_violations']} "
        f"augmentation_failures={quality['augmentation_failures']} "
        f"feature_clock_violations={quality['feature_clock_violations']}"
    )
    history = report["history_integrity"]
    print(
        "history_integrity="
        f"exact_parity={history['all_exact_reconstruction_parity']} "
        "snapshots_pre_quotes="
        f"{history['all_feature_snapshots_frozen_before_provider_quotes']}"
    )

    print_feature(report, PARTICIPANT_FEATURE_ID)
    print_feature(report, PRICE_IMPACT_SIGNED)
    print_feature(report, PRICE_IMPACT_CLOSENESS)

    print("\nDIAGNOSTIC_ONLY=True")
    print("NO_SELECTOR_FROZEN=True")
    print("NO_NEW_FRESH=True")
    print(f"report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
