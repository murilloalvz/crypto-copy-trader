from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from benchmarks.early_buyer_churn_prospective_v1.parity import (
    validate_parity_report,
)
from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    read_json,
    validate_protocol,
)
from benchmarks.early_buyer_churn_prospective_v1.provider_preflight import (
    PASS as PROVIDER_PREFLIGHT_PASS,
)
from benchmarks.early_buyer_churn_prospective_v1.run_live import (
    _same_value,
)
from benchmarks.early_buyer_churn_prospective_v1.runtime_enrichment import (
    EXTERNAL_EVIDENCE_KEY,
)
from benchmarks.early_buyer_churn_v0.run import (
    FEATURE_ID,
    _association,
    _incremental,
)
from benchmarks.early_buyer_prior_quality_v0.run import (
    FEATURE_ID as PARTICIPANT_QUALITY_FEATURE_ID,
    _episode_sources,
    _finite,
    _history_feature,
)
from benchmarks.market_first_feature_discovery_v1.run import (
    _causal_quote_asset_summary,
    _reconstruct_state,
    _same_number,
)
from benchmarks.launch_burst_sniper_v1.runtime_enrichment import (
    feature_snapshot_with_sniper_v1,
)
from src.market_first_feature_discovery_v1 import acceleration_features_v1


PASS = "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1"
FAIL = "FAIL_EARLY_BUYER_CHURN_PROSPECTIVE_V1"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)


