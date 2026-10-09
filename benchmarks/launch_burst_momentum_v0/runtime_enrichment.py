from __future__ import annotations

from contextlib import contextmanager
import math
from typing import Any, Iterator

from benchmarks.launch_burst_prospective_route_paper_v2 import live as live_v2
from benchmarks.launch_burst_shadow_v0 import run as shadow
from benchmarks.launch_burst_sniper_v1.runtime_enrichment import (
    envelope_with_sniper_wallet_v1,
    feature_snapshot_with_sniper_v1,
)


ENRICHMENT_VERSION = "launch_burst_momentum_runtime_enrichment_v0"
HALF_WINDOW_NS = 2_500_000_000
FULL_WINDOW_NS = 5_000_000_000


def _ratio(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    value = num / den
    return value if math.isfinite(value) else None


def feature_snapshot_with_momentum_v0(rows, *, anchor_wall_ns: int) -> dict[str, Any]:
    base = feature_snapshot_with_sniper_v1(rows, anchor_wall_ns=anchor_wall_ns)
    first = []
    second = []
    for item in rows:
        delta = int(item.observed_wall_ns) - int(anchor_wall_ns)
        if delta < 0 or delta > FULL_WINDOW_NS:
            continue
        if delta < HALF_WINDOW_NS:
            first.append(item)
        else:
            second.append(item)

    first_signed = sum(shadow._ratio_signed(item) for item in first)
    second_signed = sum(shadow._ratio_signed(item) for item in second)
    first_gross = sum(abs(shadow._ratio_signed(item)) for item in first)
    second_gross = sum(abs(shadow._ratio_signed(item)) for item in second)
    first_buy = sum(shadow._ratio_signed(item) for item in first if item.side == "buy")
    second_buy = sum(shadow._ratio_signed(item) for item in second if item.side == "buy")

    late_efficiency = None
    if second_gross > 0:
        late_efficiency = second_signed / second_gross
        if not math.isfinite(late_efficiency):
            late_efficiency = None

    features = dict(base)
    features.update(
        {
            "momentum_feature_enrichment_version": ENRICHMENT_VERSION,
            "momentum_first_half_event_count": len(first),
            "momentum_second_half_event_count": len(second),
            "momentum_first_half_gross_flow_over_event_reserve": first_gross,
            "momentum_second_half_gross_flow_over_event_reserve": second_gross,
            "momentum_first_half_signed_flow_over_event_reserve": first_signed,
            "momentum_second_half_signed_flow_over_event_reserve": second_signed,
            "gross_flow_acceleration_second_half_over_first_half": _ratio(second_gross, first_gross),
            "event_rate_acceleration_second_half_over_first_half": _ratio(float(len(second)), float(len(first))),
            "buy_flow_acceleration_second_half_over_first_half": _ratio(second_buy, first_buy),
            "late_half_directional_flow_efficiency": late_efficiency,
            "momentum_first_half_has_evidence": bool(first),
            "momentum_second_half_has_evidence": bool(second),
        }
    )
    return features


@contextmanager
def patched_momentum_feature_enrichment_v0() -> Iterator[None]:
    original_envelope = live_v2._envelope
    original_feature_snapshot = live_v2._feature_snapshot
    live_v2._envelope = envelope_with_sniper_wallet_v1
    live_v2._feature_snapshot = feature_snapshot_with_momentum_v0
    try:
        yield
    finally:
        live_v2._envelope = original_envelope
        live_v2._feature_snapshot = original_feature_snapshot
