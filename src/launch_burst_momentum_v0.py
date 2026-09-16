from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


MOMENTUM_VERSION = "launch_burst_momentum_convergence_v0"
EXPECTED_POLICY_SCHEMA = "launch_burst_momentum_convergence_policy_v0"
EXPECTED_POLICY_NAME = "BURST-MOMENTUM-CONVERGENCE-V0"
EXPECTED_ACTIVE_CHAIN_PROFILE = "solana:mainnet:pumpfun"
EXPECTED_ROUTE_CONTRACT_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
EXPECTED_POLICY_HASH = "78eb1fdf44ec74821a4c7c61af3a9f4b429e46c7c44c18c2ffa71368d3cb0047"
SUPPORTED_OPS = {">=", "<=", ">", "<", "=="}


@dataclass(frozen=True)
class MomentumPredicateResultV0:
    feature: str
    op: str
    threshold: float
    observed: float | None
    available: bool
    passed: bool


@dataclass(frozen=True)
class MomentumDecisionV0:
    method_version: str
    policy_hash_sha256: str
    selector_name: str
    selected: bool
    status: str
    reasons: tuple[str, ...]
    predicates: tuple[MomentumPredicateResultV0, ...]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _validate_selector(selector: Mapping[str, Any], *, name: str) -> None:
    if selector.get("mode") != "all_of":
        raise ValueError(f"{name} must use all_of")
    predicates = selector.get("predicates")
    if not isinstance(predicates, list) or not predicates:
        raise ValueError(f"{name} must contain predicates")
    seen: set[str] = set()
    for predicate in predicates:
        if not isinstance(predicate, Mapping):
            raise ValueError(f"{name} predicate must be an object")
        feature = str(predicate.get("feature") or "").strip()
        op = str(predicate.get("op") or "").strip()
        value = predicate.get("value")
        if not feature or feature in seen:
            raise ValueError(f"{name} feature names must be unique and non-empty")
        seen.add(feature)
        if op not in SUPPORTED_OPS:
            raise ValueError(f"unsupported momentum predicate op: {op}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{name}.{feature} threshold must be finite numeric")


