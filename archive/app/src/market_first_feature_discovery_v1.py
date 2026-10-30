from __future__ import annotations

from collections import defaultdict
import math
from typing import Any, Iterable, Mapping


VERSION = "market_first_feature_discovery_v1"
WINDOW_NS = 5_000_000_000
HALF_WINDOW_NS = WINDOW_NS // 2
HALF_WINDOW_SECONDS = HALF_WINDOW_NS / 1_000_000_000.0
HALF_CENTER_DISTANCE_SECONDS = HALF_WINDOW_SECONDS

FEATURE_IDS = (
    "mf_event_rate_acceleration_per_s2",
    "mf_buy_event_rate_acceleration_per_s2",
    "mf_unique_buy_wallet_arrival_acceleration_per_s2",
    "mf_signed_flow_acceleration_per_s2",
    "mf_directional_efficiency_delta_late_minus_early",
    "mf_top_wallet_gross_share_delta_pct_points_late_minus_early",
)


def _value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _wall_ns(row: Any) -> int | None:
    value = _value(row, "observed_wall_ns")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _side(row: Any) -> str | None:
    value = _value(row, "side")
    return value if value in {"buy", "sell"} else None


def _wallet(row: Any) -> str | None:
    value = _value(row, "wallet_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _signed_ratio(row: Any) -> float | None:
    amount = _finite_number(_value(row, "quote_amount_raw"))
    reserve = _finite_number(_value(row, "quote_reserve_raw"))
    side = _side(row)
    if amount is None or reserve is None or reserve <= 0 or amount < 0 or side is None:
        return None
    magnitude = amount / reserve
    return magnitude if side == "buy" else -magnitude


def _rate_acceleration(early_count: float, late_count: float) -> float:
    early_rate = early_count / HALF_WINDOW_SECONDS
    late_rate = late_count / HALF_WINDOW_SECONDS
    return (late_rate - early_rate) / HALF_CENTER_DISTANCE_SECONDS


def _directional_efficiency(rows: list[Any]) -> float | None:
    ratios = [_signed_ratio(row) for row in rows]
    if not rows or any(value is None for value in ratios):
        return None
    signed = sum(float(value) for value in ratios if value is not None)
    gross = sum(abs(float(value)) for value in ratios if value is not None)
    if gross <= 0:
        return None
    result = signed / gross
    return result if math.isfinite(result) else None


def _top_wallet_gross_share_pct(rows: list[Any]) -> float | None:
    if not rows or any(_wallet(row) is None for row in rows):
        return None
    wallet_gross: dict[str, float] = defaultdict(float)
    total = 0.0
    for row in rows:
        ratio = _signed_ratio(row)
        wallet = _wallet(row)
        if ratio is None or wallet is None:
            return None
        gross = abs(ratio)
        wallet_gross[wallet] += gross
        total += gross
    if total <= 0:
        return None
    return 100.0 * max(wallet_gross.values(), default=0.0) / total


def acceleration_features_v1(
    rows: Iterable[Any],
    *,
    anchor_wall_ns: int,
    cutoff_wall_ns: int,
) -> dict[str, float | None]:
    """Compute diagnostic-only acceleration features from the frozen causal 5s trade sequence.

    Temporal contract:
    - window is exactly [t0, t0 + 5s];
    - early half is [t0, t0 + 2.5s);
    - late half is [t0 + 2.5s, t0 + 5s];
    - observations outside the causal window are ignored;
    - no provider quote, execution result, published_at clock, or future outcome is consumed.

    These values are discovery diagnostics. They are intentionally not selector-ready and define
    no economic threshold.
    """

    if not isinstance(anchor_wall_ns, int) or isinstance(anchor_wall_ns, bool) or anchor_wall_ns <= 0:
        raise ValueError("anchor_wall_ns must be a positive integer")
    if cutoff_wall_ns - anchor_wall_ns != WINDOW_NS:
        raise ValueError("Market-First feature discovery v1 requires the frozen 5s causal window")

    split_wall_ns = anchor_wall_ns + HALF_WINDOW_NS
    ordered = sorted(
        (
            row
            for row in rows
            if (_wall_ns(row) is not None and anchor_wall_ns <= int(_wall_ns(row)) <= cutoff_wall_ns)
        ),
        key=lambda row: (int(_wall_ns(row) or 0), str(_value(row, "event_key") or "")),
    )
    if not ordered:
        return {feature_id: None for feature_id in FEATURE_IDS}

    early = [row for row in ordered if int(_wall_ns(row) or 0) < split_wall_ns]
    late = [row for row in ordered if int(_wall_ns(row) or 0) >= split_wall_ns]

    event_accel = _rate_acceleration(float(len(early)), float(len(late)))
    buy_accel = _rate_acceleration(
        float(sum(_side(row) == "buy" for row in early)),
        float(sum(_side(row) == "buy" for row in late)),
    )

    ratios_early = [_signed_ratio(row) for row in early]
    ratios_late = [_signed_ratio(row) for row in late]
    signed_flow_accel = None
    if not any(value is None for value in ratios_early + ratios_late):
        early_signed = sum(float(value) for value in ratios_early if value is not None)
        late_signed = sum(float(value) for value in ratios_late if value is not None)
        signed_flow_accel = _rate_acceleration(early_signed, late_signed)

    early_efficiency = _directional_efficiency(early)
    late_efficiency = _directional_efficiency(late)
    efficiency_delta = (
        late_efficiency - early_efficiency
        if early_efficiency is not None and late_efficiency is not None
        else None
    )

    wallet_complete = all(_wallet(row) is not None for row in ordered)
    unique_buy_wallet_accel = None
    concentration_delta = None
    if wallet_complete:
        first_buy_seen: dict[str, int] = {}
        for row in ordered:
            if _side(row) != "buy":
                continue
            wallet = _wallet(row)
            wall_ns = _wall_ns(row)
            if wallet is not None and wall_ns is not None and wallet not in first_buy_seen:
                first_buy_seen[wallet] = wall_ns
        early_new = sum(wall_ns < split_wall_ns for wall_ns in first_buy_seen.values())
        late_new = sum(wall_ns >= split_wall_ns for wall_ns in first_buy_seen.values())
        unique_buy_wallet_accel = _rate_acceleration(float(early_new), float(late_new))

        early_concentration = _top_wallet_gross_share_pct(early)
        late_concentration = _top_wallet_gross_share_pct(late)
        if early_concentration is not None and late_concentration is not None:
            concentration_delta = late_concentration - early_concentration

    return {
        "mf_event_rate_acceleration_per_s2": event_accel,
        "mf_buy_event_rate_acceleration_per_s2": buy_accel,
        "mf_unique_buy_wallet_arrival_acceleration_per_s2": unique_buy_wallet_accel,
        "mf_signed_flow_acceleration_per_s2": signed_flow_accel,
        "mf_directional_efficiency_delta_late_minus_early": efficiency_delta,
        "mf_top_wallet_gross_share_delta_pct_points_late_minus_early": concentration_delta,
    }


def feature_definitions_v1() -> dict[str, dict[str, object]]:
    common = {
        "track": "market_first",
        "causal_window_seconds": 5,
        "split_seconds": 2.5,
        "selector_eligible": False,
        "diagnostic_only": True,
        "future_dependent": False,
        "provider_execution_dependent": False,
        "threshold_defined": False,
    }
    return {
        "mf_event_rate_acceleration_per_s2": {
            **common,
            "description": "Late-half event rate minus early-half event rate, divided by the 2.5s half-center distance.",
            "missing_policy": "unavailable only when the frozen causal window contains no observed trade events",
        },
        "mf_buy_event_rate_acceleration_per_s2": {
            **common,
            "description": "Late-half BUY event rate minus early-half BUY event rate, divided by the 2.5s half-center distance.",
            "missing_policy": "unavailable only when the frozen causal window contains no observed trade events",
        },
        "mf_unique_buy_wallet_arrival_acceleration_per_s2": {
            **common,
            "description": "Acceleration in first-seen BUY-wallet arrival rate across the two causal half-windows.",
            "missing_policy": "fail closed when any frozen-window event lacks wallet identity",
        },
        "mf_signed_flow_acceleration_per_s2": {
            **common,
            "description": "Acceleration in signed flow normalized by each event reserve across the two causal half-windows.",
            "missing_policy": "fail closed when an event lacks a valid side, quote amount, or positive event reserve",
        },
        "mf_directional_efficiency_delta_late_minus_early": {
            **common,
            "description": "Late-half signed/gross directional efficiency minus early-half directional efficiency.",
            "missing_policy": "fail closed unless both half-windows contain valid non-zero gross flow",
        },
        "mf_top_wallet_gross_share_delta_pct_points_late_minus_early": {
            **common,
            "description": "Late-half top-wallet gross-flow share minus early-half share in percentage points.",
            "missing_policy": "fail closed unless wallet identity is complete and both half-windows have valid gross flow",
        },
    }


def liquidity_exitability_discovery_status_v1() -> dict[str, object]:
    return {
        "status": "BLOCKED_NO_RELIABLE_CAUSAL_EXITABILITY_FEATURE",
        "causal_fields_already_observed": [
            "quote_reserve_raw",
            "reserve_kind",
            "reserve_delta_fraction",
        ],
        "why_not_promoted": (
            "Existing reserve fields are causal market observations but do not by themselves define "
            "denomination-comparable executable depth or exitability. Provider route availability and "
            "price impact remain execution evidence and are forbidden as selector inputs."
        ),
        "required_next_evidence": (
            "A separately defined market-observable depth/liquidity state with explicit units and causal "
            "availability before provider quoting."
        ),
        "selector_eligible": False,
    }
