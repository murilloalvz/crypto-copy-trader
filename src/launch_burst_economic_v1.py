from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from src.causal_quotes import CausalQuoteObservation, select_first_causal_quote
from src.launch_burst_v0 import canonical_launch_venue, launch_stratum_for_venue

CONTRACT_SCHEMA_VERSION = "launch_burst_economic_contract_v1"
RUNNER_VERSION = "launch_burst_prospective_economic_v1"
SUPPORTED_STRATA = ("pump_launch", "pumpswap_liquidity_launch")
FROZEN_STATUS = "FROZEN"
DRAFT_STATUS = "DRAFT_UNARMED"


@dataclass(frozen=True)
class LaunchBurstEconomicDecision:
    token_mint: str
    stratum: str
    decision_as_of: int
    feature_snapshot_hash: str
    admitted: bool
    decision_reason: str
    entry_quote: CausalQuoteObservation | None
    exit_quote: CausalQuoteObservation | None
    status: str
    gross_return_pct: float | None
    net_return_pct: float | None
    pnl_usd: float | None
    contract_hash_sha256: str


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _positive_number(value: Any, name: str) -> float:
    out = _finite_number(value, name)
    if out <= 0:
        raise ValueError(f"{name} must be positive")
    return out


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def contract_payload_for_hash(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(contract).items() if key != "contract_hash_sha256"}


def contract_hash_sha256(contract: Mapping[str, Any]) -> str:
    return sha256_payload(contract_payload_for_hash(contract))


def feature_snapshot_hash_sha256(snapshot: Mapping[str, Any]) -> str:
    return sha256_payload(dict(snapshot))


def _validate_selection_rule(rule: Mapping[str, Any], *, frozen: bool) -> None:
    if str(rule.get("mode") or "") != "all_of":
        raise ValueError("selection_rule.mode must be all_of")
    predicates = rule.get("predicates")
    if not isinstance(predicates, list):
        raise ValueError("selection_rule.predicates must be a list")
    if frozen and not predicates:
        raise ValueError("frozen contract requires at least one selection predicate")
    for index, item in enumerate(predicates):
        if not isinstance(item, dict):
            raise ValueError(f"selection predicate {index} must be an object")
        feature = str(item.get("feature") or "").strip()
        op = str(item.get("op") or "")
        if not feature:
            raise ValueError(f"selection predicate {index} feature cannot be empty")
        if op not in {">", ">=", "<", "<=", "=="}:
            raise ValueError(f"selection predicate {index} has unsupported op")
        _finite_number(item.get("value"), f"selection predicate {index} value")


