from __future__ import annotations

import json
from pathlib import Path
from typing import Any


VERSION = "post_transition_discovery_label_contract_v0"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "post_transition_reacceleration_v0"
    / "discovery_label_contract_v0.frozen.json"
)
EXPECTED_REFERENCE_ROUTE_HASH = (
    "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
)


def load_and_validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("contract must be a JSON object")
    if payload.get("schema_version") != VERSION:
        raise ValueError("unexpected discovery label contract version")
    if payload.get("status") != "FROZEN":
        raise ValueError("discovery label contract must remain FROZEN")

    cohort = payload.get("cohort") or {}
    selection = payload.get("selection") or {}
    entry = payload.get("entry") or {}
    position = payload.get("position") or {}
    quality = payload.get("route_quality") or {}
    costs = payload.get("costs") or {}
    labels = payload.get("labels") or {}
    primary = labels.get("primary") or {}
    exploratory = labels.get("exploratory") or {}
    guardrails = payload.get("scientific_guardrails") or {}
    reference = payload.get("frozen_reference_contract") or {}

    exact = {
        "requires_direct_pumpswap_create_event": cohort.get(
            "requires_direct_pumpswap_create_event"
        ) is True,
        "requires_prior_pump_birth": cohort.get(
            "requires_prior_pump_birth_causally_known"
        ) is True,
        "pump_birth_venue": cohort.get("pump_birth_venue") == "pump_bonding_curve",
        "decision_delay_30s": int(
            cohort.get("decision_delay_seconds_from_transition_observed") or -1
        ) == 30,
        "one_snapshot": cohort.get(
            "exactly_one_decision_snapshot_per_transition"
        ) is True,
        "minimum_trade_count_one": int(
            cohort.get("minimum_post_transition_trade_count_by_decision") or -1
        ) == 1,
        "no_selector_predicates": selection.get("selector_predicates") == [],
        "all_eligible_labeled": selection.get(
            "all_lineage_eligible_complete_decision_snapshots_receive_labels"
        ) is True,
        "marker_not_selector": selection.get(
            "structural_reacceleration_candidate_is_selector"
        ) is False,
        "threshold_search_forbidden": selection.get(
            "threshold_search_permitted"
        ) is False,
        "entry_latency_2s": int(
            entry.get("latency_seconds_after_decision") or -1
        ) == 2,
        "entry_wait_5s": int(entry.get("max_quote_wait_seconds") or -1) == 5,
        "entry_assembly_required": entry.get(
            "require_assembled_transaction"
        ) is True,
        "notional_25": float(position.get("notional_usd") or -1) == 25.0,
        "price_impact_2": float(
            quality.get("max_provider_price_impact_pct_points") or -1
        ) == 2.0,
        "entry_fee_20": int(costs.get("entry_fee_bps") or -1) == 20,
        "exit_fee_20": int(costs.get("exit_fee_bps") or -1) == 20,
        "entry_slippage_100": int(
            costs.get("entry_adverse_slippage_bps") or -1
        ) == 100,
        "exit_slippage_100": int(
            costs.get("exit_adverse_slippage_bps") or -1
        ) == 100,
        "primary_60": int(
            primary.get("horizon_seconds_from_entry") or -1
        ) == 60,
        "exploratory_300": int(
            exploratory.get("horizon_seconds_from_entry") or -1
        ) == 300,
        "exploratory_cannot_replace_primary": exploratory.get(
            "cannot_replace_primary_based_on_results"
        ) is True,
        "reference_route_hash": reference.get(
            "launch_burst_route_paper_v2_hash_sha256"
        ) == EXPECTED_REFERENCE_ROUTE_HASH,
        "features_before_provider": guardrails.get(
            "features_frozen_before_provider_calls"
        ) is True,
        "route_fields_not_features": guardrails.get(
            "provider_route_fields_forbidden_as_selector_features"
        ) is True,
        "no_same_sample_threshold": guardrails.get(
            "no_same_sample_threshold_sweep"
        ) is True,
        "discovery_no_edge_claim": guardrails.get(
            "discovery_cannot_claim_edge"
        ) is True,
        "live_money_false": guardrails.get("live_money_authorized") is False,
    }
    failed = sorted(key for key, value in exact.items() if not value)
    if failed:
        raise ValueError(
            "frozen discovery label contract mismatch: " + ",".join(failed)
        )
    return payload
