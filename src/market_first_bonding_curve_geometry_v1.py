from __future__ import annotations

import math
import struct
from typing import Any, Mapping, Sequence

from src.pump_bonding_stream import (
    PUMP_CREATE_EVENT_DISCRIMINATOR,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
    decode_pump_create_event_payload,
    decode_pump_trade_event_payload,
)


VERSION = "market_first_bonding_curve_geometry_v1"
WINDOW_NS = 5_000_000_000
LAMPORTS_PER_SOL = 1_000_000_000
SOL_QUOTE_MINT = "11111111111111111111111111111111"

# Mechanically declared probes for retrospective discovery only. They are not selector
# thresholds and must not be optimized on the discovery sample.
PROBE_LAMPORTS = {
    "0_01_sol": 10_000_000,
    "0_10_sol": 100_000_000,
    "0_50_sol": 500_000_000,
}

FEATURE_IDS = (
    "mf_curve_progress_pct",
    "mf_curve_real_token_fraction_of_initial_pct",
    "mf_curve_spot_price_multiplier_vs_initial",
    "mf_curve_real_token_to_virtual_token_ratio_at_cutoff",
    "mf_curve_virtual_sol_reserves_sol_at_cutoff",
    "mf_curve_real_sol_reserves_sol_at_cutoff",
    "mf_curve_buy_impact_0_01_sol_pct_curve_only",
    "mf_curve_buy_impact_0_10_sol_pct_curve_only",
    "mf_curve_buy_impact_0_50_sol_pct_curve_only",
    "mf_curve_real_token_capacity_ratio_0_10_sol",
)


def _skip_borsh_string(payload: bytes, offset: int, *, name: str) -> int:
    if offset + 4 > len(payload):
        raise ValueError(f"truncated CreateEvent {name} length")
    length = struct.unpack_from("<I", payload, offset)[0]
    end = offset + 4 + length
    if end > len(payload):
        raise ValueError(f"truncated CreateEvent {name}")
    return end


def decode_create_geometry_payload_v1(payload: bytes) -> dict[str, Any] | None:
    """Decode only event-native initial curve state from a Pump CreateEvent payload.

    Identity/timestamp semantics are delegated to the existing stable Pump decoder. Reserve
    fields are read from the public CreateEvent layout immediately after that identity prefix.
    """

    identity = decode_pump_create_event_payload(payload)
    if identity is None:
        return None
    if payload[:8] != PUMP_CREATE_EVENT_DISCRIMINATOR:
        return None

    offset = 8
    for name in ("name", "symbol", "uri"):
        offset = _skip_borsh_string(payload, offset, name=name)
    identity_bytes = 32 * 4 + 8
    if offset + identity_bytes + 8 * 4 > len(payload):
        raise ValueError("truncated Pump CreateEvent reserve state")
    offset += identity_bytes
    virtual_token_reserves = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    virtual_sol_reserves = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    real_token_reserves = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    token_total_supply = struct.unpack_from("<Q", payload, offset)[0]

    return {
        "mint": identity.mint,
        "timestamp": identity.timestamp,
        "virtual_token_reserves_raw": int(virtual_token_reserves),
        "virtual_sol_reserves_raw": int(virtual_sol_reserves),
        "real_token_reserves_raw": int(real_token_reserves),
        "token_total_supply_raw": int(token_total_supply),
    }


def decode_trade_geometry_payload_v1(payload: bytes) -> dict[str, Any] | None:
    """Decode the four post-trade bonding-curve reserves from a Pump TradeEvent payload."""

    identity = decode_pump_trade_event_payload(payload)
    if identity is None:
        return None
    if payload[:8] != PUMP_TRADE_EVENT_DISCRIMINATOR:
        return None

    # discriminator + mint + sol_amount + token_amount + is_buy + user + timestamp
    offset = 8 + 32 + 8 + 8 + 1 + 32 + 8
    if offset + 8 * 4 > len(payload):
        raise ValueError("truncated Pump TradeEvent curve geometry state")
    virtual_sol_reserves = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    virtual_token_reserves = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    real_sol_reserves = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    real_token_reserves = struct.unpack_from("<Q", payload, offset)[0]

    return {
        "mint": identity.mint,
        "timestamp": identity.timestamp,
        "side": "buy" if identity.is_buy else "sell",
        "virtual_sol_reserves_raw": int(virtual_sol_reserves),
        "virtual_token_reserves_raw": int(virtual_token_reserves),
        "real_sol_reserves_raw": int(real_sol_reserves),
        "real_token_reserves_raw": int(real_token_reserves),
    }