def validate_contract(contract: Mapping[str, Any], *, require_frozen: bool = False) -> None:
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported economic contract schema_version")
    status = str(contract.get("status") or "")
    if status not in {DRAFT_STATUS, FROZEN_STATUS}:
        raise ValueError("contract status must be DRAFT_UNARMED or FROZEN")
    if require_frozen and status != FROZEN_STATUS:
        raise ValueError("economic outcomes are blocked until contract status is FROZEN")

    primary = contract.get("primary_evidence") or {}
    if int(primary.get("window_seconds") or 0) != 5:
        raise ValueError("primary evidence window must remain 5 seconds")
    if primary.get("confirmation_window_seconds") not in {None, 10}:
        raise ValueError("confirmation window must be null or 10 seconds")
    if tuple(contract.get("strata") or ()) != SUPPORTED_STRATA:
        raise ValueError("contract must preserve Pump and PumpSwap as separate ordered strata")

    selection_rule = contract.get("selection_rule")
    if not isinstance(selection_rule, dict):
        raise ValueError("selection_rule must be an object")
    _validate_selection_rule(selection_rule, frozen=status == FROZEN_STATUS)

    entry = contract.get("entry") or {}
    exit_policy = contract.get("exit") or {}
    costs = contract.get("costs") or {}
    position = contract.get("position") or {}
    failure = contract.get("failure_policy") or {}

    if status == FROZEN_STATUS:
        source_hash = str(contract.get("source_feature_report_sha256") or "")
        if len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash.lower()):
            raise ValueError("frozen contract requires source_feature_report_sha256 as 64 hex chars")
        _nonnegative_int(entry.get("latency_seconds"), "entry.latency_seconds")
        _nonnegative_int(entry.get("max_quote_age_seconds"), "entry.max_quote_age_seconds")
        _nonnegative_int(entry.get("max_quote_wait_seconds"), "entry.max_quote_wait_seconds")
        if entry.get("require_executable") is not True:
            raise ValueError("frozen entry policy must require executable quotes")
        if exit_policy.get("policy") != "fixed_horizon_from_entry":
            raise ValueError("V1 supports only fixed_horizon_from_entry exit policy")
        _positive_int(exit_policy.get("horizon_seconds"), "exit.horizon_seconds")
        _nonnegative_int(exit_policy.get("max_quote_age_seconds"), "exit.max_quote_age_seconds")
        _nonnegative_int(exit_policy.get("max_quote_wait_seconds"), "exit.max_quote_wait_seconds")
        if exit_policy.get("require_executable") is not True:
            raise ValueError("frozen exit policy must require executable quotes")

        for name in ("entry_fee_bps", "exit_fee_bps", "entry_adverse_slippage_bps", "exit_adverse_slippage_bps"):
            value = _finite_number(costs.get(name), f"costs.{name}")
            if value < 0 or value > 10_000:
                raise ValueError(f"costs.{name} must be between 0 and 10000")

        _positive_number(position.get("notional_usd"), "position.notional_usd")
        fraction = _positive_number(position.get("max_fraction_of_reported_liquidity"), "position.max_fraction_of_reported_liquidity")
        if fraction > 1:
            raise ValueError("position.max_fraction_of_reported_liquidity cannot exceed 1")
        if position.get("require_liquidity_observation") is not True:
            raise ValueError("frozen V1 requires a liquidity observation")
        impact = _finite_number(position.get("max_provider_price_impact_pct_points"), "position.max_provider_price_impact_pct_points")
        if impact < 0:
            raise ValueError("max provider price impact cannot be negative")

        if _finite_number(failure.get("unexitable_return_pct"), "failure_policy.unexitable_return_pct") >= 0:
            raise ValueError("unexitable_return_pct must be negative")
        if _finite_number(failure.get("entry_unavailable_return_pct"), "failure_policy.entry_unavailable_return_pct") > 0:
            raise ValueError("entry_unavailable_return_pct cannot be positive")

        expected_hash = str(contract.get("contract_hash_sha256") or "")
        if not expected_hash:
            raise ValueError("frozen contract requires contract_hash_sha256")
        if expected_hash != contract_hash_sha256(contract):
            raise ValueError("economic contract hash mismatch; post-freeze mutation detected")


def freeze_contract(draft: Mapping[str, Any]) -> dict[str, Any]:
    frozen = json.loads(json.dumps(dict(draft)))
    frozen["status"] = FROZEN_STATUS
    frozen.pop("contract_hash_sha256", None)
    shadow = dict(frozen)
    shadow["contract_hash_sha256"] = "pending"
    try:
        validate_contract(shadow)
    except ValueError as exc:
        if "hash mismatch" not in str(exc):
            raise
    frozen["contract_hash_sha256"] = contract_hash_sha256(frozen)
    validate_contract(frozen, require_frozen=True)
    return frozen


def _compare(value: float, op: str, threshold: float) -> bool:
    return {">": value > threshold, ">=": value >= threshold, "<": value < threshold, "<=": value <= threshold, "==": value == threshold}[op]


