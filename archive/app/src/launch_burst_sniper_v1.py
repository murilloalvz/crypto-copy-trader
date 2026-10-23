from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from src.opportunity_feature_matrix_v0 import (
    TRACK_MARKET_FIRST,
    assert_selector_features_eligible_v0,
)


SNIPER_VERSION = "launch_burst_sniper_v1"
EXPECTED_POLICY_SCHEMA = "launch_burst_sniper_policy_v1"
EXPECTED_POLICY_NAME = "SNIPER-HIGH-PRECISION-V1"
EXPECTED_ACTIVE_CHAIN_PROFILE = "solana:mainnet:pumpfun"
EXPECTED_ROUTE_CONTRACT_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
EXPECTED_POLICY_HASH = "60a480a90365eae8abfcb55787345b41573fc1d2632d17c344741e93e36f490a"
SUPPORTED_OPS = {">=", "<=", ">", "<", "=="}


@dataclass(frozen=True)
class SniperPredicateResultV1:
    feature: str
    op: str
    threshold: float
    observed: float | None
    available: bool
    passed: bool


@dataclass(frozen=True)
class LaunchBurstSniperDecisionV1:
    method_version: str
    policy_hash_sha256: str
    selector_name: str
    selected: bool
    status: str
    reasons: tuple[str, ...]
    predicates: tuple[SniperPredicateResultV1, ...]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def validate_sniper_policy_v1(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != EXPECTED_POLICY_SCHEMA:
        raise ValueError("unsupported Launch Burst sniper policy schema")
    if policy.get("status") != "PREREGISTERED_PROSPECTIVE":
        raise ValueError("Launch Burst sniper policy is not preregistered prospective")
    if policy.get("policy_name") != EXPECTED_POLICY_NAME:
        raise ValueError("Launch Burst sniper policy name changed")
    if policy.get("active_chain_profile") != EXPECTED_ACTIVE_CHAIN_PROFILE:
        raise ValueError("Launch Burst sniper active chain profile changed")
    if policy.get("route_contract_hash_sha256") != EXPECTED_ROUTE_CONTRACT_HASH:
        raise ValueError("Launch Burst sniper route contract hash mismatch")
    if int(policy.get("decision_window_seconds") or 0) != 5:
        raise ValueError("Launch Burst sniper decision window must remain 5 seconds")
    if int(policy.get("inherited_entry_latency_seconds") or -1) != 2:
        raise ValueError("Launch Burst sniper inherited entry latency must remain +2 seconds")

    expected_hash = str(policy.get("policy_hash_sha256") or "")
    if len(expected_hash) != 64:
        raise ValueError("Launch Burst sniper policy hash is missing/invalid")
    shadow = {key: value for key, value in dict(policy).items() if key != "policy_hash_sha256"}
    actual_hash = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("Launch Burst sniper policy hash mismatch")
    if expected_hash != EXPECTED_POLICY_HASH:
        raise ValueError("Launch Burst sniper frozen V1 policy hash changed")

    for selector_name in ("primary_selector", "diagnostic_selector"):
        selector = policy.get(selector_name)
        if not isinstance(selector, Mapping) or selector.get("mode") != "all_of":
            raise ValueError(f"{selector_name} must be an all_of selector")
        predicates = selector.get("predicates")
        if not isinstance(predicates, list) or not predicates:
            raise ValueError(f"{selector_name} must contain predicates")
        seen: set[str] = set()
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                raise ValueError(f"{selector_name} predicate must be an object")
            feature = str(predicate.get("feature") or "").strip()
            op = str(predicate.get("op") or "").strip()
            value = predicate.get("value")
            if not feature or feature in seen:
                raise ValueError(f"{selector_name} feature names must be unique and non-empty")
            seen.add(feature)
            if op not in SUPPORTED_OPS:
                raise ValueError(f"unsupported sniper predicate op: {op}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{selector_name}.{feature} threshold must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{selector_name}.{feature} threshold must be finite")

    primary = policy["primary_selector"]["predicates"]
    assert_selector_features_eligible_v0(
        (str(item["feature"]) for item in primary),
        selector_track=TRACK_MARKET_FIRST,
    )
    baseline_predicate = next(
        (
            item
            for item in primary
            if item.get("feature") == "signed_flow_over_event_reserve"
        ),
        None,
    )
    if baseline_predicate != {
        "feature": "signed_flow_over_event_reserve",
        "op": ">=",
        "value": 0.08,
    }:
        raise ValueError("primary sniper selector must preserve the frozen baseline >=0.08 predicate")


def load_sniper_policy_v1(path: Path) -> dict[str, Any]:
    policy = _read_json(path)
    validate_sniper_policy_v1(policy)
    return policy


def _numeric_feature(features: Mapping[str, Any], name: str) -> float | None:
    value = features.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _predicate_passes(observed: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return observed >= threshold
    if op == "<=":
        return observed <= threshold
    if op == ">":
        return observed > threshold
    if op == "<":
        return observed < threshold
    if op == "==":
        return observed == threshold
    raise ValueError(f"unsupported predicate op: {op}")


def evaluate_launch_burst_sniper_v1(
    *,
    snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
    selector_name: str = "primary_selector",
) -> LaunchBurstSniperDecisionV1:
    validate_sniper_policy_v1(policy)
    if selector_name not in {"primary_selector", "diagnostic_selector"}:
        raise ValueError("selector_name must be primary_selector or diagnostic_selector")

    policy_hash = str(policy["policy_hash_sha256"])
    structural_reasons: list[str] = []
    if snapshot.get("complete") is not True:
        structural_reasons.append("SNAPSHOT_INCOMPLETE")
    if snapshot.get("stratum") != "pump_launch":
        structural_reasons.append("UNSUPPORTED_STRATUM")
    if int(snapshot.get("evidence_window_seconds") or 0) != int(policy["decision_window_seconds"]):
        structural_reasons.append("DECISION_WINDOW_MISMATCH")
    features = snapshot.get("features")
    if not isinstance(features, Mapping):
        structural_reasons.append("FEATURES_MISSING")
        features = {}

    selector = policy[selector_name]
    predicate_results: list[SniperPredicateResultV1] = []
    missing_features: list[str] = []
    failed_features: list[str] = []
    for predicate in selector["predicates"]:
        feature = str(predicate["feature"])
        op = str(predicate["op"])
        threshold = float(predicate["value"])
        observed = _numeric_feature(features, feature)
        available = observed is not None
        passed = available and _predicate_passes(float(observed), op, threshold)
        predicate_results.append(
            SniperPredicateResultV1(
                feature=feature,
                op=op,
                threshold=threshold,
                observed=observed,
                available=available,
                passed=passed,
            )
        )
        if not available:
            missing_features.append(feature)
        elif not passed:
            failed_features.append(feature)

    reasons = list(structural_reasons)
    reasons.extend(f"MISSING:{name}" for name in missing_features)
    reasons.extend(f"FAILED:{name}" for name in failed_features)

    if structural_reasons or missing_features:
        status = "INSUFFICIENT_EVIDENCE"
        selected = False
    elif failed_features:
        status = "REJECTED"
        selected = False
    else:
        status = "SELECTED"
        selected = True

    return LaunchBurstSniperDecisionV1(
        method_version=SNIPER_VERSION,
        policy_hash_sha256=policy_hash,
        selector_name=selector_name,
        selected=selected,
        status=status,
        reasons=tuple(reasons),
        predicates=tuple(predicate_results),
    )


def sniper_decision_to_dict_v1(decision: LaunchBurstSniperDecisionV1) -> dict[str, Any]:
    return {
        "method_version": decision.method_version,
        "policy_hash_sha256": decision.policy_hash_sha256,
        "selector_name": decision.selector_name,
        "selected": decision.selected,
        "status": decision.status,
        "reasons": list(decision.reasons),
        "predicates": [
            {
                "feature": item.feature,
                "op": item.op,
                "threshold": item.threshold,
                "observed": item.observed,
                "available": item.available,
                "passed": item.passed,
            }
            for item in decision.predicates
        ],
    }