def _positive_int(row: Mapping[str, Any], name: str) -> int | None:
    value = row.get(name)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _nonnegative_int(row: Mapping[str, Any], name: str) -> int | None:
    value = row.get(name)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _curve_only_buy_impact_pct(
    *,
    virtual_sol_reserves: int,
    virtual_token_reserves: int,
    real_token_reserves: int,
    quote_in_lamports: int,
) -> tuple[float | None, float | None]:
    """Return fee-free constant-product impact and real-token capacity ratio.

    This deliberately does not emulate protocol/provider fees. It is a mechanical curve-shape
    diagnostic. If the unconstrained quote would exceed real tokens remaining, impact is marked
    unavailable rather than inventing capped-fill semantics; the capacity ratio remains available.
    """

    if min(virtual_sol_reserves, virtual_token_reserves, quote_in_lamports) <= 0:
        return None, None
    unconstrained_out = (
        quote_in_lamports * virtual_token_reserves
    ) // (virtual_sol_reserves + quote_in_lamports)
    if unconstrained_out <= 0:
        return None, None
    capacity_ratio = real_token_reserves / unconstrained_out
    if unconstrained_out > real_token_reserves:
        return None, float(capacity_ratio)

    spot_quote_per_token = virtual_sol_reserves / virtual_token_reserves
    average_quote_per_token = quote_in_lamports / unconstrained_out
    impact = 100.0 * (average_quote_per_token / spot_quote_per_token - 1.0)
    if not math.isfinite(impact):
        return None, float(capacity_ratio)
    return float(impact), float(capacity_ratio)


def geometry_features_v1(
    *,
    initial_state: Mapping[str, Any],
    cutoff_state: Mapping[str, Any],
    quote_mint: str | None,
) -> dict[str, Any]:
    missing = {feature_id: None for feature_id in FEATURE_IDS}
    if quote_mint != SOL_QUOTE_MINT:
        return {
            "status": "OUT_OF_SCOPE_NON_SOL_QUOTE",
            "quote_mint": quote_mint,
            "features": missing,
            "probe_capacity_bound": {},
        }

    initial_virtual_token = _positive_int(initial_state, "virtual_token_reserves_raw")
    initial_virtual_sol = _positive_int(initial_state, "virtual_sol_reserves_raw")
    initial_real_token = _positive_int(initial_state, "real_token_reserves_raw")
    cutoff_virtual_token = _positive_int(cutoff_state, "virtual_token_reserves_raw")
    cutoff_virtual_sol = _positive_int(cutoff_state, "virtual_sol_reserves_raw")
    cutoff_real_token = _nonnegative_int(cutoff_state, "real_token_reserves_raw")
    cutoff_real_sol = _nonnegative_int(cutoff_state, "real_sol_reserves_raw")
    if None in (
        initial_virtual_token,
        initial_virtual_sol,
        initial_real_token,
        cutoff_virtual_token,
        cutoff_virtual_sol,
        cutoff_real_token,
        cutoff_real_sol,
    ):
        return {
            "status": "INSUFFICIENT_EVIDENCE_CURVE_STATE_MISSING",
            "quote_mint": quote_mint,
            "features": missing,
            "probe_capacity_bound": {},
        }

    assert initial_virtual_token is not None
    assert initial_virtual_sol is not None
    assert initial_real_token is not None
    assert cutoff_virtual_token is not None
    assert cutoff_virtual_sol is not None
    assert cutoff_real_token is not None
    assert cutoff_real_sol is not None

    if cutoff_real_token > initial_real_token:
        return {
            "status": "INSUFFICIENT_EVIDENCE_REAL_TOKEN_RESERVE_REGRESSION",
            "quote_mint": quote_mint,
            "features": missing,
            "probe_capacity_bound": {},
        }

    progress_pct = 100.0 * (1.0 - cutoff_real_token / initial_real_token)
    real_fraction_pct = 100.0 * cutoff_real_token / initial_real_token
    spot_multiplier = (
        cutoff_virtual_sol * initial_virtual_token
    ) / (cutoff_virtual_token * initial_virtual_sol)
    real_to_virtual = cutoff_real_token / cutoff_virtual_token

    features: dict[str, float | None] = {
        "mf_curve_progress_pct": float(progress_pct),
        "mf_curve_real_token_fraction_of_initial_pct": float(real_fraction_pct),
        "mf_curve_spot_price_multiplier_vs_initial": float(spot_multiplier),
        "mf_curve_real_token_to_virtual_token_ratio_at_cutoff": float(real_to_virtual),
        "mf_curve_virtual_sol_reserves_sol_at_cutoff": cutoff_virtual_sol / LAMPORTS_PER_SOL,
        "mf_curve_real_sol_reserves_sol_at_cutoff": cutoff_real_sol / LAMPORTS_PER_SOL,
    }
    bound: dict[str, bool] = {}
    primary_capacity_ratio: float | None = None
    for label, amount in PROBE_LAMPORTS.items():
        impact, capacity_ratio = _curve_only_buy_impact_pct(
            virtual_sol_reserves=cutoff_virtual_sol,
            virtual_token_reserves=cutoff_virtual_token,
            real_token_reserves=cutoff_real_token,
            quote_in_lamports=amount,
        )
        feature_id = f"mf_curve_buy_impact_{label}_pct_curve_only"
        features[feature_id] = impact
        bound[label] = bool(capacity_ratio is not None and capacity_ratio < 1.0)
        if label == "0_10_sol":
            primary_capacity_ratio = capacity_ratio
    features["mf_curve_real_token_capacity_ratio_0_10_sol"] = primary_capacity_ratio

    return {
        "status": "AVAILABLE_CAUSAL_SOL_BONDING_CURVE_GEOMETRY",
        "quote_mint": quote_mint,
        "features": features,
        "probe_capacity_bound": bound,
    }


