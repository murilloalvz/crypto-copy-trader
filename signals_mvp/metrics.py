"""Metricas da v0 (so o que GeckoTerminal/GoPlus entregam). Dado ausente = None."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from .models import PoolSnap, TradesSummary

MIN_AGE_FOR_ACCEL_S = 300.0


@dataclass
class Metrics:
    age_s: Optional[float]
    price: Optional[float]
    mc: Optional[float]
    liq: Optional[float]
    liq_unreliable: bool
    vol_m5: Optional[float]
    vol_h1: Optional[float]
    acel: Optional[float]            # ritmo do m5 / ritmo medio dos ultimos min(idade, 60) min
    buys: Optional[int]
    sells: Optional[int]
    tx_total: Optional[int]
    buy_pct: Optional[float]         # % de compras por contagem
    buyers: Optional[int]            # compradores unicos no m5
    sellers: Optional[int]
    pos_pct_liq: Optional[float]     # posicao padrao como % da liquidez
    ticket_medio: Optional[float]    # volume m5 / transacoes m5
    tx_por_carteira: Optional[float]
    price_change_m5: Optional[float]
    buy_usd: Optional[float] = None  # valor de compras (trades; pode ser parcial)
    sell_usd: Optional[float] = None
    trades_complete: Optional[bool] = None
    trades_covered_s: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def acceleration(vol_m5: Optional[float], vol_h1: Optional[float], age_s: Optional[float]) -> Optional[float]:
    """Ritmo (USD/min) do ultimo 5 min dividido pelo ritmo medio da ultima hora (ou da vida do pool).

    Definida so para pool com 5+ min de vida. Em pool mais novo nao ha base de comparacao => None
    (o score trata isso por config, nao inventa 1.0x).
    """
    if vol_m5 is None or vol_h1 is None or age_s is None or age_s < MIN_AGE_FOR_ACCEL_S:
        return None
    span_min = min(age_s / 60.0, 60.0)
    average_rate = vol_h1 / span_min
    if average_rate <= 0:
        return None
    return (vol_m5 / 5.0) / average_rate


def compute_metrics(snap: PoolSnap, position_usd: float, trades: Optional[TradesSummary] = None) -> Metrics:
    m5 = snap.window("m5")
    vol_m5 = snap.vol_window("m5")
    vol_h1 = snap.vol_window("h1")
    age = snap.age_s()
    tx_total = m5.total
    ticket = (vol_m5 / tx_total) if (vol_m5 is not None and tx_total) else None
    per_wallet = None
    if tx_total and m5.buyers is not None and m5.sellers is not None:
        most = max(m5.buyers, m5.sellers)
        per_wallet = (tx_total / most) if most > 0 else None
    pos_pct = (100.0 * position_usd / snap.liq_usd) if snap.liq_usd else None
    return Metrics(
        age_s=age,
        price=snap.price_usd,
        mc=snap.mc_usd,
        liq=snap.liq_usd,
        liq_unreliable=snap.liq_unreliable,
        vol_m5=vol_m5,
        vol_h1=vol_h1,
        acel=acceleration(vol_m5, vol_h1, age),
        buys=m5.buys,
        sells=m5.sells,
        tx_total=tx_total,
        buy_pct=m5.buy_pct,
        buyers=m5.buyers,
        sellers=m5.sellers,
        pos_pct_liq=pos_pct,
        ticket_medio=ticket,
        tx_por_carteira=per_wallet,
        price_change_m5=snap.price_change.get("m5"),
        buy_usd=None if trades is None else trades.buy_usd,
        sell_usd=None if trades is None else trades.sell_usd,
        trades_complete=None if trades is None else trades.complete,
        trades_covered_s=None if trades is None else trades.covered_s,
    )