def _route_input_sha256(run_dir: Path) -> str:
    path = Path(run_dir) / "route-input-v2.json"
    if not path.is_file():
        raise ValueError(f"route input missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_fresh_wrapper(
    *,
    fresh_run_dir: Path,
    protocol: Mapping[str, Any],
    parity_report_path: Path,
) -> dict[str, Any]:
    wrapper_path = (
        Path(fresh_run_dir)
        / "simulation-report-v4-early-buyer-churn-prospective-v1.json"
    )
    wrapper = read_json(wrapper_path)
    if wrapper.get("classification") != (
        "PASS_LAUNCH_BURST_EARLY_BUYER_CHURN_PROSPECTIVE_V1"
    ):
        raise ValueError("fresh churn prospective wrapper did not PASS")
    if wrapper.get("protocol_hash_sha256") != protocol.get("protocol_hash_sha256"):
        raise ValueError("fresh churn wrapper protocol hash mismatch")

    expected_duration = int(
        (protocol.get("fresh_confirmation") or {}).get(
            "requested_duration_seconds"
        )
        or 0
    )
    base = wrapper.get("base_v4_report") or {}
    capture = base.get("capture") or {}
    if int(base.get("requested_duration_seconds") or 0) != expected_duration:
        raise ValueError("fresh churn requested duration changed")
    if str(capture.get("stop_reason") or "") != "duration_elapsed":
        raise ValueError("fresh churn capture did not complete requested duration")
    if base.get("economic_outcomes_opened") is not True:
        raise ValueError("fresh churn wrapper did not open route-paper outcomes")
    if str(base.get("mode") or "") != "route_paper_economic":
        raise ValueError("fresh churn wrapper is not route-paper economic mode")
    if not str(base.get("classification") or "").startswith("PASS_"):
        raise ValueError("fresh churn base V4 report did not PASS")

    churn = wrapper.get("churn_prospective_v1") or {}
    if churn.get("systems_valid") is not True:
        raise ValueError("fresh churn instrumentation is systems-invalid")
    if churn.get("instrumentation_valid") is not True:
        raise ValueError("fresh churn route-input instrumentation invalid")
    if churn.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("fresh churn feature snapshot order guard failed")

    guardrails = wrapper.get("guardrails") or {}
    required_false = (
        "feature_definition_changed",
        "external_provider_used_for_churn",
        "selector_changed",
        "participant_quality_changed",
        "route_contract_changed",
        "threshold_search_performed",
        "transaction_signed",
        "transaction_submitted",
        "automatic_profitability_claim",
    )
    for key in required_false:
        if guardrails.get(key) is not False:
            raise ValueError(f"fresh churn guardrail changed: {key}")
    if guardrails.get("feature_computed_before_provider_quotes") is not True:
        raise ValueError("fresh churn provider-order guard changed")
    if guardrails.get("exact_parity_attested") is not True:
        raise ValueError("fresh churn wrapper did not attest exact parity")

    required_true = (
        "provider_health_preflight_required_before_capture",
        "provider_health_rechecked_immediately_before_capture",
        "rpc_endpoint_fixed_for_run",
        "exact_approved_preflight_control_reused",
        "exact_preflight_control_reused",
    )
    for key in required_true:
        if guardrails.get(key) is not True:
            raise ValueError(f"fresh churn provider guardrail changed: {key}")

    if guardrails.get("market_ingest_provider") != "solana_public_standard_wss":
        raise ValueError("fresh churn market ingest provider changed")
    if guardrails.get("market_ingest_http_hydration") is not False:
        raise ValueError("fresh churn market ingest HTTP hydration changed")
    for key in (
        "helius_market_ingest_used",
        "helius_control_discovery_used",
        "helius_dependency_active",
    ):
        if guardrails.get(key) is not False:
            raise ValueError(f"fresh churn Helius guardrail changed: {key}")

    selected_host = str(guardrails.get("selected_rpc_safe_host") or "").lower()
    if not selected_host or "helius" in selected_host:
        raise ValueError("fresh churn selected RPC host is missing or Helius-backed")

    artifacts = wrapper.get("artifacts") or {}
    provider_preflight_path = Path(
        str(artifacts.get("provider_preflight") or "")
    )
    if not provider_preflight_path.is_file():
        raise ValueError("fresh churn provider preflight artifact missing")
    provider_report = read_json(provider_preflight_path)
    if provider_report.get("classification") != PROVIDER_PREFLIGHT_PASS:
        raise ValueError("fresh churn provider preflight artifact did not PASS")
    provider_selected = provider_report.get("selected_rpc") or {}
    if str(provider_selected.get("safe_host") or "").lower() != selected_host:
        raise ValueError("fresh churn provider preflight RPC host mismatch")
    provider_control = provider_report.get("control") or {}
    approved_control_hash = str(
        provider_control.get("owner_public_key_sha256") or ""
    ).strip().lower()
    wrapper_control_hash = str(
        guardrails.get("selected_control_hash_sha256") or ""
    ).strip().lower()
    if not approved_control_hash or wrapper_control_hash != approved_control_hash:
        raise ValueError("fresh churn approved control hash mismatch")
    if provider_report.get("economic_outcomes_opened") is not False:
        raise ValueError("provider preflight unexpectedly opened economic outcomes")
    if provider_report.get("fresh_confirmation_consumed") is not False:
        raise ValueError("provider preflight unexpectedly consumed fresh confirmation")
    if provider_report.get("helius_dependency_active") is not False:
        raise ValueError("provider preflight unexpectedly used Helius")

    recheck = wrapper.get("provider_preflight_recheck") or {}
    if recheck.get("classification") != PROVIDER_PREFLIGHT_PASS:
        raise ValueError("fresh churn immediate provider recheck did not PASS")
    recheck_selected = recheck.get("selected_rpc") or {}
    if str(recheck_selected.get("safe_host") or "").lower() != selected_host:
        raise ValueError("fresh churn immediate provider recheck RPC host mismatch")
    recheck_control = recheck.get("control") or {}
    recheck_control_hash = str(
        recheck_control.get("owner_public_key_sha256") or ""
    ).strip().lower()
    if recheck_control_hash != approved_control_hash:
        raise ValueError("fresh churn immediate provider recheck control hash mismatch")

    parity = validate_parity_report(
        parity_report_path=parity_report_path,
        protocol=protocol,
    )
    wrapper_parity = wrapper.get("parity_attestation") or {}
    if wrapper_parity.get("protocol_hash_sha256") != parity.get(
        "protocol_hash_sha256"
    ):
        raise ValueError("fresh wrapper parity attestation differs from supplied parity")
    if int(wrapper_parity.get("mismatch_count") or 0) != 0:
        raise ValueError("fresh wrapper parity attestation contains mismatches")

    return {
        "wrapper": str(wrapper_path.resolve()),
        "classification": wrapper.get("classification"),
        "requested_duration_seconds": expected_duration,
        "capture_stop_reason": capture.get("stop_reason"),
        "mode": base.get("mode"),
        "economic_outcomes_opened": True,
        "complete_episode_count": int(churn.get("complete_episode_count") or 0),
        "causal_available_count": int(churn.get("causal_available_count") or 0),
        "missing_no_buy_count": int(churn.get("missing_no_buy_count") or 0),
        "right_censored_count": int(churn.get("right_censored_count") or 0),
        "selected_rpc_safe_host": selected_host,
        "selected_control_hash_sha256": approved_control_hash,
        "provider_preflight_artifact": str(provider_preflight_path.resolve()),
        "provider_preflight_classification": provider_report.get("classification"),
        "provider_recheck_classification": recheck.get("classification"),
        "helius_dependency_active": False,
        "parity": parity,
    }


