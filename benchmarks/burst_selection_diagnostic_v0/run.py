from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_route_research_store import load_route_research_decision
from src.opportunity_wallet_market_history import (
    PRIOR_PARTICIPANT_WINDOW_SECONDS,
    load_market_first_wallet_opportunity_history,
)
from src.route_research_early_opportunity_v55 import (
    build_early_opportunity_dataset_v55,
)
from src.route_research_feature_robustness_v47 import (
    robust_return_metrics_v47,
)


VERSION = "burst_selection_diagnostic_v0"
CLASSIFICATION = "DIAGNOSTIC_ONLY_NO_FRESH_VERDICT"
PRIMARY_HORIZON_SECONDS = 900
HORIZONS_SECONDS = (300, 900, 3600)

PARTICIPANT_FEATURE = (
    "participant_prior_900_quote_return_median_of_wallet_medians_pct"
)
ENTRY_PRICE_IMPACT_FEATURE = "entry_price_impact_pct_points"
ENTRY_LIQUIDITY_FEATURE = "entry_liquidity_usd"

FEATURE_SPECS = {
    PARTICIPANT_FEATURE: {
        "family": "participant_quality",
        "expected_favorable_group": "HIGH",
        "source": (
            "median across current early BUY wallets of each wallet's median "
            "prior market-first +900s executable quote return, using only "
            "history resolved strictly before current episode T0"
        ),
    },
    ENTRY_PRICE_IMPACT_FEATURE: {
        "family": "copyability",
        "expected_favorable_group": "LOW",
        "source": "causal entry quote provider price impact known by research decision",
    },
    ENTRY_LIQUIDITY_FEATURE: {
        "family": "copyability",
        "expected_favorable_group": "HIGH",
        "source": "causal entry quote liquidity known by research decision",
    },
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between zero and one")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def tercile_cutpoints(values: Iterable[float]) -> tuple[float, float]:
    normalized = [float(item) for item in values]
    if not normalized or any(not math.isfinite(item) for item in normalized):
        raise ValueError("tercile values must be non-empty finite numbers")
    return _percentile(normalized, 1.0 / 3.0), _percentile(
        normalized, 2.0 / 3.0
    )


def tercile_group(value: float, low_cut: float, high_cut: float) -> str:
    numeric = float(value)
    if numeric <= low_cut:
        return "LOW"
    if numeric <= high_cut:
        return "MID"
    return "HIGH"


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        for position in range(cursor, end):
            ranks[indexed[position][0]] = average_rank
        cursor = end
    return ranks


def spearman_rank_correlation(
    feature_values: list[float],
    outcome_values: list[float],
) -> float | None:
    if len(feature_values) != len(outcome_values):
        raise ValueError("feature/outcome lengths must match")
    if len(feature_values) < 2:
        return None
    x = _average_ranks([float(item) for item in feature_values])
    y = _average_ranks([float(item) for item in outcome_values])
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    numerator = sum(
        (left - mean_x) * (right - mean_y)
        for left, right in zip(x, y)
    )
    denom_x = math.sqrt(sum((item - mean_x) ** 2 for item in x))
    denom_y = math.sqrt(sum((item - mean_y) ** 2 for item in y))
    if denom_x == 0.0 or denom_y == 0.0:
        return None
    return numerator / (denom_x * denom_y)


def median_of_wallet_medians(
    associations: Iterable[Any],
) -> tuple[float | None, int, int]:
    by_wallet: dict[str, list[float]] = defaultdict(list)
    association_count = 0
    for item in associations:
        wallet = str(getattr(item, "wallet_address", "") or "").strip()
        value = _finite_number(
            getattr(item, "executable_quote_return_pct", None)
        )
        if not wallet or value is None:
            continue
        by_wallet[wallet].append(value)
        association_count += 1
    wallet_medians = [
        float(median(values))
        for _, values in sorted(by_wallet.items())
        if values
    ]
    if not wallet_medians:
        return None, 0, association_count
    return (
        float(median(wallet_medians)),
        len(wallet_medians),
        association_count,
    )


def _safe_number(value: float | None) -> float | str | None:
    if value is None:
        return None
    numeric = float(value)
    if math.isfinite(numeric):
        return numeric
    if numeric > 0:
        return "INF"
    return "-INF"


def _metrics_dict(values: list[float]) -> dict[str, Any]:
    metrics = robust_return_metrics_v47(values)
    raw = asdict(metrics)
    return {
        key: _safe_number(value) if isinstance(value, (int, float)) else value
        for key, value in raw.items()
    }


def _scope_rows(rows, scope: str):
    if scope == "ALL":
        return tuple(rows)
    return tuple(row for row in rows if row.cohort == scope)


def _participant_feature_values(rows):
    values: dict[tuple[str, str], float | None] = {}
    details: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        key = (row.acquisition_run_key, row.episode_key)
        episode = get_market_opportunity_episode(row.episode_key)
        decision = load_route_research_decision(
            acquisition_run_key=row.acquisition_run_key,
            episode_key=row.episode_key,
        )
        if episode is None or decision is None:
            values[key] = None
            details[key] = {
                "status": "MISSING_EPISODE_OR_DECISION",
                "current_buy_wallet_count": 0,
                "wallets_with_prior_history": 0,
                "history_coverage_pct": None,
                "association_count": 0,
            }
            continue

        trades = load_market_trades(
            acquisition_run_key=row.acquisition_run_key,
            token_mint=row.token_mint,
            as_of=row.research_decision_as_of,
            chain_time_after=max(
                0,
                row.research_decision_as_of
                - PRIOR_PARTICIPANT_WINDOW_SECONDS,
            ),
        )
        buy_wallets = tuple(
            sorted(
                {
                    str(item.observation.wallet_address)
                    for item in trades
                    if item.observation.side == "buy"
                    and item.observation.wallet_address
                }
            )
        )

        history = load_market_first_wallet_opportunity_history(
            current_episode=episode,
            current_participant_wallets=buy_wallets,
            horizon_seconds=PRIMARY_HORIZON_SECONDS,
            history_cutoff=episode.first_trigger_observed_at,
        )
        feature, covered_wallets, association_count = median_of_wallet_medians(
            history.associations
        )
        values[key] = feature
        coverage = (
            100.0 * covered_wallets / len(buy_wallets)
            if buy_wallets
            else None
        )
        details[key] = {
            "status": "AVAILABLE" if feature is not None else "MISSING_HISTORY",
            "current_buy_wallet_count": len(buy_wallets),
            "wallets_with_prior_history": covered_wallets,
            "history_coverage_pct": coverage,
            "association_count": association_count,
            "candidate_prior_episode_count": (
                history.candidate_prior_episode_count
            ),
            "eligible_labeled_prior_episode_count": (
                history.eligible_labeled_prior_episode_count
            ),
            "prior_episodes_with_matching_participants": (
                history.prior_episodes_with_matching_participants
            ),
            "data_quality_flags": list(history.data_quality_flags),
            "exclusion_counts": dict(history.exclusion_counts),
        }

    return values, details


def _row_feature_values(rows, feature_name: str):
    return {
        (row.acquisition_run_key, row.episode_key): _finite_number(
            row.features.get(feature_name)
        )
        for row in rows
    }


def _feature_report(rows, feature_name: str, values):
    known = [value for value in values.values() if value is not None]
    if not known:
        return {
            "feature": feature_name,
            "spec": FEATURE_SPECS[feature_name],
            "coverage": {
                "known": 0,
                "total": len(rows),
                "pct": 0.0 if rows else None,
            },
            "cutpoints": None,
            "horizons": {},
        }

    low_cut, high_cut = tercile_cutpoints(known)
    assignments = {
        key: (
            tercile_group(value, low_cut, high_cut)
            if value is not None
            else None
        )
        for key, value in values.items()
    }

    report: dict[str, Any] = {
        "feature": feature_name,
        "spec": FEATURE_SPECS[feature_name],
        "coverage": {
            "known": len(known),
            "total": len(rows),
            "pct": 100.0 * len(known) / len(rows) if rows else None,
        },
        "cutpoints": {
            "low_max": low_cut,
            "mid_max": high_cut,
            "method": "outcome_blind_global_feature_terciles",
        },
        "horizons": {},
    }

    favorable = FEATURE_SPECS[feature_name]["expected_favorable_group"]
    opposite = "LOW" if favorable == "HIGH" else "HIGH"

    for horizon in HORIZONS_SECONDS:
        by_scope: dict[str, Any] = {}
        for scope in ("A", "B", "ALL"):
            scoped = _scope_rows(rows, scope)
            paired_feature: list[float] = []
            paired_outcome: list[float] = []
            grouped_values: dict[str, list[float]] = {
                "LOW": [],
                "MID": [],
                "HIGH": [],
            }
            label_available = 0
            feature_known = 0

            for row in scoped:
                key = (row.acquisition_run_key, row.episode_key)
                feature = values.get(key)
                outcome = _finite_number(row.labels.get(horizon))
                if feature is not None:
                    feature_known += 1
                if outcome is not None:
                    label_available += 1
                if feature is None or outcome is None:
                    continue
                paired_feature.append(float(feature))
                paired_outcome.append(float(outcome))
                group = assignments[key]
                if group is not None:
                    grouped_values[group].append(float(outcome))

            groups = {
                group: _metrics_dict(grouped_values[group])
                for group in ("LOW", "MID", "HIGH")
            }
            favorable_median = groups[favorable]["median_return_pct"]
            opposite_median = groups[opposite]["median_return_pct"]
            delta = (
                float(favorable_median) - float(opposite_median)
                if isinstance(favorable_median, (int, float))
                and isinstance(opposite_median, (int, float))
                else None
            )
            by_scope[scope] = {
                "rows": len(scoped),
                "feature_known": feature_known,
                "label_available": label_available,
                "paired": len(paired_outcome),
                "spearman": _safe_number(
                    spearman_rank_correlation(
                        paired_feature,
                        paired_outcome,
                    )
                ),
                "groups": groups,
                "expected_favorable_group": favorable,
                "opposite_group": opposite,
                "expected_favorable_minus_opposite_median_pct": delta,
            }
        report["horizons"][str(horizon)] = by_scope

    return report


def build_report(run_keys: tuple[str, ...]) -> dict[str, Any]:
    dataset = build_early_opportunity_dataset_v55(
        acquisition_run_keys=run_keys
    )
    rows = dataset.rows

    participant_values, participant_details = _participant_feature_values(rows)
    feature_values = {
        PARTICIPANT_FEATURE: participant_values,
        ENTRY_PRICE_IMPACT_FEATURE: _row_feature_values(
            rows,
            ENTRY_PRICE_IMPACT_FEATURE,
        ),
        ENTRY_LIQUIDITY_FEATURE: _row_feature_values(
            rows,
            ENTRY_LIQUIDITY_FEATURE,
        ),
    }

    baseline: dict[str, Any] = {}
    for horizon in HORIZONS_SECONDS:
        baseline[str(horizon)] = {}
        for scope in ("A", "B", "ALL"):
            values = [
                float(row.labels[horizon])
                for row in _scope_rows(rows, scope)
                if _finite_number(row.labels.get(horizon)) is not None
            ]
            baseline[str(horizon)][scope] = _metrics_dict(values)

    participant_detail_rows = []
    for row in rows:
        key = (row.acquisition_run_key, row.episode_key)
        detail = dict(participant_details[key])
        detail.update(
            {
                "acquisition_run_key": row.acquisition_run_key,
                "cohort": row.cohort,
                "episode_key": row.episode_key,
                "token_mint": row.token_mint,
                "feature_value": participant_values[key],
            }
        )
        participant_detail_rows.append(detail)

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
            "missing_decisions": dataset.base.missing_decisions,
            "missing_episodes": dataset.base.missing_episodes,
            "missing_hazard_attempts": dataset.base.missing_hazard_attempts,
            "missing_entry_quotes": dataset.base.missing_entry_quotes,
            "official_decision_mutations": (
                dataset.base.official_decision_mutations
            ),
            "augmentation_failures": dataset.augmentation_failures,
            "feature_clock_violations": dataset.feature_clock_violations,
        },
        "baseline": baseline,
        "features": {
            feature_name: _feature_report(
                rows,
                feature_name,
                values,
            )
            for feature_name, values in feature_values.items()
        },
        "participant_quality_episode_details": participant_detail_rows,
        "scientific_note": (
            "The consumed V68 -03 cohort is discovery-only for these new "
            "features. Tercile cutpoints use feature values only and never "
            "outcomes, but any candidate suggested by this report requires a "
            "new independently named fresh cohort before an edge claim."
        ),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_summary(report: dict[str, Any]) -> None:
    print("Crypto Copy Trader — Burst Selection Diagnostic V0")
    print(f"classification={report['classification']}")
    print(f"rows_total={report['rows_total']}")
    quality = report["dataset_quality"]
    print(
        "dataset_quality="
        f"lineage_violations={quality['lineage_violations']} "
        f"augmentation_failures={quality['augmentation_failures']} "
        f"feature_clock_violations={quality['feature_clock_violations']}"
    )

    print("\n=== BURST BASELINE 900s ===")
    for scope in ("A", "B", "ALL"):
        metrics = report["baseline"]["900"][scope]
        print(
            f"BURST_900_{scope} "
            f"n={metrics['n']} "
            f"positive_pct={_fmt(metrics['positive_share_pct'])} "
            f"mean={_fmt(metrics['mean_return_pct'])} "
            f"median={_fmt(metrics['median_return_pct'])} "
            f"PF={_fmt(metrics['profit_factor'])} "
            f"mean_without_best={_fmt(metrics['mean_without_best_pct'])}"
        )

    for feature_name, feature in report["features"].items():
        coverage = feature["coverage"]
        print(f"\n=== FEATURE {feature_name} ===")
        print(
            f"coverage={coverage['known']}/{coverage['total']} "
            f"({coverage['pct']:.1f}%)"
            if coverage["pct"] is not None
            else f"coverage={coverage['known']}/{coverage['total']}"
        )
        if feature["cutpoints"] is None:
            print("cutpoints=NA")
            continue
        print(
            f"terciles_low_max={feature['cutpoints']['low_max']:.6f} "
            f"mid_max={feature['cutpoints']['mid_max']:.6f} "
            f"expected_favorable={feature['spec']['expected_favorable_group']}"
        )
        for scope in ("A", "B", "ALL"):
            current = feature["horizons"]["900"][scope]
            fav = current["expected_favorable_group"]
            opp = current["opposite_group"]
            fav_metrics = current["groups"][fav]
            opp_metrics = current["groups"][opp]
            print(
                f"DIAG_900_{scope} "
                f"paired={current['paired']} "
                f"spearman={_fmt(current['spearman'])} "
                f"{fav}_n={fav_metrics['n']} "
                f"{fav}_median={_fmt(fav_metrics['median_return_pct'])} "
                f"{fav}_PF={_fmt(fav_metrics['profit_factor'])} "
                f"{fav}_mean_wo_best={_fmt(fav_metrics['mean_without_best_pct'])} "
                f"{opp}_n={opp_metrics['n']} "
                f"{opp}_median={_fmt(opp_metrics['median_return_pct'])} "
                f"delta_median={_fmt(current['expected_favorable_minus_opposite_median_pct'])}"
            )

    print("\nDIAGNOSTIC_ONLY=True")
    print("NO_SELECTOR_FROZEN=True")
    print("NO_NEW_FRESH=True")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only diagnostic on consumed V68 cohorts: Burst baseline, "
            "causal Participant Quality and entry Copyability features."
        )
    )
    parser.add_argument(
        "--run-keys",
        nargs="+",
        required=True,
        help="Consumed acquisition run keys, normally V68 -03 A/B.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/burst_selection_diagnostic_v0/report.json"
        ),
    )
    args = parser.parse_args()

    run_keys = tuple(str(item).strip() for item in args.run_keys if str(item).strip())
    if len(run_keys) != 2 or len(set(run_keys)) != 2:
        raise SystemExit("--run-keys requires exactly two unique A/B run keys")

    report = build_report(run_keys)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print_summary(report)
    print(f"report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
