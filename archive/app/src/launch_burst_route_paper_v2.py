from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from src.causal_quotes import CausalQuoteObservation, select_first_causal_quote
from src.launch_burst_v0 import canonical_launch_venue, launch_stratum_for_venue

CONTRACT_SCHEMA_VERSION = "launch_burst_route_paper_contract_v2"
RUNNER_VERSION = "launch_burst_prospective_route_paper_v2"
SUPPORTED_STRATA = ("pump_launch", "pumpswap_liquidity_launch")
FROZEN_STATUS = "FROZEN"


@dataclass(frozen=True)
class RoutePaperDecision:
    token_mint: str
    stratum: str
    decision_as_of: int
    feature_snapshot_hash: str
    admitted: bool
    decision_reason: str
    entry_quote: CausalQuoteObservation | None
    exit_quote: CausalQuoteObservation | None
    status: str
    gross_route_return_pct: float | None
    net_route_return_pct: float | None
    route_paper_pnl_usd: float | None
    contract_hash_sha256: str
    scope: str = "ROUTE_PAPER_NOT_LANDED_FILL"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def contract_hash_sha256(contract: Mapping[str, Any]) -> str:
    return sha256_payload({k: v for k, v in dict(contract).items() if k != "contract_hash_sha256"})


def feature_snapshot_hash_sha256(snapshot: Mapping[str, Any]) -> str:
    return sha256_payload(dict(snapshot))


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported route-paper contract schema_version")
    if contract.get("status") != FROZEN_STATUS:
        raise ValueError("route-paper outcomes are blocked until contract status is FROZEN")
    if tuple(contract.get("strata") or ()) != SUPPORTED_STRATA:
        raise ValueError("contract must preserve Pump and PumpSwap as separate strata")
    active = tuple(contract.get("active_strata") or ())
    if not active or any(item not in SUPPORTED_STRATA for item in active):
        raise ValueError("active_strata must be a non-empty subset of supported strata")
    primary = contract.get("primary_evidence") or {}
    if primary.get("window_seconds") != 5 or primary.get("confirmation_window_seconds") is not None:
        raise ValueError("V2 requires frozen 5s primary evidence with no confirmation window")
    rule = contract.get("selection_rule") or {}
    if rule.get("mode") != "all_of" or not isinstance(rule.get("predicates"), list) or not rule["predicates"]:
        raise ValueError("frozen selection_rule requires non-empty all_of predicates")
    for index, predicate in enumerate(rule["predicates"]):
        if not isinstance(predicate, dict) or not str(predicate.get("feature") or "").strip():
            raise ValueError(f"selection predicate {index} is invalid")
        if predicate.get("op") not in {">", ">=", "<", "<=", "=="}:
            raise ValueError(f"selection predicate {index} op is invalid")
        _finite(predicate.get("value"), f"selection predicate {index} value")

    entry = contract.get("entry") or {}
    _nonnegative_int(entry.get("latency_seconds"), "entry.latency_seconds")
    _nonnegative_int(entry.get("max_quote_age_seconds"), "entry.max_quote_age_seconds")
    _nonnegative_int(entry.get("max_quote_wait_seconds"), "entry.max_quote_wait_seconds")
    if entry.get("require_assembled_transaction") is not True:
        raise ValueError("entry must require an assembled transaction")

    position = contract.get("position") or {}
    if _finite(position.get("notional_usd"), "position.notional_usd") <= 0:
        raise ValueError("position.notional_usd must be positive")

    route_quality = contract.get("route_quality") or {}
    if route_quality.get("require_provider_price_impact") is not True:
        raise ValueError("route quality must require provider price impact")
    if _finite(route_quality.get("max_provider_price_impact_pct_points"), "route_quality.max_provider_price_impact_pct_points") < 0:
        raise ValueError("max provider price impact cannot be negative")

    costs = contract.get("costs") or {}
    for name in ("entry_fee_bps", "exit_fee_bps", "entry_adverse_slippage_bps", "exit_adverse_slippage_bps"):
        value = _finite(costs.get(name), f"costs.{name}")
        if value < 0 or value > 10_000:
            raise ValueError(f"costs.{name} must be between 0 and 10000")

    exit_policy = contract.get("exit") or {}
    if exit_policy.get("policy") != "fixed_horizon_from_entry":
        raise ValueError("V2 supports only fixed_horizon_from_entry")
    _positive_int(exit_policy.get("horizon_seconds"), "exit.horizon_seconds")
    _nonnegative_int(exit_policy.get("max_quote_age_seconds"), "exit.max_quote_age_seconds")
    _nonnegative_int(exit_policy.get("max_quote_wait_seconds"), "exit.max_quote_wait_seconds")
    if exit_policy.get("evidence_mode") != "route_only_exact_entry_quantity":
        raise ValueError("V2 exit evidence must remain route_only_exact_entry_quantity")
    if exit_policy.get("require_assembled_transaction") is not False:
        raise ValueError("route-only exit must not require an assembled transaction")

    failure = contract.get("failure_policy") or {}
    if _finite(failure.get("entry_unavailable_return_pct"), "failure_policy.entry_unavailable_return_pct") > 0:
        raise ValueError("entry unavailable return cannot be positive")
    if _finite(failure.get("unexitable_return_pct"), "failure_policy.unexitable_return_pct") >= 0:
        raise ValueError("unexitable return must be negative")

    expected = str(contract.get("contract_hash_sha256") or "")
    if not expected or expected != contract_hash_sha256(contract):
        raise ValueError("route-paper contract hash mismatch; post-freeze mutation detected")