def selection_decision(snapshot: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[bool, str]:
    validate_contract(contract, require_frozen=True)
    if snapshot.get("complete") is not True:
        return False, "RIGHT_CENSORED"
    features = snapshot.get("features")
    if not isinstance(features, dict):
        return False, "MISSING_FEATURES"
    for predicate in contract["selection_rule"]["predicates"]:
        name = predicate["feature"]
        raw = features.get(name)
        if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            return False, f"FEATURE_UNAVAILABLE:{name}"
        if not _compare(float(raw), predicate["op"], float(predicate["value"])):
            return False, f"SELECTION_REJECT:{name}"
    return True, "SELECTION_ADMIT"


def _liquidity_ok(quote: CausalQuoteObservation, contract: Mapping[str, Any]) -> tuple[bool, str]:
    position = contract["position"]
    if quote.liquidity_usd is None or quote.liquidity_usd <= 0:
        return False, "LIQUIDITY_UNAVAILABLE"
    if float(position["notional_usd"]) / quote.liquidity_usd > float(position["max_fraction_of_reported_liquidity"]):
        return False, "POSITION_EXCEEDS_LIQUIDITY_FRACTION"
    impact = quote.provider_price_impact_pct_points
    if impact is None or impact < 0:
        return False, "PRICE_IMPACT_UNAVAILABLE"
    if impact > float(position["max_provider_price_impact_pct_points"]):
        return False, "PRICE_IMPACT_EXCEEDS_LIMIT"
    return True, "OK"


def evaluate_episode(*, token_mint: str, venue: str, feature_snapshot: Mapping[str, Any], quotes: Sequence[CausalQuoteObservation], contract: Mapping[str, Any]) -> LaunchBurstEconomicDecision:
    validate_contract(contract, require_frozen=True)
    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    canonical_venue = canonical_launch_venue(venue)
    stratum = launch_stratum_for_venue(canonical_venue)
    if stratum not in contract["strata"]:
        raise ValueError("launch stratum is not enabled by contract")

    observed_t0 = feature_snapshot.get("observed_t0")
    decision_as_of = feature_snapshot.get("decision_as_of")
    if isinstance(observed_t0, bool) or not isinstance(observed_t0, int) or observed_t0 < 0:
        raise ValueError("feature_snapshot.observed_t0 must be a non-negative integer")
    if isinstance(decision_as_of, bool) or not isinstance(decision_as_of, int) or decision_as_of < 0:
        raise ValueError("feature_snapshot.decision_as_of must be a non-negative integer")
    if feature_snapshot.get("evidence_window_seconds") != 5 or decision_as_of != observed_t0 + 5:
        raise ValueError("feature snapshot must be frozen exactly at observed_t0 + 5s")
    if feature_snapshot.get("stratum") != stratum:
        raise ValueError("feature snapshot stratum does not match episode venue")

    snapshot_hash = feature_snapshot_hash_sha256(feature_snapshot)
    admitted, reason = selection_decision(feature_snapshot, contract)
    contract_hash = str(contract["contract_hash_sha256"])
    if not admitted:
        return LaunchBurstEconomicDecision(token_mint, stratum, decision_as_of, snapshot_hash, False, reason, None, None, reason, None, None, None, contract_hash)

    entry_policy = contract["entry"]
    entry_ready = decision_as_of + int(entry_policy["latency_seconds"])
    entry_sel = select_first_causal_quote(list(quotes), token_mint=token_mint, side="buy", ready_at=entry_ready, max_quote_age_seconds=int(entry_policy["max_quote_age_seconds"]), max_quote_wait_seconds=int(entry_policy["max_quote_wait_seconds"]), require_executable=True)
    if entry_sel.quote is None:
        loss = float(contract["failure_policy"]["entry_unavailable_return_pct"])
        return LaunchBurstEconomicDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, None, None, "ENTRY_UNAVAILABLE", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)
    entry_quote = entry_sel.quote
    ok, failure_reason = _liquidity_ok(entry_quote, contract)
    if not ok:
        loss = float(contract["failure_policy"]["entry_unavailable_return_pct"])
        return LaunchBurstEconomicDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry_quote, None, f"ENTRY_REJECTED:{failure_reason}", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)

    exit_policy = contract["exit"]
    exit_ready = entry_quote.observed_at + int(exit_policy["horizon_seconds"])
    exit_sel = select_first_causal_quote(list(quotes), token_mint=token_mint, side="sell", ready_at=exit_ready, max_quote_age_seconds=int(exit_policy["max_quote_age_seconds"]), max_quote_wait_seconds=int(exit_policy["max_quote_wait_seconds"]), require_executable=True)
    if exit_sel.quote is None:
        loss = float(contract["failure_policy"]["unexitable_return_pct"])
        return LaunchBurstEconomicDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry_quote, None, "UNEXITABLE", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)
    exit_quote = exit_sel.quote
    ok, failure_reason = _liquidity_ok(exit_quote, contract)
    if not ok:
        loss = float(contract["failure_policy"]["unexitable_return_pct"])
        return LaunchBurstEconomicDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry_quote, exit_quote, f"UNEXITABLE:{failure_reason}", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)

    costs = contract["costs"]
    entry_drag = (float(costs["entry_fee_bps"]) + float(costs["entry_adverse_slippage_bps"])) / 10_000.0
    exit_drag = (float(costs["exit_fee_bps"]) + float(costs["exit_adverse_slippage_bps"])) / 10_000.0
    gross = 100.0 * (exit_quote.price_usd / entry_quote.price_usd - 1.0)
    net = 100.0 * ((exit_quote.price_usd * (1.0 - exit_drag)) / (entry_quote.price_usd * (1.0 + entry_drag)) - 1.0)
    pnl = float(contract["position"]["notional_usd"]) * net / 100.0
    return LaunchBurstEconomicDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry_quote, exit_quote, "CLOSED", gross, net, pnl, contract_hash)


def decision_to_dict(decision: LaunchBurstEconomicDecision) -> dict[str, Any]:
    return asdict(decision)
