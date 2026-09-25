from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.causal_quotes import (
    CausalQuoteObservation,
    select_first_causal_quote,
    validate_causal_quote,
)


VERSION = "post_transition_economic_collector_v0"
CONTRACT_SCHEMA_VERSION = "post_transition_economic_collector_contract_v0"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "post_transition_reacceleration_v0"
    / "economic_collector_contract_v0.frozen.json"
)

FIXED_60 = "FIXED_60"
FIXED_300 = "FIXED_300"
TP50 = "TP50"
TP100 = "TP100"
TP200 = "TP200"

DYNAMIC_POLICIES = (
    "DECELERATION_EXIT",
    "PROFIT_PROTECTION_EXIT",
    "HYBRID_HUMAN_EXIT",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def contract_hash_sha256(contract: Mapping[str, Any]) -> str:
    shadow = {
        key: value
        for key, value in dict(contract).items()
        if key != "contract_hash_sha256"
    }
    return hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()


def _finite_number(value: Any, name: str) -> float:
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


def load_and_validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("economic collector contract must be a JSON object")
    if payload.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported post-transition economic collector contract")
    if payload.get("status") != "FROZEN_IMPLEMENTATION_ONLY":
        raise ValueError("economic collector contract must remain implementation-only frozen")

    discovery = payload.get("discovery_contract") or {}
    entry = payload.get("entry") or {}
    position = payload.get("position") or {}
    quality = payload.get("route_quality") or {}
    costs = payload.get("costs") or {}
    outcomes = payload.get("standardized_outcomes") or {}
    fixed60 = outcomes.get("fixed_60") or {}
    fixed300 = outcomes.get("fixed_300") or {}
    market_path = payload.get("market_path") or {}
    tp = payload.get("take_profit_policies") or {}
    dynamic = payload.get("dynamic_exit_policies") or {}
    censoring = payload.get("censoring") or {}
    failure = payload.get("failure_semantics") or {}
    guardrails = payload.get("scientific_guardrails") or {}

    exact = {
        "decision_30s": discovery.get(
            "decision_delay_seconds_from_transition_observed"
        ) == 30,
        "selector_empty": discovery.get("selector_predicates") == [],
        "marker_not_selector": discovery.get(
            "structural_reacceleration_candidate_is_selector"
        ) is False,
        "entry_latency_2": entry.get("latency_seconds_after_decision") == 2,
        "entry_age_15": entry.get("max_quote_age_seconds") == 15,
        "entry_wait_5": entry.get("max_quote_wait_seconds") == 5,
        "entry_assembled": entry.get("require_assembled_transaction") is True,
        "notional_25": float(position.get("notional_usd") or -1) == 25.0,
        "impact_required": quality.get("require_provider_price_impact") is True,
        "impact_2": float(
            quality.get("max_provider_price_impact_pct_points") or -1
        ) == 2.0,
        "route_only_sell": quality.get("route_only_sell_required") is True,
        "exact_quantity": quality.get("exact_entry_quantity_required") is True,
        "entry_fee_20": costs.get("entry_fee_bps") == 20,
        "exit_fee_20": costs.get("exit_fee_bps") == 20,
        "entry_slippage_100": costs.get("entry_adverse_slippage_bps") == 100,
        "exit_slippage_100": costs.get("exit_adverse_slippage_bps") == 100,
        "fixed60_primary": fixed60.get("role") == "PRIMARY"
        and fixed60.get("horizon_seconds_from_entry") == 60,
        "fixed300_exploratory": fixed300.get("role") == "EXPLORATORY"
        and fixed300.get("horizon_seconds_from_entry") == 300,
        "fixed300_no_swap": fixed300.get(
            "cannot_replace_primary_based_on_results"
        ) is True,
        "mfe_not_exit": market_path.get("mfe_is_not_exit") is True,
        "no_interpolation": market_path.get(
            "missing_route_marks_are_not_interpolated"
        ) is True,
        "tp50": (tp.get(TP50) or {}).get("threshold_net_return_pct") == 50
        and (tp.get(TP50) or {}).get("status") == "ARMED",
        "tp100": (tp.get(TP100) or {}).get("threshold_net_return_pct") == 100
        and (tp.get(TP100) or {}).get("status") == "ARMED",
        "tp200": (tp.get(TP200) or {}).get("threshold_net_return_pct") == 200
        and (tp.get(TP200) or {}).get("status") == "ARMED",
        "dynamic_not_armed": all(
            (dynamic.get(name) or {}).get("status") == "NOT_ARMED"
            for name in DYNAMIC_POLICIES
        ),
        "retrospective_not_reused": dynamic.get(
            "retrospective_human_assisted_exit_v0_reused"
        ) is False,
        "horizon_unresolved": censoring.get("maximum_horizon_seconds") is None
        and censoring.get("policy_status")
        == "UNRESOLVED_BLOCKS_FRESH_DISCOVERY",
        "no_forced_exit": censoring.get("forced_time_exit") is False,
        "fresh_requires_horizon": censoring.get(
            "fresh_discovery_requires_prior_horizon_freeze"
        ) is True,
        "entry_missing": failure.get(
            "entry_unavailable_is_missing_not_zero_return"
        ) is True,
        "unexitable_minus_100": float(
            failure.get("unexitable_after_usable_entry_return_pct") or 0
        ) == -100.0,
        "not_reached": failure.get("threshold_not_reached_status")
        == "NOT_REACHED",
        "fresh_closed": guardrails.get("fresh_economic_outcomes_opened")
        is False,
        "fresh_not_authorized": guardrails.get(
            "fresh_economic_discovery_authorized"
        ) is False,
        "live_false": guardrails.get("live_money_authorized") is False,
        "fixed60_stays_primary": guardrails.get("fixed_60_remains_primary")
        is True,
        "fixed300_stays_exploratory": guardrails.get(
            "fixed_300_remains_exploratory"
        ) is True,
        "best_tp_forbidden": guardrails.get(
            "best_tp_per_trade_selection_forbidden"
        ) is True,
        "mfe_exit_forbidden": guardrails.get("mfe_as_exit_forbidden") is True,
        "no_retuning": guardrails.get("same_sample_retuning_allowed") is False,
    }
    failed = sorted(name for name, ok in exact.items() if not ok)
    if failed:
        raise ValueError(
            "frozen economic collector contract mismatch: " + ",".join(failed)
        )

    expected = str(payload.get("contract_hash_sha256") or "")
    if not expected or expected != contract_hash_sha256(payload):
        raise ValueError("economic collector contract hash mismatch")
    return payload


def assert_fresh_discovery_blocked(contract: Mapping[str, Any]) -> None:
    censoring = contract.get("censoring") or {}
    guardrails = contract.get("scientific_guardrails") or {}
    if censoring.get("maximum_horizon_seconds") is None:
        raise RuntimeError(
            "fresh economic discovery blocked: maximum horizon/censoring "
            "policy must be frozen before opening outcomes"
        )
    if guardrails.get("fresh_economic_discovery_authorized") is not True:
        raise RuntimeError(
            "fresh economic discovery blocked: explicit authorization absent"
        )


@dataclass(frozen=True)
class EntryEvaluation:
    status: str
    reason: str
    ready_at: int
    deadline_at: int
    quote: CausalQuoteObservation | None
    included_in_conditional_economics: bool = False


@dataclass(frozen=True)
class RouteMark:
    observed_at: int
    market_time: int
    offset_seconds: int
    resolution_seconds: int
    routeable: bool
    reason: str
    provider_price_impact_pct_points: float | None
    liquidity_usd: float | None
    gross_return_pct: float | None
    net_return_pct: float | None


def _route_quality_ok(
    quote: CausalQuoteObservation,
    contract: Mapping[str, Any],
) -> tuple[bool, str]:
    impact = quote.provider_price_impact_pct_points
    if impact is None or not math.isfinite(float(impact)) or float(impact) < 0:
        return False, "PRICE_IMPACT_UNAVAILABLE"
    if float(impact) > float(
        contract["route_quality"]["max_provider_price_impact_pct_points"]
    ):
        return False, "PRICE_IMPACT_EXCEEDS_LIMIT"
    return True, "OK"


def _entry_ready_at(decision_as_of: int, contract: Mapping[str, Any]) -> int:
    return int(decision_as_of) + int(
        contract["entry"]["latency_seconds_after_decision"]
    )


def evaluate_entry(
    *,
    token_mint: str,
    decision_as_of: int,
    quotes: Sequence[CausalQuoteObservation],
    contract: Mapping[str, Any],
) -> EntryEvaluation:
    ready_at = _entry_ready_at(decision_as_of, contract)
    deadline_at = ready_at + int(contract["entry"]["max_quote_wait_seconds"])
    selection = select_first_causal_quote(
        list(quotes),
        token_mint=token_mint,
        side="buy",
        ready_at=ready_at,
        max_quote_age_seconds=int(contract["entry"]["max_quote_age_seconds"]),
        max_quote_wait_seconds=int(contract["entry"]["max_quote_wait_seconds"]),
        require_executable=True,
    )
    if selection.quote is None:
        return EntryEvaluation(
            status="ENTRY_UNAVAILABLE",
            reason=str(selection.reason or "NO_ELIGIBLE_ENTRY_QUOTE"),
            ready_at=ready_at,
            deadline_at=deadline_at,
            quote=None,
        )

    quote = selection.quote
    ok, why = _route_quality_ok(quote, contract)
    if not ok:
        return EntryEvaluation(
            status=f"ENTRY_REJECTED:{why}",
            reason=why,
            ready_at=ready_at,
            deadline_at=deadline_at,
            quote=quote,
        )
    if not quote.executable:
        return EntryEvaluation(
            status="ENTRY_REJECTED:ASSEMBLED_TRANSACTION_REQUIRED",
            reason="ASSEMBLED_TRANSACTION_REQUIRED",
            ready_at=ready_at,
            deadline_at=deadline_at,
            quote=quote,
        )
    if not str(quote.output_amount_raw or "").strip():
        return EntryEvaluation(
            status="ENTRY_REJECTED:MISSING_EXACT_OUTPUT_QUANTITY",
            reason="MISSING_EXACT_OUTPUT_QUANTITY",
            ready_at=ready_at,
            deadline_at=deadline_at,
            quote=quote,
        )
    return EntryEvaluation(
        status="ENTRY_USABLE",
        reason="OK",
        ready_at=ready_at,
        deadline_at=deadline_at,
        quote=quote,
        included_in_conditional_economics=True,
    )


def _net_returns(
    entry: CausalQuoteObservation,
    exit_quote: CausalQuoteObservation,
    contract: Mapping[str, Any],
) -> tuple[float, float]:
    costs = contract["costs"]
    entry_drag = (
        float(costs["entry_fee_bps"])
        + float(costs["entry_adverse_slippage_bps"])
    ) / 10_000.0
    exit_drag = (
        float(costs["exit_fee_bps"])
        + float(costs["exit_adverse_slippage_bps"])
    ) / 10_000.0
    gross = 100.0 * (exit_quote.price_usd / entry.price_usd - 1.0)
    net = 100.0 * (
        (exit_quote.price_usd * (1.0 - exit_drag))
        / (entry.price_usd * (1.0 + entry_drag))
        - 1.0
    )
    return gross, net


def classify_route_mark(
    *,
    entry: CausalQuoteObservation,
    quote: CausalQuoteObservation,
    contract: Mapping[str, Any],
) -> RouteMark:
    validate_causal_quote(quote)
    offset = int(quote.observed_at) - int(entry.observed_at)
    base = {
        "observed_at": int(quote.observed_at),
        "market_time": int(quote.market_time),
        "offset_seconds": offset,
        "resolution_seconds": int(quote.resolution_seconds),
        "provider_price_impact_pct_points": (
            float(quote.provider_price_impact_pct_points)
            if quote.provider_price_impact_pct_points is not None
            else None
        ),
        "liquidity_usd": (
            float(quote.liquidity_usd)
            if quote.liquidity_usd is not None
            else None
        ),
    }
    if quote.token_mint != entry.token_mint or quote.side != "sell":
        return RouteMark(**base, routeable=False, reason="WRONG_ROUTE_IDENTITY",
                         gross_return_pct=None, net_return_pct=None)
    if offset < 0:
        return RouteMark(**base, routeable=False, reason="BEFORE_ENTRY",
                         gross_return_pct=None, net_return_pct=None)
    if quote.executable:
        return RouteMark(**base, routeable=False, reason="SELL_NOT_ROUTE_ONLY",
                         gross_return_pct=None, net_return_pct=None)
    if str(quote.input_amount_raw or "") != str(entry.output_amount_raw or ""):
        return RouteMark(**base, routeable=False, reason="EXACT_QUANTITY_MISMATCH",
                         gross_return_pct=None, net_return_pct=None)
    age = int(quote.observed_at) - int(quote.market_time)
    if age > int(contract["entry"]["max_quote_age_seconds"]):
        return RouteMark(**base, routeable=False, reason="STALE_QUOTE",
                         gross_return_pct=None, net_return_pct=None)
    ok, why = _route_quality_ok(quote, contract)
    if not ok:
        return RouteMark(**base, routeable=False, reason=why,
                         gross_return_pct=None, net_return_pct=None)
    gross, net = _net_returns(entry, quote, contract)
    return RouteMark(
        **base,
        routeable=True,
        reason="OK",
        gross_return_pct=gross,
        net_return_pct=net,
    )


def build_market_path(
    *,
    entry: CausalQuoteObservation,
    quotes: Sequence[CausalQuoteObservation],
    contract: Mapping[str, Any],
    maximum_horizon_seconds: int | None = None,
) -> list[RouteMark]:
    marks: list[RouteMark] = []
    for quote in sorted(
        quotes,
        key=lambda item: (
            item.observed_at,
            item.market_time,
            item.side,
            item.route_id or "",
        ),
    ):
        if quote.token_mint != entry.token_mint or quote.side != "sell":
            continue
        mark = classify_route_mark(entry=entry, quote=quote, contract=contract)
        if mark.offset_seconds < 0:
            continue
        if (
            maximum_horizon_seconds is not None
            and mark.offset_seconds > int(maximum_horizon_seconds)
        ):
            continue
        marks.append(mark)
    return marks


def market_path_metrics(
    marks: Sequence[RouteMark],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    valid = [mark for mark in marks if mark.routeable and mark.net_return_pct is not None]
    if valid:
        mfe = max(valid, key=lambda item: float(item.net_return_pct))
        mae = min(valid, key=lambda item: float(item.net_return_pct))
        last = valid[-1]
    else:
        mfe = mae = last = None

    metrics: dict[str, Any] = {
        "route_mark_count": len(marks),
        "routeable_mark_count": len(valid),
        "routeability_share_pct": (
            100.0 * len(valid) / len(marks) if marks else None
        ),
        "mfe_pct": (float(mfe.net_return_pct) if mfe else None),
        "mae_pct": (float(mae.net_return_pct) if mae else None),
        "time_to_mfe_seconds": (mfe.offset_seconds if mfe else None),
        "time_to_mae_seconds": (mae.offset_seconds if mae else None),
        "last_routeable_return_pct": (
            float(last.net_return_pct) if last else None
        ),
        "last_routeable_offset_seconds": (
            last.offset_seconds if last else None
        ),
        "mfe_is_simulated_exit": False,
        "missing_route_marks_interpolated": False,
    }

    for threshold in contract["market_path"]["above_thresholds_pct"]:
        key = f"time_above_+{int(threshold)}_pct_seconds"
        metrics[key] = sum(
            mark.resolution_seconds
            for mark in valid
            if float(mark.net_return_pct) >= float(threshold)
        )
    for threshold in contract["market_path"]["below_thresholds_pct"]:
        key = f"time_below_{int(threshold)}_pct_seconds"
        metrics[key] = sum(
            mark.resolution_seconds
            for mark in valid
            if float(mark.net_return_pct) <= float(threshold)
        )
    return metrics


def _first_valid_mark_at_or_after(
    marks: Sequence[RouteMark],
    *,
    ready_at_offset_seconds: int,
    max_wait_seconds: int,
) -> RouteMark | None:
    deadline = int(ready_at_offset_seconds) + int(max_wait_seconds)
    for mark in marks:
        if mark.offset_seconds < int(ready_at_offset_seconds):
            continue
        if mark.offset_seconds > deadline:
            break
        if mark.routeable:
            return mark
    return None


def evaluate_fixed_outcome(
    *,
    name: str,
    marks: Sequence[RouteMark],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if name not in {FIXED_60, FIXED_300}:
        raise ValueError("unsupported fixed outcome")
    key = "fixed_60" if name == FIXED_60 else "fixed_300"
    policy = contract["standardized_outcomes"][key]
    horizon = int(policy["horizon_seconds_from_entry"])
    mark = _first_valid_mark_at_or_after(
        marks,
        ready_at_offset_seconds=horizon,
        max_wait_seconds=int(policy["max_quote_wait_seconds"]),
    )
    if mark is None:
        return {
            "policy": name,
            "role": policy["role"],
            "status": "UNROUTABLE_EXIT",
            "target_offset_seconds": horizon,
            "exit_observed_at": None,
            "gross_return_pct": None,
            "net_return_pct": float(
                contract["failure_semantics"][
                    "unexitable_after_usable_entry_return_pct"
                ]
            ),
            "contractual_unexitable_semantics_applied": True,
        }
    return {
        "policy": name,
        "role": policy["role"],
        "status": "ROUTE_CLOSED",
        "target_offset_seconds": horizon,
        "exit_observed_at": mark.observed_at,
        "actual_offset_seconds": mark.offset_seconds,
        "gross_return_pct": mark.gross_return_pct,
        "net_return_pct": mark.net_return_pct,
        "price_impact_at_exit": mark.provider_price_impact_pct_points,
        "routeable_at_exit": True,
        "contractual_unexitable_semantics_applied": False,
    }


def evaluate_take_profit(
    *,
    name: str,
    marks: Sequence[RouteMark],
    contract: Mapping[str, Any],
    maximum_horizon_seconds: int,
) -> dict[str, Any]:
    if name not in {TP50, TP100, TP200}:
        raise ValueError("unsupported take-profit policy")
    horizon = _positive_int(maximum_horizon_seconds, "maximum_horizon_seconds")
    threshold = float(
        contract["take_profit_policies"][name]["threshold_net_return_pct"]
    )
    for mark in marks:
        if mark.offset_seconds > horizon:
            break
        if (
            mark.routeable
            and mark.net_return_pct is not None
            and float(mark.net_return_pct) >= threshold
        ):
            return {
                "policy": name,
                "status": "THRESHOLD_REACHED",
                "threshold_reached": True,
                "threshold_net_return_pct": threshold,
                "time_to_threshold_seconds": mark.offset_seconds,
                "exit_observed_at": mark.observed_at,
                "routeable_at_crossing": True,
                "price_impact_at_crossing": (
                    mark.provider_price_impact_pct_points
                ),
                "gross_return_pct": mark.gross_return_pct,
                "fees_and_slippage_included_once": True,
                "net_return_if_exited_pct": mark.net_return_pct,
            }
    return {
        "policy": name,
        "status": contract["failure_semantics"]["threshold_not_reached_status"],
        "threshold_reached": False,
        "threshold_net_return_pct": threshold,
        "time_to_threshold_seconds": None,
        "exit_observed_at": None,
        "routeable_at_crossing": None,
        "price_impact_at_crossing": None,
        "gross_return_pct": None,
        "fees_and_slippage_included_once": True,
        "net_return_if_exited_pct": None,
    }


def dynamic_exit_status(contract: Mapping[str, Any]) -> dict[str, Any]:
    configured = contract["dynamic_exit_policies"]
    return {
        name: {
            "status": configured[name]["status"],
            "outcome": None,
            "reason": (
                "prospective thresholds not frozen; retrospective "
                "human_assisted_exit_v0 policy is intentionally isolated"
            ),
        }
        for name in DYNAMIC_POLICIES
    }


def collector_capabilities(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fixed_60": "ARMED",
        "fixed_300": "ARMED",
        "market_path": "ARMED",
        TP50: contract["take_profit_policies"][TP50]["status"],
        TP100: contract["take_profit_policies"][TP100]["status"],
        TP200: contract["take_profit_policies"][TP200]["status"],
        "DECELERATION_EXIT": contract["dynamic_exit_policies"][
            "DECELERATION_EXIT"
        ]["status"],
        "PROFIT_PROTECTION_EXIT": contract["dynamic_exit_policies"][
            "PROFIT_PROTECTION_EXIT"
        ]["status"],
        "HYBRID_HUMAN_EXIT": contract["dynamic_exit_policies"][
            "HYBRID_HUMAN_EXIT"
        ]["status"],
        "fresh_discovery": "BLOCKED_PENDING_CENSORING_HORIZON",
    }


def evaluate_episode(
    *,
    token_mint: str,
    decision_snapshot: Mapping[str, Any],
    quotes: Sequence[CausalQuoteObservation],
    contract: Mapping[str, Any],
    maximum_horizon_seconds: int,
) -> dict[str, Any]:
    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if decision_snapshot.get("structural_reacceleration_candidate") not in {
        True,
        False,
    }:
        raise ValueError("decision snapshot must expose structural marker")
    if (contract.get("discovery_contract") or {}).get("selector_predicates") != []:
        raise ValueError("post-transition collector requires empty selector predicates")

    decision_as_of = int(decision_snapshot["as_of_observed_at"])
    identity = decision_snapshot.get("identity") or {}
    if int(identity.get("transition_observed_at") or -1) + 30 != decision_as_of:
        raise ValueError("decision snapshot must remain transition+30s")
    if str(identity.get("opportunity_mint") or "") != token_mint:
        raise ValueError("decision snapshot token identity mismatch")

    entry = evaluate_entry(
        token_mint=token_mint,
        decision_as_of=decision_as_of,
        quotes=quotes,
        contract=contract,
    )
    if entry.quote is None or entry.status != "ENTRY_USABLE":
        return {
            "type": "post_transition_economic_collector_episode_v0",
            "version": VERSION,
            "token_mint": token_mint,
            "decision_as_of": decision_as_of,
            "entry": asdict(entry),
            "fixed_60": None,
            "fixed_300": None,
            TP50: None,
            TP100: None,
            TP200: None,
            "market_path": None,
            "dynamic_exits": dynamic_exit_status(contract),
            "included_in_conditional_economics": False,
            "fresh_economic_outcomes_opened": False,
        }

    marks = build_market_path(
        entry=entry.quote,
        quotes=quotes,
        contract=contract,
        maximum_horizon_seconds=maximum_horizon_seconds,
    )
    return {
        "type": "post_transition_economic_collector_episode_v0",
        "version": VERSION,
        "token_mint": token_mint,
        "decision_as_of": decision_as_of,
        "entry": asdict(entry),
        "fixed_60": evaluate_fixed_outcome(
            name=FIXED_60,
            marks=marks,
            contract=contract,
        ),
        "fixed_300": evaluate_fixed_outcome(
            name=FIXED_300,
            marks=marks,
            contract=contract,
        ),
        TP50: evaluate_take_profit(
            name=TP50,
            marks=marks,
            contract=contract,
            maximum_horizon_seconds=maximum_horizon_seconds,
        ),
        TP100: evaluate_take_profit(
            name=TP100,
            marks=marks,
            contract=contract,
            maximum_horizon_seconds=maximum_horizon_seconds,
        ),
        TP200: evaluate_take_profit(
            name=TP200,
            marks=marks,
            contract=contract,
            maximum_horizon_seconds=maximum_horizon_seconds,
        ),
        "market_path": {
            "metrics": market_path_metrics(marks, contract),
            "marks": [asdict(mark) for mark in marks],
        },
        "dynamic_exits": dynamic_exit_status(contract),
        "included_in_conditional_economics": True,
        "fresh_economic_outcomes_opened": False,
    }