def _compare(value: float, op: str, threshold: float) -> bool:
    return {">": value > threshold, ">=": value >= threshold, "<": value < threshold, "<=": value <= threshold, "==": value == threshold}[op]


def selection_decision(snapshot: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[bool, str]:
    validate_contract(contract)
    if snapshot.get("stratum") not in contract["active_strata"]:
        return False, "STRATUM_HOLD"
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


def _route_quality_ok(quote: CausalQuoteObservation, contract: Mapping[str, Any]) -> tuple[bool, str]:
    impact = quote.provider_price_impact_pct_points
    if impact is None or not math.isfinite(float(impact)) or impact < 0:
        return False, "PRICE_IMPACT_UNAVAILABLE"
    if impact > float(contract["route_quality"]["max_provider_price_impact_pct_points"]):
        return False, "PRICE_IMPACT_EXCEEDS_LIMIT"
    return True, "OK"


def _snapshot_clocks(snapshot: Mapping[str, Any]) -> tuple[int, int, int]:
    observed_t0 = snapshot.get("observed_t0")
    decision_as_of = snapshot.get("decision_as_of")
    wall_ns = snapshot.get("observed_t0_wall_ns")
    cutoff_ns = snapshot.get("decision_cutoff_wall_ns")
    if isinstance(observed_t0, bool) or not isinstance(observed_t0, int) or observed_t0 < 0:
        raise ValueError("feature_snapshot.observed_t0 must be a non-negative integer")
    if isinstance(decision_as_of, bool) or not isinstance(decision_as_of, int) or decision_as_of != observed_t0 + 5:
        raise ValueError("feature snapshot decision_as_of must equal observed_t0 + 5s")
    if isinstance(wall_ns, bool) or not isinstance(wall_ns, int) or wall_ns <= 0:
        raise ValueError("feature_snapshot.observed_t0_wall_ns must be positive")
    if isinstance(cutoff_ns, bool) or not isinstance(cutoff_ns, int) or cutoff_ns != wall_ns + 5_000_000_000:
        raise ValueError("feature snapshot decision_cutoff_wall_ns must equal observed_t0_wall_ns + 5s")
    return observed_t0, decision_as_of, cutoff_ns


def evaluate_episode(*, token_mint: str, venue: str, feature_snapshot: Mapping[str, Any], quotes: Sequence[CausalQuoteObservation], contract: Mapping[str, Any]) -> RoutePaperDecision:
    validate_contract(contract)
    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    stratum = launch_stratum_for_venue(canonical_launch_venue(venue))
    if feature_snapshot.get("stratum") != stratum:
        raise ValueError("feature snapshot stratum does not match episode venue")
    _, decision_as_of, cutoff_ns = _snapshot_clocks(feature_snapshot)
    snapshot_hash = feature_snapshot_hash_sha256(feature_snapshot)
    admitted, reason = selection_decision(feature_snapshot, contract)
    contract_hash = str(contract["contract_hash_sha256"])
    if not admitted:
        return RoutePaperDecision(token_mint, stratum, decision_as_of, snapshot_hash, False, reason, None, None, reason, None, None, None, contract_hash)

    entry_policy = contract["entry"]
    entry_ready_ns = cutoff_ns + int(entry_policy["latency_seconds"]) * 1_000_000_000
    entry_ready = (entry_ready_ns + 999_999_999) // 1_000_000_000
    entry_sel = select_first_causal_quote(
        list(quotes), token_mint=token_mint, side="buy", ready_at=int(entry_ready),
        max_quote_age_seconds=int(entry_policy["max_quote_age_seconds"]),
        max_quote_wait_seconds=int(entry_policy["max_quote_wait_seconds"]), require_executable=True,
    )
    if entry_sel.quote is None:
        loss = float(contract["failure_policy"]["entry_unavailable_return_pct"])
        return RoutePaperDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, None, None, "ENTRY_UNAVAILABLE", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)
    entry = entry_sel.quote
    ok, why = _route_quality_ok(entry, contract)
    if not ok:
        loss = float(contract["failure_policy"]["entry_unavailable_return_pct"])
        return RoutePaperDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry, None, f"ENTRY_REJECTED:{why}", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)
    if not entry.output_amount_raw:
        raise ValueError("entry quote lacks output_amount_raw required for exact route sizing")

    exit_policy = contract["exit"]
    exit_ready = entry.observed_at + int(exit_policy["horizon_seconds"])
    exit_sel = select_first_causal_quote(
        list(quotes), token_mint=token_mint, side="sell", ready_at=exit_ready,
        max_quote_age_seconds=int(exit_policy["max_quote_age_seconds"]),
        max_quote_wait_seconds=int(exit_policy["max_quote_wait_seconds"]), require_executable=False,
    )
    if exit_sel.quote is None:
        loss = float(contract["failure_policy"]["unexitable_return_pct"])
        return RoutePaperDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry, None, "UNROUTABLE_EXIT", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)
    exit_quote = exit_sel.quote
    if exit_quote.executable:
        raise ValueError("V2 exit evidence must remain route-only/non-executable")
    if str(exit_quote.input_amount_raw or "") != str(entry.output_amount_raw):
        raise ValueError("exit route amount must exactly equal entry output amount")
    ok, why = _route_quality_ok(exit_quote, contract)
    if not ok:
        loss = float(contract["failure_policy"]["unexitable_return_pct"])
        return RoutePaperDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry, exit_quote, f"UNROUTABLE_EXIT:{why}", None, loss, float(contract["position"]["notional_usd"]) * loss / 100.0, contract_hash)

    costs = contract["costs"]
    entry_drag = (float(costs["entry_fee_bps"]) + float(costs["entry_adverse_slippage_bps"])) / 10_000.0
    exit_drag = (float(costs["exit_fee_bps"]) + float(costs["exit_adverse_slippage_bps"])) / 10_000.0
    gross = 100.0 * (exit_quote.price_usd / entry.price_usd - 1.0)
    net = 100.0 * ((exit_quote.price_usd * (1.0 - exit_drag)) / (entry.price_usd * (1.0 + entry_drag)) - 1.0)
    pnl = float(contract["position"]["notional_usd"]) * net / 100.0
    return RoutePaperDecision(token_mint, stratum, decision_as_of, snapshot_hash, True, reason, entry, exit_quote, "ROUTE_CLOSED", gross, net, pnl, contract_hash)


def decision_to_dict(decision: RoutePaperDecision) -> dict[str, Any]:
    return asdict(decision)