def _load_fresh_churn_map(run_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    route_input = read_json(Path(run_dir) / "route-input-v2.json")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("fresh route input feature snapshot order guard failed")

    mapping: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}
    errors: list[str] = []

    for episode in route_input.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        snapshot = episode.get("feature_snapshot") or {}
        if snapshot.get("complete") is not True:
            continue
        episode_key = str(episode.get("episode_key") or "")
        if not episode_key:
            errors.append("complete_episode_missing_key")
            continue
        features = snapshot.get("features") or {}
        evidence = (
            (snapshot.get("external_evidence") or {}).get(EXTERNAL_EVIDENCE_KEY)
            or {}
        )
        status = str(evidence.get("status") or "MISSING_EVIDENCE")
        status_counts[status] = status_counts.get(status, 0) + 1
        value = features.get(FEATURE_ID)

        if evidence.get("feature_id") != FEATURE_ID:
            errors.append(f"feature_id:{episode_key}")
        if evidence.get("computed_before_provider_quotes") is not True:
            errors.append(f"provider_order:{episode_key}")
        if evidence.get("external_provider_used") is not False:
            errors.append(f"external_provider:{episode_key}")
        if not _same_value(value, evidence.get("feature_value")):
            errors.append(f"feature_value_mismatch:{episode_key}")

        if status == "CAUSAL_AVAILABLE":
            if _finite(value) is None:
                errors.append(f"causal_available_missing_value:{episode_key}")
        elif status == "MISSING_NO_OBSERVED_BUY":
            if value is not None:
                errors.append(f"missing_no_buy_has_value:{episode_key}")
        else:
            errors.append(f"unexpected_status:{episode_key}:{status}")

        mapping[episode_key] = {
            "status": status,
            FEATURE_ID: _finite(value),
            "flipper_wallet_share": _finite(evidence.get("flipper_wallet_share")),
            "unique_buy_wallet_count": evidence.get("unique_buy_wallet_count"),
            "flipper_wallet_count": evidence.get("flipper_wallet_count"),
        }

    if errors:
        raise ValueError(
            "fresh churn snapshot integrity failed: " + ";".join(errors[:20])
        )

    return mapping, {
        "complete_episode_count": len(mapping),
        "status_counts": status_counts,
        "feature_snapshot_frozen_before_provider_quotes": True,
        "snapshot_churn_evidence_integrity": True,
    }



