from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from benchmarks.market_first_feature_discovery_v1.run import (
    _causal_quote_asset_summary,
    _reconstruct_state,
    _same_number,
)
from benchmarks.launch_burst_sniper_v1.runtime_enrichment import feature_snapshot_with_sniper_v1
from src.market_first_feature_discovery_v1 import acceleration_features_v1


VERSION = "early_buyer_prior_quality_v0"
PASS = "PASS_EARLY_BUYER_PRIOR_QUALITY_V0"
FAIL = "FAIL_EARLY_BUYER_PRIOR_QUALITY_V0"
FEATURE_ID = "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct"
DEFAULT_PROTOCOL = Path("benchmarks") / "early_buyer_prior_quality_v0" / "protocol.frozen.json"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _pct(numerator: int, denominator: int) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm = sum(left) / len(left)
    rm = sum(right) / len(right)
    numerator = sum((x - lm) * (y - rm) for x, y in zip(left, right))
    lss = sum((x - lm) ** 2 for x in left)
    rss = sum((y - rm) ** 2 for y in right)
    if lss <= 0 or rss <= 0:
        return None
    out = numerator / math.sqrt(lss * rss)
    return out if math.isfinite(out) else None


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_average_ranks(left), _average_ranks(right))


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    n = len(vector)
    if len(matrix) != n or any(len(row) != n for row in matrix):
        raise ValueError("linear system shape mismatch")
    aug = [list(matrix[row]) + [float(vector[row])] for row in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) <= 1e-12:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [value / scale for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if abs(factor) <= 1e-15:
                continue
            aug[row] = [
                aug[row][idx] - factor * aug[col][idx]
                for idx in range(n + 1)
            ]
    return [aug[row][-1] for row in range(n)]


def _residualize(target: list[float], controls: list[list[float]]) -> list[float] | None:
    if not target:
        return None
    usable_controls = [
        column for column in controls
        if len(column) == len(target) and len(set(column)) > 1
    ]
    design = [
        [1.0, *[column[row] for column in usable_controls]]
        for row in range(len(target))
    ]
    width = len(design[0])
    xtx = [
        [
            sum(design[row][i] * design[row][j] for row in range(len(design)))
            for j in range(width)
        ]
        for i in range(width)
    ]
    xty = [
        sum(design[row][i] * target[row] for row in range(len(design)))
        for i in range(width)
    ]
    beta = _solve_linear(xtx, xty)
    if beta is None:
        return None
    return [
        target[row] - sum(design[row][col] * beta[col] for col in range(width))
        for row in range(len(design))
    ]


def _partial_spearman(
    predictor: list[float],
    outcome: list[float],
    controls: list[list[float]],
) -> float | None:
    if len(predictor) != len(outcome) or len(predictor) < 4:
        return None
    if any(len(column) != len(predictor) for column in controls):
        return None
    ranked_predictor = _average_ranks(predictor)
    ranked_outcome = _average_ranks(outcome)
    ranked_controls = [_average_ranks(column) for column in controls]
    predictor_residual = _residualize(ranked_predictor, ranked_controls)
    outcome_residual = _residualize(ranked_outcome, ranked_controls)
    if predictor_residual is None or outcome_residual is None:
        return None
    return _pearson(predictor_residual, outcome_residual)


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {key: value for key, value in dict(protocol).items() if key != "protocol_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("early-buyer prior-quality protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_RETROSPECTIVE_CAUSAL_DISCOVERY":
        raise ValueError("early-buyer prior-quality protocol is not preregistered")
    if (protocol.get("feature_contract") or {}).get("primary_feature_id") != FEATURE_ID:
        raise ValueError("unexpected primary feature id")


def _episode_sources(
    *,
    run_dir: Path,
    contract_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    processed_root = run_dir / "processed-chunks"
    for path in (route_input_path, route_result_path):
        if not path.is_file():
            raise ValueError(f"required participant-quality source missing: {path}")
    if not processed_root.is_dir():
        raise ValueError(f"processed-chunks directory missing: {processed_root}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    if route_input.get("contract_hash_sha256") != contract_hash:
        raise ValueError(f"route input contract mismatch: {run_dir}")
    if route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError(f"route result contract mismatch: {run_dir}")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError(f"feature snapshots were not frozen before provider quotes: {run_dir}")

    state, processed_chunk_count = _reconstruct_state(processed_root)
    decisions = {
        str(row.get("episode_key") or ""): row
        for row in route_result.get("decisions") or []
        if isinstance(row, dict) and str(row.get("episode_key") or "")
    }

    output: list[dict[str, Any]] = []
    parity_errors: list[str] = []
    complete_count = 0

    for episode in route_input.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        snapshot = episode.get("feature_snapshot") or {}
        if snapshot.get("complete") is not True:
            continue
        complete_count += 1
        episode_key = str(episode.get("episode_key") or "")
        token_mint = str(episode.get("token_mint") or "")
        anchor_wall_ns = int(snapshot.get("observed_t0_wall_ns") or 0)
        cutoff_wall_ns = int(snapshot.get("decision_cutoff_wall_ns") or 0)
        observed_t0 = int(snapshot.get("observed_t0") or 0)

        anchor = state.anchors.get((token_mint, "pump"))
        if not anchor:
            parity_errors.append(f"missing_anchor:{episode_key}")
            continue
        if int(anchor.get("observed_wall_ns") or 0) != anchor_wall_ns:
            parity_errors.append(f"anchor_clock_mismatch:{episode_key}")
            continue
        chain_t0 = int(anchor.get("chain_t0") or 0)
        rows = [
            item
            for item in state.adapted
            if item.token_mint == token_mint
            and item.venue == "pump"
            and anchor_wall_ns <= item.observed_wall_ns <= cutoff_wall_ns
            and chain_t0 <= item.chain_time <= chain_t0 + 5
        ]

        replay = feature_snapshot_with_sniper_v1(rows, anchor_wall_ns=anchor_wall_ns)
        stored = snapshot.get("features") or {}
        checks = {
            "event_count": replay.get("event_count") == stored.get("event_count"),
            "signed_flow_over_event_reserve": _same_number(
                replay.get("signed_flow_over_event_reserve"),
                stored.get("signed_flow_over_event_reserve"),
            ),
            "directional_flow_efficiency": _same_number(
                replay.get("directional_flow_efficiency"),
                stored.get("directional_flow_efficiency"),
            ),
            "unique_buy_wallet_count": replay.get("unique_buy_wallet_count")
            == stored.get("unique_buy_wallet_count"),
            "quote_asset_identity_count": replay.get("quote_asset_identity_count")
            == stored.get("quote_asset_identity_count"),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            parity_errors.append(f"feature_parity:{episode_key}:{','.join(failed)}")
            continue

        quote_asset = _causal_quote_asset_summary(rows)
        acceleration = acceleration_features_v1(
            rows,
            anchor_wall_ns=anchor_wall_ns,
            cutoff_wall_ns=cutoff_wall_ns,
        )
        buy_rows = [item for item in rows if item.side == "buy"]
        buy_identity_complete = bool(buy_rows) and all(item.wallet_key is not None for item in buy_rows)
        buy_wallets = (
            tuple(sorted({str(item.wallet_key) for item in buy_rows if item.wallet_key is not None}))
            if buy_identity_complete
            else tuple()
        )

        decision = decisions.get(episode_key) or {}
        status = str(decision.get("status") or "MISSING")
        route_usable = status == "ROUTE_CLOSED" or status.startswith("UNROUTABLE_EXIT")
        gross = _finite(decision.get("gross_route_return_pct")) if status == "ROUTE_CLOSED" else None
        net = _finite(decision.get("net_route_return_pct")) if route_usable else None

        exit_observed_at = None
        if status == "ROUTE_CLOSED":
            exit_quote = decision.get("exit_quote")
            if isinstance(exit_quote, dict):
                raw = exit_quote.get("observed_at")
                if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                    exit_observed_at = int(raw)

        output.append(
            {
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                "episode_key": episode_key,
                "token_mint": token_mint,
                "observed_t0": observed_t0,
                "observed_t0_wall_ns": anchor_wall_ns,
                "baseline_admitted": decision.get("admitted") is True,
                "route_status": status,
                "route_usable": route_usable,
                "current_route_closed_gross_return_pct": gross,
                "current_route_closed_net_return_pct": (
                    _finite(decision.get("net_route_return_pct"))
                    if status == "ROUTE_CLOSED"
                    else None
                ),
                "current_route_usable_fixed_return_pct": net,
                "exit_observed_at": exit_observed_at,
                "is_default_sol_quote": quote_asset.get("is_default_sol_quote") is True,
                "buy_identity_complete": buy_identity_complete,
                "buy_wallet_count": len(buy_wallets) if buy_identity_complete else None,
                "buy_wallets": buy_wallets,
                "mf_buy_event_rate_acceleration_per_s2": _finite(
                    acceleration.get("mf_buy_event_rate_acceleration_per_s2")
                ),
                "signed_flow_over_event_reserve": _finite(
                    stored.get("signed_flow_over_event_reserve")
                ),
            }
        )

    if parity_errors:
        raise ValueError(
            f"causal participant reconstruction parity failed for {run_dir}: "
            + ";".join(parity_errors[:10])
        )

    return output, {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "processed_chunk_count": processed_chunk_count,
        "route_input_episode_count": len(route_input.get("episodes") or []),
        "complete_episode_count": complete_count,
        "reconstructed_complete_episode_count": len(output),
        "exact_reconstruction_parity": True,
        "feature_snapshot_frozen_before_provider_quotes": True,
        "route_contract_hash_sha256": contract_hash,
    }


def _history_feature(
    current: Mapping[str, Any],
    universe: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if current.get("buy_identity_complete") is not True:
        return {
            FEATURE_ID: None,
            "history_coverage_pct": None,
            "wallets_with_history": 0,
            "current_buy_wallet_count": current.get("buy_wallet_count"),
            "prior_association_count": 0,
            "prior_unique_episode_count": 0,
            "prior_positive_association_share_pct": None,
        }

    current_wallets = tuple(current.get("buy_wallets") or ())
    current_t0 = int(current.get("observed_t0") or 0)
    current_token = str(current.get("token_mint") or "")
    current_episode_key = str(current.get("episode_key") or "")
    current_run_id = str(current.get("run_id") or "")

    wallet_history: dict[str, list[tuple[str, str, float]]] = {
        wallet: [] for wallet in current_wallets
    }
    for prior in universe:
        if prior.get("baseline_admitted") is not True:
            continue
        if prior.get("is_default_sol_quote") is not True:
            continue
        if prior.get("buy_identity_complete") is not True:
            continue
        if str(prior.get("route_status") or "") != "ROUTE_CLOSED":
            continue
        gross = _finite(prior.get("current_route_closed_gross_return_pct"))
        resolved_at = prior.get("exit_observed_at")
        if gross is None or not isinstance(resolved_at, int) or isinstance(resolved_at, bool):
            continue
        # Strict pre-T0: same-second resolution is excluded because ordering is ambiguous.
        if int(resolved_at) >= current_t0:
            continue
        if str(prior.get("token_mint") or "") == current_token:
            continue
        if (
            str(prior.get("episode_key") or "") == current_episode_key
            and str(prior.get("run_id") or "") == current_run_id
        ):
            continue
        prior_wallets = set(prior.get("buy_wallets") or ())
        for wallet in current_wallets:
            if wallet in prior_wallets:
                wallet_history[wallet].append(
                    (
                        str(prior.get("run_id") or ""),
                        str(prior.get("episode_key") or ""),
                        gross,
                    )
                )

    wallet_medians: list[float] = []
    all_association_returns: list[float] = []
    prior_episode_keys: set[tuple[str, str]] = set()
    wallets_with_history = 0
    for wallet in current_wallets:
        history = wallet_history[wallet]
        if not history:
            continue
        wallets_with_history += 1
        returns = [item[2] for item in history]
        wallet_medians.append(float(median(returns)))
        all_association_returns.extend(returns)
        prior_episode_keys.update((item[0], item[1]) for item in history)

    return {
        FEATURE_ID: float(median(wallet_medians)) if wallet_medians else None,
        "history_coverage_pct": _pct(wallets_with_history, len(current_wallets)),
        "wallets_with_history": wallets_with_history,
        "current_buy_wallet_count": len(current_wallets),
        "prior_association_count": len(all_association_returns),
        "prior_unique_episode_count": len(prior_episode_keys),
        "prior_positive_association_share_pct": (
            100.0 * sum(value > 0 for value in all_association_returns) / len(all_association_returns)
            if all_association_returns
            else None
        ),
    }


def _association(rows: list[Mapping[str, Any]], outcome_key: str) -> dict[str, Any]:
    pairs: list[tuple[float, float, Mapping[str, Any]]] = []
    for row in rows:
        feature = _finite(row.get(FEATURE_ID))
        outcome = _finite(row.get(outcome_key))
        if feature is not None and outcome is not None:
            pairs.append((feature, outcome, row))
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
    lower = [item[1] for item in pairs if split is not None and item[0] <= split]
    upper = [item[1] for item in pairs if split is not None and item[0] > split]
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
            "n": len(upper),
            "mean_outcome_pct": _mean(upper),
            "median_outcome_pct": median(upper) if upper else None,
        },
    }


def _incremental_partial(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    complete: list[tuple[float, float, float, float]] = []
    for row in rows:
        feature = _finite(row.get(FEATURE_ID))
        outcome = _finite(row.get("current_route_closed_gross_return_pct"))
        acceleration = _finite(row.get("mf_buy_event_rate_acceleration_per_s2"))
        signed_flow = _finite(row.get("signed_flow_over_event_reserve"))
        if None not in (feature, outcome, acceleration, signed_flow):
            complete.append(
                (
                    float(feature),
                    float(outcome),
                    float(acceleration),
                    float(signed_flow),
                )
            )
    if len(complete) < 4:
        return {
            "usable_pair_count": len(complete),
            "partial_spearman": None,
            "controls": [
                "mf_buy_event_rate_acceleration_per_s2",
                "signed_flow_over_event_reserve",
            ],
        }
    partial = _partial_spearman(
        [item[0] for item in complete],
        [item[1] for item in complete],
        [
            [item[2] for item in complete],
            [item[3] for item in complete],
        ],
    )
    return {
        "usable_pair_count": len(complete),
        "partial_spearman": partial,
        "controls": [
            "mf_buy_event_rate_acceleration_per_s2",
            "signed_flow_over_event_reserve",
        ],
        "spearman_feature_vs_buy_acceleration": _spearman(
            [item[0] for item in complete],
            [item[2] for item in complete],
        ),
        "spearman_feature_vs_signed_flow": _spearman(
            [item[0] for item in complete],
            [item[3] for item in complete],
        ),
    }


def _decision(
    *,
    protocol: Mapping[str, Any],
    primary: Mapping[str, Any],
    per_run: Mapping[str, Mapping[str, Any]],
    incremental: Mapping[str, Any],
) -> tuple[str, list[str], dict[str, bool | None]]:
    rule = protocol.get("decision_rule") or {}
    minimum_pairs = int(rule.get("minimum_pooled_primary_pairs") or 0)
    minimum_runs = int(rule.get("minimum_informative_runs") or 0)
    per_run_min = int(rule.get("minimum_pairs_per_informative_run") or 0)

    informative = [
        row for row in per_run.values()
        if int(row.get("usable_pair_count") or 0) >= per_run_min
        and _finite(row.get("spearman")) is not None
    ]
    positive_runs = sum(float(row["spearman"]) > 0 for row in informative)
    positive_fraction = positive_runs / len(informative) if informative else None

    rho = _finite(primary.get("spearman"))
    without_best = _finite(primary.get("spearman_without_best_trade"))
    loo = _finite(primary.get("leave_one_out_sign_consistency_fraction"))
    partial = _finite(incremental.get("partial_spearman"))

    checks: dict[str, bool | None] = {
        "minimum_sample_met": int(primary.get("usable_pair_count") or 0) >= minimum_pairs,
        "minimum_informative_runs_met": len(informative) >= minimum_runs,
        "pooled_spearman_positive": rho is not None and rho > 0,
        "pooled_spearman_nonpositive": rho is not None and rho <= 0,
        "pooled_spearman_without_best_positive": without_best is not None and without_best > 0,
        "pooled_spearman_without_best_nonpositive": without_best is not None and without_best <= 0,
        "pooled_leave_one_out_sign_consistency_gte_0_90": loo is not None and loo >= 0.90,
        "positive_direction_run_fraction_gte_two_thirds": (
            positive_fraction is not None and positive_fraction >= (2.0 / 3.0)
        ),
        "positive_direction_run_fraction_lt_0_50": (
            positive_fraction is not None and positive_fraction < 0.50
        ),
        "partial_spearman_positive_if_estimable": partial is not None and partial > 0,
    }

    if all(checks.get(name) is True for name in rule.get("keep_if_all") or []):
        return "KEEP", ["all_preregistered_signal_quality_keep_conditions_passed"], checks
    if all(checks.get(name) is True for name in rule.get("kill_if_all") or []):
        return "KILL", ["all_preregistered_signal_quality_kill_conditions_passed"], checks
    reasons: list[str] = []
    if not checks["minimum_sample_met"]:
        reasons.append("insufficient_pooled_prior_history_pairs")
    if not checks["minimum_informative_runs_met"]:
        reasons.append("insufficient_cross_run_history_coverage")
    if partial is None:
        reasons.append("incremental_partial_spearman_not_estimable")
    if not reasons:
        reasons.append("mixed_direction_or_robustness_requires_no_threshold_retuning")
    return "ITERATE", reasons, checks


def run_discovery(
    *,
    run_dirs: list[Path],
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if len(run_dirs) < 2:
        raise ValueError("at least two run dirs are required for prior-opportunity history")
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol)
    contract = _read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")

    resolved_dirs = [Path(path).resolve() for path in run_dirs]
    if len(set(map(str, resolved_dirs))) != len(resolved_dirs):
        raise ValueError("run dirs must be unique")

    universe: list[dict[str, Any]] = []
    source_integrity: list[dict[str, Any]] = []
    for run_dir in resolved_dirs:
        rows, integrity = _episode_sources(
            run_dir=run_dir,
            contract_hash=contract_hash,
        )
        universe.extend(rows)
        source_integrity.append(integrity)
    universe.sort(
        key=lambda row: (
            int(row.get("observed_t0_wall_ns") or 0),
            str(row.get("run_id") or ""),
            str(row.get("episode_key") or ""),
        )
    )

    analyzed_rows: list[dict[str, Any]] = []
    for row in universe:
        if row.get("baseline_admitted") is not True or row.get("is_default_sol_quote") is not True:
            continue
        history = _history_feature(row, universe)
        analyzed_rows.append(
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

    primary = _association(analyzed_rows, "current_route_closed_gross_return_pct")
    secondary = _association(analyzed_rows, "current_route_closed_net_return_pct")
    copyability_sensitive = _association(
        analyzed_rows,
        "current_route_usable_fixed_return_pct",
    )
    per_run: dict[str, Any] = {}
    for run_id in sorted({str(row["run_id"]) for row in analyzed_rows}):
        per_run[run_id] = _association(
            [row for row in analyzed_rows if row["run_id"] == run_id],
            "current_route_closed_gross_return_pct",
        )
    incremental = _incremental_partial(analyzed_rows)
    decision, reasons, checks = _decision(
        protocol=protocol,
        primary=primary,
        per_run=per_run,
        incremental=incremental,
    )

    buy_complete = [row for row in analyzed_rows if row["buy_identity_complete"] is True]
    with_history = [row for row in analyzed_rows if _finite(row.get(FEATURE_ID)) is not None]
    history_coverages = [
        float(value)
        for row in analyzed_rows
        if (value := _finite(row.get("history_coverage_pct"))) is not None
    ]

    report = {
        "type": "early_buyer_prior_quality_report_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "decision_reasons": reasons,
        "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
        "inference_role": "RETROSPECTIVE_CAUSAL_DISCOVERY_ONLY_NO_ALPHA_CLAIM",
        "feature_id": FEATURE_ID,
        "feature_semantics": protocol.get("feature_contract"),
        "population": {
            "baseline_default_sol_episode_count": len(analyzed_rows),
            "buy_identity_complete_episode_count": len(buy_complete),
            "feature_available_episode_count": len(with_history),
            "feature_availability_pct_of_population": _pct(
                len(with_history), len(analyzed_rows)
            ),
            "mean_current_wallet_history_coverage_pct": _mean(history_coverages),
            "run_count": len(resolved_dirs),
        },
        "signal_quality": {
            "primary_route_closed_gross_plus_60s": primary,
            "secondary_route_closed_net_plus_60s": secondary,
            "per_run_primary": per_run,
            "incremental_vs_existing_flow": incremental,
        },
        "copyability_sensitive_reference": {
            "route_usable_fixed_plus_60s_including_unroutable_exit_minus_100": copyability_sensitive,
            "role": "REFERENCE_ONLY_NOT_PRIMARY_SIGNAL_ENDPOINT",
        },
        "decision_rule_checks": checks,
        "source_integrity": {
            "route_contract_hash_sha256": contract_hash,
            "all_runs_exact_reconstruction_parity": all(
                item.get("exact_reconstruction_parity") is True
                for item in source_integrity
            ),
            "feature_snapshots_frozen_before_provider_quotes": all(
                item.get("feature_snapshot_frozen_before_provider_quotes") is True
                for item in source_integrity
            ),
            "strict_pre_t0_history": True,
            "same_second_history_excluded": True,
            "same_token_prior_history_excluded": True,
            "wallet_realized_pnl_claim": False,
            "source_runs": source_integrity,
        },
        "guardrails": {
            "threshold_search_performed": False,
            "selector_changed": False,
            "single_score_created": False,
            "external_wallet_score_used": False,
            "future_history_used": False,
            "manual_exit_instruction": False,
            "keep_requires_fresh_confirmation": decision == "KEEP",
        },
        "rows": analyzed_rows,
        "interpretation": (
            "This discovery asks whether BUY wallets already associated with better strictly pre-T0 "
            "route-closed +60s opportunities carry current signal-quality information. Historical "
            "opportunity returns are association labels, not wallet realized PnL. The primary endpoint "
            "uses current ROUTE_CLOSED gross +60s return to reduce copyability/exit-failure contamination. "
            "KEEP means only that the feature is worth freezing for fresh confirmation."
        ),
    }

    destination = (
        output_path
        or (resolved_dirs[-1] / "early-buyer-prior-quality-v0.json")
    )
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "decision": report.get("decision"),
        "decision_reasons": report.get("decision_reasons"),
        "population": report.get("population"),
        "primary_signal_quality": (
            (report.get("signal_quality") or {}).get("primary_route_closed_gross_plus_60s")
        ),
        "incremental_vs_existing_flow": (
            (report.get("signal_quality") or {}).get("incremental_vs_existing_flow")
        ),
        "per_run_primary": (
            (report.get("signal_quality") or {}).get("per_run_primary")
        ),
        "copyability_sensitive_reference": report.get("copyability_sensitive_reference"),
        "decision_rule_checks": report.get("decision_rule_checks"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Causal discovery of early-buyer prior opportunity quality"
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
