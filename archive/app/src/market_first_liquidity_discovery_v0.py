from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


VERSION = "market_first_liquidity_discovery_v0"
WINDOW_NS = 5_000_000_000

FEATURE_IDS = (
    "mf_pump_real_quote_reserve_raw_at_cutoff",
    "mf_pump_real_to_virtual_quote_reserve_ratio_at_cutoff",
    "mf_pump_real_quote_reserve_change_over_virtual_start",
)


def _value(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _text(row: Any, name: str) -> str | None:
    value = _value(row, name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_int(row: Any, name: str) -> int | None:
    value = _value(row, name)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _positive_int(row: Any, name: str) -> int | None:
    value = _nonnegative_int(row, name)
    return value if value is not None and value > 0 else None


def _wall_ns(row: Any) -> int | None:
    value = _value(row, "observed_wall_ns")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _missing() -> dict[str, float | int | None]:
    return {feature_id: None for feature_id in FEATURE_IDS}


def liquidity_features_v0(
    rows: Iterable[Any],
    *,
    anchor_wall_ns: int,
    cutoff_wall_ns: int,
) -> dict[str, Any]:
    """Derive diagnostic-only Pump reserve features from causal TradeEvent state.

    The feature side consumes only decoded market events observed inside the frozen 5s
    evidence window. Provider quotes, route availability, price impact, future outcomes,
    and published metadata are deliberately absent from this contract.

    `real_quote_reserves_raw` is an event-native reserve state in the quote asset's raw
    units. Absolute raw reserves are therefore comparable only within the same quote mint.
    The two ratio/change features are dimensionless.
    """

    if not isinstance(anchor_wall_ns, int) or isinstance(anchor_wall_ns, bool) or anchor_wall_ns <= 0:
        raise ValueError("anchor_wall_ns must be a positive integer")
    if cutoff_wall_ns - anchor_wall_ns != WINDOW_NS:
        raise ValueError("Market-First liquidity discovery v0 requires the frozen 5s causal window")

    ordered = sorted(
        (
            row
            for row in rows
            if (_wall_ns(row) is not None and anchor_wall_ns <= int(_wall_ns(row)) <= cutoff_wall_ns)
        ),
        key=lambda row: (int(_wall_ns(row) or 0), str(_value(row, "event_key") or "")),
    )
    if not ordered:
        return {
            "features": _missing(),
            "quote_mint": None,
            "status": "INSUFFICIENT_EVIDENCE_NO_CAUSAL_TRADE_ROWS",
        }

    quote_mints = {_text(row, "quote_mint") for row in ordered}
    if None in quote_mints or len(quote_mints) != 1:
        return {
            "features": _missing(),
            "quote_mint": None,
            "status": "INSUFFICIENT_EVIDENCE_QUOTE_MINT_CONFLICT_OR_MISSING",
        }
    quote_mint = next(iter(quote_mints))

    states: list[tuple[int, int]] = []
    for row in ordered:
        real = _nonnegative_int(row, "real_quote_reserves_raw")
        virtual = _positive_int(row, "virtual_quote_reserves_raw")
        if real is None or virtual is None:
            return {
                "features": _missing(),
                "quote_mint": quote_mint,
                "status": "INSUFFICIENT_EVIDENCE_RESERVE_STATE_MISSING",
            }
        states.append((real, virtual))

    first_real, first_virtual = states[0]
    last_real, last_virtual = states[-1]
    ratio = float(last_real) / float(last_virtual)
    change = float(last_real - first_real) / float(first_virtual)
    if not math.isfinite(ratio) or not math.isfinite(change):
        return {
            "features": _missing(),
            "quote_mint": quote_mint,
            "status": "INSUFFICIENT_EVIDENCE_NONFINITE_RESERVE_FEATURE",
        }

    return {
        "features": {
            "mf_pump_real_quote_reserve_raw_at_cutoff": last_real,
            "mf_pump_real_to_virtual_quote_reserve_ratio_at_cutoff": ratio,
            "mf_pump_real_quote_reserve_change_over_virtual_start": change,
        },
        "quote_mint": quote_mint,
        "status": "AVAILABLE_CAUSAL_MARKET_RESERVE_STATE",
    }


def feature_definitions_v0() -> dict[str, dict[str, object]]:
    common = {
        "track": "market_first",
        "causal_window_seconds": 5,
        "selector_eligible": False,
        "diagnostic_only": True,
        "execution_only": False,
        "future_dependent": False,
        "threshold_defined": False,
        "provider_quote_used": False,
    }
    return {
        "mf_pump_real_quote_reserve_raw_at_cutoff": {
            **common,
            "description": "Latest Pump TradeEvent real quote reserve causally observed by the frozen 5s cutoff, in raw quote-asset units.",
            "comparability": "within_exact_quote_mint_only",
            "missing_policy": "fail closed when quote identity or reserve state is missing/conflicting",
        },
        "mf_pump_real_to_virtual_quote_reserve_ratio_at_cutoff": {
            **common,
            "description": "Real quote reserve divided by virtual quote reserve at the latest causal Pump TradeEvent by cutoff.",
            "comparability": "dimensionless_cross_token_when_semantics_match",
            "missing_policy": "fail closed when quote identity or reserve state is missing/conflicting",
        },
        "mf_pump_real_quote_reserve_change_over_virtual_start": {
            **common,
            "description": "Change in real quote reserve from first to last causal Pump TradeEvent, normalized by the first virtual quote reserve.",
            "comparability": "dimensionless_cross_token_when_semantics_match",
            "missing_policy": "fail closed when quote identity or reserve state is missing/conflicting",
        },
    }
