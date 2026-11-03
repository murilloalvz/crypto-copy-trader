from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import replace
import math
from typing import Any, Iterator

from benchmarks.launch_burst_prospective_route_paper_v2 import live as live_v2
from benchmarks.launch_burst_shadow_v0 import run as shadow


ENRICHMENT_VERSION = "launch_burst_sniper_runtime_enrichment_v1"


def _row_wallet(row: dict[str, Any]) -> str | None:
    # Current Carbon Pump trade canonical rows expose the signer as `wallet`.
    # The frozen shadow adapter predates that field and therefore reported 0%
    # wallet identity coverage for Pump launches. This is enrichment-only:
    # route selection continues to use the frozen signed-flow predicate.
    value = row.get("wallet")
    return value.strip() if isinstance(value, str) and value.strip() else None


def envelope_with_sniper_wallet_v1(result: Any, row: dict[str, Any], wall_ns: int):
    envelope = shadow._envelope(result, row, wall_ns)
    if envelope is None or envelope.wallet_key is not None:
        return envelope
    wallet = _row_wallet(row)
    return replace(envelope, wallet_key=wallet) if wallet is not None else envelope


def _pct(num: float, den: float) -> float | None:
    if den <= 0:
        return None
    value = 100.0 * num / den
    return value if math.isfinite(value) else None


def feature_snapshot_with_sniper_v1(rows, *, anchor_wall_ns: int) -> dict[str, Any]:
    base = shadow._feature_snapshot(rows, anchor_wall_ns=anchor_wall_ns)
    total = int(base.get("event_count") or 0)
    signed = base.get("signed_flow_over_event_reserve")
    gross = base.get("gross_turnover_over_event_reserve")

    directional_efficiency = None
    if isinstance(signed, (int, float)) and not isinstance(signed, bool) and isinstance(gross, (int, float)) and not isinstance(gross, bool):
        signed_f = float(signed)
        gross_f = float(gross)
        if math.isfinite(signed_f) and math.isfinite(gross_f) and gross_f > 0:
            directional_efficiency = signed_f / gross_f
            if not math.isfinite(directional_efficiency):
                directional_efficiency = None

    wallet_rows = [item for item in rows if item.wallet_key is not None]
    wallet_counts = Counter(str(item.wallet_key) for item in wallet_rows)
    unique_buy_wallets = {str(item.wallet_key) for item in wallet_rows if item.side == "buy"}
    unique_sell_wallets = {str(item.wallet_key) for item in wallet_rows if item.side == "sell"}
    wallet_gross: dict[str, float] = defaultdict(float)
    for item in wallet_rows:
        wallet_gross[str(item.wallet_key)] += abs(shadow._ratio_signed(item))

    wallet_gross_total = sum(wallet_gross.values())
    all_gross = float(gross) if isinstance(gross, (int, float)) and not isinstance(gross, bool) and math.isfinite(float(gross)) else 0.0
    covered_wallet_events = len(wallet_rows)
    unique_wallet_count = len(wallet_counts)
    repeat_wallet_share = _pct(max(0, covered_wallet_events - unique_wallet_count), covered_wallet_events)
    top_wallet_event_share = _pct(max(wallet_counts.values(), default=0), covered_wallet_events)
    top_wallet_gross = max(wallet_gross.values(), default=0.0)
    top_wallet_gross_share = _pct(top_wallet_gross, wallet_gross_total)
    wallet_gross_coverage = _pct(wallet_gross_total, all_gross)

    # Conservative upper bound for concentration under incomplete wallet identity.
    # All unidentified gross flow is pessimistically assigned to the current top wallet.
    # This never makes the token look more distributed because of missing wallet data.
    unidentified_gross = max(0.0, all_gross - wallet_gross_total)
    top_wallet_gross_worst_case_share = _pct(
        top_wallet_gross + unidentified_gross,
        all_gross,
    )

    tx_rows = [item for item in rows if item.transaction_key is not None]
    tx_counts = Counter(str(item.transaction_key) for item in tx_rows)
    tx_gross: dict[str, float] = defaultdict(float)
    for item in tx_rows:
        tx_gross[str(item.transaction_key)] += abs(shadow._ratio_signed(item))
    tx_gross_total = sum(tx_gross.values())

    base.update(
        {
            "sniper_feature_enrichment_version": ENRICHMENT_VERSION,
            "directional_flow_efficiency": directional_efficiency,
            "wallet_observed_event_count": covered_wallet_events,
            "unique_buy_wallet_count": len(unique_buy_wallets),
            "unique_sell_wallet_count": len(unique_sell_wallets),
            "repeat_wallet_event_share_pct": repeat_wallet_share,
            "top_wallet_event_share_pct": top_wallet_event_share,
            "top_wallet_gross_flow_share_pct": top_wallet_gross_share,
            "top_wallet_gross_flow_share_worst_case_pct": top_wallet_gross_worst_case_share,
            "wallet_gross_flow_coverage_pct": wallet_gross_coverage,
            "top_transaction_event_share_pct": _pct(max(tx_counts.values(), default=0), len(tx_rows)),
            "top_transaction_gross_flow_share_pct": _pct(max(tx_gross.values(), default=0.0), tx_gross_total),
            "sniper_wallet_feature_available": bool(total > 0 and covered_wallet_events > 0),
        }
    )
    return base


@contextmanager
def patched_sniper_feature_enrichment_v1() -> Iterator[None]:
    original_envelope = live_v2._envelope
    original_feature_snapshot = live_v2._feature_snapshot
    live_v2._envelope = envelope_with_sniper_wallet_v1
    live_v2._feature_snapshot = feature_snapshot_with_sniper_v1
    try:
        yield
    finally:
        live_v2._envelope = original_envelope
        live_v2._feature_snapshot = original_feature_snapshot