def feature_definitions_v1() -> dict[str, dict[str, str]]:
    return {
        "mf_curve_progress_pct": {
            "role": "curve_progress_candidate",
            "definition": "100 * (1 - cutoff real token reserves / CreateEvent initial real token reserves).",
        },
        "mf_curve_real_token_fraction_of_initial_pct": {
            "role": "remaining_real_inventory_candidate",
            "definition": "100 * cutoff real token reserves / initial real token reserves.",
        },
        "mf_curve_spot_price_multiplier_vs_initial": {
            "role": "price_displacement_candidate",
            "definition": "(cutoff virtual SOL / cutoff virtual token) divided by its CreateEvent initial value.",
        },
        "mf_curve_real_token_to_virtual_token_ratio_at_cutoff": {
            "role": "real_inventory_vs_virtual_depth_candidate",
            "definition": "cutoff real token reserves / cutoff virtual token reserves.",
        },
        "mf_curve_virtual_sol_reserves_sol_at_cutoff": {
            "role": "virtual_quote_depth_candidate",
            "definition": "cutoff virtual SOL reserves converted from lamports to SOL.",
        },
        "mf_curve_real_sol_reserves_sol_at_cutoff": {
            "role": "real_quote_inventory_candidate",
            "definition": "cutoff real SOL reserves converted from lamports to SOL.",
        },
        "mf_curve_buy_impact_0_01_sol_pct_curve_only": {
            "role": "curve_shape_sensitivity_probe",
            "definition": "fee-free constant-product average-fill impact for a fixed 0.01 SOL mechanical probe; unavailable if real-token capacity binds.",
        },
        "mf_curve_buy_impact_0_10_sol_pct_curve_only": {
            "role": "curve_shape_primary_mechanical_probe",
            "definition": "fee-free constant-product average-fill impact for a fixed 0.10 SOL mechanical probe; unavailable if real-token capacity binds.",
        },
        "mf_curve_buy_impact_0_50_sol_pct_curve_only": {
            "role": "curve_shape_sensitivity_probe",
            "definition": "fee-free constant-product average-fill impact for a fixed 0.50 SOL mechanical probe; unavailable if real-token capacity binds.",
        },
        "mf_curve_real_token_capacity_ratio_0_10_sol": {
            "role": "remaining_inventory_capacity_candidate",
            "definition": "real tokens remaining divided by unconstrained constant-product tokens-out for the fixed 0.10 SOL probe.",
        },
    }