def _fresh_episode_sources_base_compatible(
    *,
    run_dir: Path,
    contract_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reconstruct fresh participant-quality inputs without requiring Sniper snapshot enrichment.

    The frozen historical Participant Quality runs were captured with Sniper V1 runtime
    enrichment. The prospective churn fresh run intentionally was not. For the fresh run,
    validate exact parity for the base fields that were actually stored, then reconstruct
    wallet identity causally from the same processed Carbon rows inside T0..T0+5. This does
    not alter the stored snapshot, churn feature, route outcome, or frozen PQ history.
    """

    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    processed_root = run_dir / "processed-chunks"
    for path in (route_input_path, route_result_path):
        if not path.is_file():
            raise ValueError(f"required fresh participant-quality source missing: {path}")
    if not processed_root.is_dir():
        raise ValueError(f"fresh processed-chunks directory missing: {processed_root}")

    route_input = read_json(route_input_path)
    route_result = read_json(route_result_path)
    if route_input.get("contract_hash_sha256") != contract_hash:
        raise ValueError(f"fresh route input contract mismatch: {run_dir}")
    if route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError(f"fresh route result contract mismatch: {run_dir}")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError(
            f"fresh feature snapshots were not frozen before provider quotes: {run_dir}"
        )

    state, processed_chunk_count = _reconstruct_state(processed_root)
    decisions = {
        str(row.get("episode_key") or ""): row
        for row in route_result.get("decisions") or []
        if isinstance(row, dict) and str(row.get("episode_key") or "")
    }

    output: list[dict[str, Any]] = []
    parity_errors: list[str] = []
    complete_count = 0
    base_snapshot_count = 0
    sniper_snapshot_count = 0

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

        replay = feature_snapshot_with_sniper_v1(
            rows,
            anchor_wall_ns=anchor_wall_ns,
        )
        stored = snapshot.get("features") or {}

        checks = {
            "event_count": replay.get("event_count") == stored.get("event_count"),
            "signed_flow_over_event_reserve": _same_number(
                replay.get("signed_flow_over_event_reserve"),
                stored.get("signed_flow_over_event_reserve"),
            ),
            "quote_asset_identity_count": replay.get("quote_asset_identity_count")
            == stored.get("quote_asset_identity_count"),
        }

        stored_is_sniper = (
            stored.get("sniper_feature_enrichment_version") is not None
        )
        if stored_is_sniper:
            sniper_snapshot_count += 1
            checks.update(
                {
                    "directional_flow_efficiency": _same_number(
                        replay.get("directional_flow_efficiency"),
                        stored.get("directional_flow_efficiency"),
                    ),
                    "unique_buy_wallet_count": replay.get(
                        "unique_buy_wallet_count"
                    )
                    == stored.get("unique_buy_wallet_count"),
                }
            )
        else:
            base_snapshot_count += 1
            # If an enrichment-only field was persisted, it must still match.
            if "directional_flow_efficiency" in stored:
                checks["directional_flow_efficiency"] = _same_number(
                    replay.get("directional_flow_efficiency"),
                    stored.get("directional_flow_efficiency"),
                )
            if "unique_buy_wallet_count" in stored:
                checks["unique_buy_wallet_count"] = (
                    replay.get("unique_buy_wallet_count")
                    == stored.get("unique_buy_wallet_count")
                )

        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            parity_errors.append(
                f"fresh_feature_parity:{episode_key}:{','.join(failed)}"
            )
            continue

        quote_asset = _causal_quote_asset_summary(rows)
        acceleration = acceleration_features_v1(
            rows,
            anchor_wall_ns=anchor_wall_ns,
            cutoff_wall_ns=cutoff_wall_ns,
        )
        buy_rows = [item for item in rows if item.side == "buy"]
        buy_identity_complete = bool(buy_rows) and all(
            item.wallet_key is not None for item in buy_rows
        )
        buy_wallets = (
            tuple(
                sorted(
                    {
                        str(item.wallet_key)
                        for item in buy_rows
                        if item.wallet_key is not None
                    }
                )
            )
            if buy_identity_complete
            else tuple()
        )

        decision = decisions.get(episode_key) or {}
        status = str(decision.get("status") or "MISSING")
        route_usable = status == "ROUTE_CLOSED" or status.startswith(
            "UNROUTABLE_EXIT"
        )
        gross = (
            _finite(decision.get("gross_route_return_pct"))
            if status == "ROUTE_CLOSED"
            else None
        )
        net = (
            _finite(decision.get("net_route_return_pct"))
            if route_usable
            else None
        )

        exit_observed_at = None
        if status == "ROUTE_CLOSED":
            exit_quote = decision.get("exit_quote")
            if isinstance(exit_quote, dict):
                raw = exit_quote.get("observed_at")
                if (
                    isinstance(raw, int)
                    and not isinstance(raw, bool)
                    and raw >= 0
                ):
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
                "is_default_sol_quote": quote_asset.get(
                    "is_default_sol_quote"
                )
                is True,
                "buy_identity_complete": buy_identity_complete,
                "buy_wallet_count": (
                    len(buy_wallets) if buy_identity_complete else None
                ),
                "buy_wallets": buy_wallets,
                "mf_buy_event_rate_acceleration_per_s2": _finite(
                    acceleration.get(
                        "mf_buy_event_rate_acceleration_per_s2"
                    )
                ),
                "signed_flow_over_event_reserve": _finite(
                    stored.get("signed_flow_over_event_reserve")
                ),
            }
        )

    if parity_errors:
        raise ValueError(
            f"fresh causal participant reconstruction parity failed for {run_dir}: "
            + ";".join(parity_errors[:10])
        )

    return output, {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "processed_chunk_count": processed_chunk_count,
        "route_input_episode_count": len(route_input.get("episodes") or []),
        "complete_episode_count": complete_count,
        "reconstructed_complete_episode_count": len(output),
        "base_snapshot_count": base_snapshot_count,
        "sniper_enriched_snapshot_count": sniper_snapshot_count,
        "stored_snapshot_contract_respected": True,
        "base_feature_reconstruction_parity": True,
        "participant_wallet_identity_reconstructed_causally": True,
        "participant_wallet_identity_window": "T0..T0+5 inclusive",
        "participant_wallet_source": "processed Carbon pump_trade wallet field",
        "feature_snapshot_frozen_before_provider_quotes": True,
        "route_contract_hash_sha256": contract_hash,
    }


def _fresh_rows_with_controls(
    *,
    history_rows: list[dict[str, Any]],
    fresh_rows: list[dict[str, Any]],
    churn_map: Mapping[str, Mapping[str, Any]],
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
        episode_key = str(row.get("episode_key") or "")
        churn = churn_map.get(episode_key)
        if not isinstance(churn, Mapping):
            raise ValueError(f"fresh churn evidence missing for {episode_key}")
        participant = _history_feature(row, universe)
        output.append(
            {
                "run_id": row["run_id"],
                "episode_key": episode_key,
                "token_mint": row["token_mint"],
                "observed_t0": row["observed_t0"],
                "route_status": row["route_status"],
                FEATURE_ID: churn.get(FEATURE_ID),
                "churn_evidence_status": churn.get("status"),
                "flipper_wallet_share": churn.get("flipper_wallet_share"),
                "unique_buy_wallet_count": churn.get("unique_buy_wallet_count"),
                "flipper_wallet_count": churn.get("flipper_wallet_count"),
                PARTICIPANT_QUALITY_FEATURE_ID: participant[
                    PARTICIPANT_QUALITY_FEATURE_ID
                ],
                "participant_quality_history_coverage_pct": participant[
                    "history_coverage_pct"
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
) -> tuple[str, dict[str, bool | None]]:
    minimum = int(
        (protocol.get("fresh_confirmation") or {}).get(
            "minimum_primary_route_closed_pairs"
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
        "minimum_primary_pairs_met": int(primary.get("usable_pair_count") or 0)
        >= minimum,
        "primary_spearman_negative": rho is not None and rho < 0,
        "primary_without_best_negative": without_best is not None
        and without_best < 0,
        "leave_one_out_sign_consistency_gte_0_80": loo is not None
        and loo >= 0.80,
        "partial_spearman_negative": partial is not None and partial < 0,
        "higher_churn_half_median_gross_lower": (
            higher_median is not None
            and lower_median is not None
            and higher_median < lower_median
        ),
    }

    if not checks["minimum_primary_pairs_met"]:
        return "INSUFFICIENT_SAMPLE_NO_EXTENSION", checks

    keep_keys = (
        "primary_spearman_negative",
        "primary_without_best_negative",
        "leave_one_out_sign_consistency_gte_0_80",
        "partial_spearman_negative",
        "higher_churn_half_median_gross_lower",
    )
    if all(checks[key] is True for key in keep_keys):
        return "KEEP", checks
    return "NO_CONFIRMATION_CLOSE_OR_REVIEW", checks


def run_confirmation(
    *,
    prior_run_dirs: list[Path],
    fresh_run_dir: Path,
    parity_report_path: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    protocol = read_json(protocol_path)
    validate_protocol(protocol)
    contract = read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")

    expected_prior_ids = list(
        (protocol.get("instrumentation") or {}).get("parity_runs") or []
    )
    resolved_prior = [Path(path).resolve() for path in prior_run_dirs]
    supplied_prior_ids = [path.name for path in resolved_prior]
    if supplied_prior_ids != expected_prior_ids:
        raise ValueError("prior run set/order changed")
    if len(set(map(str, resolved_prior))) != len(resolved_prior):
        raise ValueError("prior run dirs are not unique")

    fresh = Path(fresh_run_dir).resolve()
    if fresh.name in set(expected_prior_ids):
        raise ValueError("fresh run identity matches a prior discovery/parity run")
    if fresh in resolved_prior:
        raise ValueError("fresh run path overlaps a prior run")

    prior_shas = [_route_input_sha256(path) for path in resolved_prior]
    if len(set(prior_shas)) != len(prior_shas):
        raise ValueError("prior route-input identities are not unique")
    fresh_sha = _route_input_sha256(fresh)
    if fresh_sha in set(prior_shas):
        raise ValueError("fresh route-input identity matches a prior run")

    fresh_live_attestation = _validate_fresh_wrapper(
        fresh_run_dir=fresh,
        protocol=protocol,
        parity_report_path=parity_report_path,
    )
    churn_map, churn_integrity = _load_fresh_churn_map(fresh)

    prior_rows_all: list[dict[str, Any]] = []
    prior_integrity: list[dict[str, Any]] = []
    for run_dir in resolved_prior:
        rows, integrity = _episode_sources(
            run_dir=run_dir,
            contract_hash=contract_hash,
        )
        prior_rows_all.extend(rows)
        prior_integrity.append(integrity)

    fresh_rows, fresh_route_integrity = _fresh_episode_sources_base_compatible(
        run_dir=fresh,
        contract_hash=contract_hash,
    )

    prior_max_wall_ns = max(
        (int(row.get("observed_t0_wall_ns") or 0) for row in prior_rows_all),
        default=0,
    )
    fresh_min_wall_ns = min(
        (int(row.get("observed_t0_wall_ns") or 0) for row in fresh_rows),
        default=0,
    )
    if prior_max_wall_ns <= 0 or fresh_min_wall_ns <= prior_max_wall_ns:
        raise ValueError(
            "fresh churn capture is not strictly after every frozen prior capture: "
            f"prior_max_wall_ns={prior_max_wall_ns} "
            f"fresh_min_wall_ns={fresh_min_wall_ns}"
        )

    expected_history_ids = list(
        (protocol.get("instrumentation") or {}).get(
            "participant_quality_history_runs"
        )
        or []
    )
    history_rows = [
        row
        for row in prior_rows_all
        if str(row.get("run_id") or "") in set(expected_history_ids)
    ]
    actual_history_ids = sorted({str(row.get("run_id") or "") for row in history_rows})
    if actual_history_ids != sorted(expected_history_ids):
        raise ValueError("Participant Quality history run set changed")

    analyzed = _fresh_rows_with_controls(
        history_rows=history_rows,
        fresh_rows=fresh_rows,
        churn_map=churn_map,
    )

    primary = _association(
        analyzed,
        outcome_key="current_route_closed_gross_return_pct",
    )
    secondary = _association(
        analyzed,
        outcome_key="current_route_closed_net_return_pct",
    )
    copyability = _association(
        analyzed,
        outcome_key="current_route_usable_fixed_return_pct",
    )
    incremental = _incremental(analyzed)
    decision, checks = _decision(
        protocol=protocol,
        primary=primary,
        incremental=incremental,
    )

    feature_available = [
        row for row in analyzed if _finite(row.get(FEATURE_ID)) is not None
    ]
    report = {
        "type": "early_buyer_churn_prospective_confirmation_report_v1",
        "classification": PASS,
        "decision": decision,
        "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
        "inference_role": "FRESH_PROSPECTIVE_SIGNAL_QUALITY_CONFIRMATION",
        "feature_id": FEATURE_ID,
        "population": {
            "fresh_baseline_default_sol_episode_count": len(analyzed),
            "fresh_feature_available_episode_count": len(feature_available),
            "fresh_feature_availability_pct": (
                100.0 * len(feature_available) / len(analyzed)
                if analyzed
                else None
            ),
            "fresh_primary_route_closed_feature_pairs": primary.get(
                "usable_pair_count"
            ),
            "minimum_primary_pairs": (
                protocol.get("fresh_confirmation") or {}
            ).get("minimum_primary_route_closed_pairs"),
        },
        "primary_signal_quality": primary,
        "secondary_route_closed_net": secondary,
        "incremental_vs_existing_evidence": incremental,
        "copyability_sensitive_reference": copyability,
        "decision_rule_checks": checks,
        "source_integrity": {
            "route_contract_hash_sha256": contract_hash,
            "prior_run_ids": expected_prior_ids,
            "prior_route_input_sha256s": prior_shas,
            "fresh_route_input_sha256": fresh_sha,
            "fresh_identity_differs_from_all_prior": fresh_sha not in set(prior_shas),
            "fresh_run_name_differs_from_all_prior": fresh.name not in set(
                expected_prior_ids
            ),
            "fresh_run_strictly_after_all_prior": fresh_min_wall_ns
            > prior_max_wall_ns,
            "prior_max_observed_t0_wall_ns": prior_max_wall_ns,
            "fresh_min_observed_t0_wall_ns": fresh_min_wall_ns,
            "participant_quality_history_run_ids": expected_history_ids,
            "participant_quality_history_run_set_unchanged": True,
            "all_prior_exact_reconstruction_parity": all(
                item.get("exact_reconstruction_parity") is True
                for item in prior_integrity
            ),
            "fresh_exact_reconstruction_parity": fresh_route_integrity.get(
                "exact_reconstruction_parity"
            )
            is True,
            "all_feature_snapshots_frozen_before_provider_quotes": all(
                item.get("feature_snapshot_frozen_before_provider_quotes")
                is True
                for item in [*prior_integrity, fresh_route_integrity]
            ),
            "fresh_churn_snapshot_integrity": churn_integrity,
            "fresh_live_attestation": fresh_live_attestation,
            "offline_prospective_parity_attestation": (
                fresh_live_attestation.get("parity")
            ),
            "retrospective_runs_counted_as_fresh": False,
            "threshold_search_performed": False,
            "feature_redefined": False,
        },
        "guardrails": protocol.get("guardrails"),
        "rows": analyzed,
        "interpretation": (
            "This evaluates exactly one new 900-second prospective capture using the "
            "frozen Early Buyer Churn feature computed in the T0..T0+5s snapshot before "
            "provider quotes. KEEP means the second Market-First evidence family survived "
            "its preregistered fresh signal-quality confirmation. It does not by itself "
            "create a TAKE/SKIP selector, claim landed fills, or establish autonomous alpha."
        ),
    }

    destination = Path(
        output_path
        or (fresh / "early-buyer-churn-prospective-v1.json")
    )
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
        "population": report.get("population"),
        "primary_signal_quality": report.get("primary_signal_quality"),
        "incremental_vs_existing_evidence": report.get(
            "incremental_vs_existing_evidence"
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
        description="Fresh prospective confirmation of Early Buyer Churn V1"
    )
    parser.add_argument("--prior-run-dir", type=Path, action="append", required=True)
    parser.add_argument("--fresh-run-dir", type=Path, required=True)
    parser.add_argument("--parity-report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_confirmation(
            prior_run_dirs=args.prior_run_dir,
            fresh_run_dir=args.fresh_run_dir,
            parity_report_path=args.parity_report,
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