def validate_momentum_policy_v0(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != EXPECTED_POLICY_SCHEMA:
        raise ValueError("unsupported Burst momentum policy schema")
    if policy.get("status") != "PREREGISTERED_PROSPECTIVE_TRANSFER":
        raise ValueError("Burst momentum policy is not preregistered prospective transfer")
    if policy.get("policy_name") != EXPECTED_POLICY_NAME:
        raise ValueError("Burst momentum policy name changed")
    if policy.get("active_chain_profile") != EXPECTED_ACTIVE_CHAIN_PROFILE:
        raise ValueError("Burst momentum active chain profile changed")
    if policy.get("route_contract_hash_sha256") != EXPECTED_ROUTE_CONTRACT_HASH:
        raise ValueError("Burst momentum route contract hash mismatch")
    if int(policy.get("decision_window_seconds") or 0) != 5:
        raise ValueError("Burst momentum decision window must remain 5 seconds")
    if int(policy.get("inherited_entry_latency_seconds") or -1) != 2:
        raise ValueError("Burst momentum inherited entry latency must remain +2 seconds")

    expected_hash = str(policy.get("policy_hash_sha256") or "")
    shadow = {key: value for key, value in dict(policy).items() if key != "policy_hash_sha256"}
    actual_hash = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected_hash != actual_hash:
        raise ValueError("Burst momentum policy hash mismatch")
    if expected_hash != EXPECTED_POLICY_HASH:
        raise ValueError("Burst momentum frozen V0 policy hash changed")

    _validate_selector(policy.get("primary_selector") or {}, name="primary_selector")
    for name, selector in (policy.get("diagnostic_selectors") or {}).items():
        if not isinstance(selector, Mapping):
            raise ValueError(f"diagnostic selector {name} must be an object")
        _validate_selector(selector, name=f"diagnostic_selectors.{name}")

    primary = policy["primary_selector"]["predicates"]
    if primary != [
        {"feature": "signed_flow_over_event_reserve", "op": ">=", "value": 0.08},
        {"feature": "gross_flow_acceleration_second_half_over_first_half", "op": ">=", "value": 2.0},
    ]:
        raise ValueError("Burst momentum V0 primary selector differs from frozen transfer hypothesis")
    horizon = policy.get("momentum_horizon") or {}
    if int(horizon.get("historical_alignment_horizon_seconds") or 0) != 300:
        raise ValueError("Burst momentum historical-alignment horizon must remain +300s")


def load_momentum_policy_v0(path: Path) -> dict[str, Any]:
    policy = _read_json(path)
    validate_momentum_policy_v0(policy)
    return policy


def _numeric_feature(features: Mapping[str, Any], name: str) -> float | None:
    value = features.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _passes(observed: float, op: str, threshold: float) -> bool:
    if op == ">=": return observed >= threshold
    if op == "<=": return observed <= threshold
    if op == ">": return observed > threshold
    if op == "<": return observed < threshold
    if op == "==": return observed == threshold
    raise ValueError(f"unsupported predicate op: {op}")


def evaluate_momentum_v0(*, snapshot: Mapping[str, Any], policy: Mapping[str, Any], selector_name: str = "primary_selector") -> MomentumDecisionV0:
    validate_momentum_policy_v0(policy)
    if selector_name == "primary_selector":
        selector = policy["primary_selector"]
    else:
        selector = (policy.get("diagnostic_selectors") or {}).get(selector_name)
        if not isinstance(selector, Mapping):
            raise ValueError(f"unknown momentum selector: {selector_name}")

    structural: list[str] = []
    if snapshot.get("complete") is not True:
        structural.append("SNAPSHOT_INCOMPLETE")
    if snapshot.get("stratum") != "pump_launch":
        structural.append("UNSUPPORTED_STRATUM")
    if int(snapshot.get("evidence_window_seconds") or 0) != int(policy["decision_window_seconds"]):
        structural.append("DECISION_WINDOW_MISMATCH")
    features = snapshot.get("features")
    if not isinstance(features, Mapping):
        structural.append("FEATURES_MISSING")
        features = {}

    results: list[MomentumPredicateResultV0] = []
    missing: list[str] = []
    failed: list[str] = []
    for predicate in selector["predicates"]:
        feature = str(predicate["feature"])
        op = str(predicate["op"])
        threshold = float(predicate["value"])
        observed = _numeric_feature(features, feature)
        available = observed is not None
        passed = available and _passes(float(observed), op, threshold)
        results.append(MomentumPredicateResultV0(feature, op, threshold, observed, available, passed))
        if not available:
            missing.append(feature)
        elif not passed:
            failed.append(feature)

    reasons = structural + [f"MISSING:{x}" for x in missing] + [f"FAILED:{x}" for x in failed]
    if structural or missing:
        status, selected = "INSUFFICIENT_EVIDENCE", False
    elif failed:
        status, selected = "REJECTED", False
    else:
        status, selected = "SELECTED", True
    return MomentumDecisionV0(
        method_version=MOMENTUM_VERSION,
        policy_hash_sha256=str(policy["policy_hash_sha256"]),
        selector_name=selector_name,
        selected=selected,
        status=status,
        reasons=tuple(reasons),
        predicates=tuple(results),
    )


def momentum_decision_to_dict_v0(decision: MomentumDecisionV0) -> dict[str, Any]:
    return {
        "method_version": decision.method_version,
        "policy_hash_sha256": decision.policy_hash_sha256,
        "selector_name": decision.selector_name,
        "selected": decision.selected,
        "status": decision.status,
        "reasons": list(decision.reasons),
        "predicates": [
            {"feature": p.feature, "op": p.op, "threshold": p.threshold, "observed": p.observed, "available": p.available, "passed": p.passed}
            for p in decision.predicates
        ],
    }
