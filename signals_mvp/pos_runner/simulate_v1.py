"""Simulador de trade da estrategia POS-RUNNER-V1 (paper), a partir de um evento ENTRADA do `detector_v1.py`.

Convencoes (ver docs/pos-runner-v1/INTERPRETACOES.md #2/#3 para a justificativa de cada uma):
- Entrada no OPEN do candle seguinte ao sinal (item 2.6: "Execucao no open do candle seguinte"). Abriu fora do
  plano (abaixo do stop ou acima do TOPO) = CANCELADO, nunca contado como trade.
- STOP (item 2.8) e intracandle: a minima toca o nivel -> preenche no stop (ou no open, se abriu em gap abaixo).
  Tem prioridade sobre TP1/EXIT FULL no mesmo candle (mesma logica conservadora do V0).
- TP1 (item 2.9): 30% da posicao quando a MAXIMA do candle alcanca o TOPO (P_peak) E o candle mostra exaustao
  (power candle OU pavio superior longo -- `_exhaustion`). Decidido no FECHAMENTO desse candle, executado no
  OPEN do candle seguinte (mesma convencao do V0 para saida por exaustao -- nao enche intracandle no proprio
  TOPO: a decisao so e conhecida no fechamento).
- EXIT FULL (item 2.9): o RESTANTE da posicao (70% se TP1 ja saiu, 100% se TP1 nunca disparou) quando um candle
  FECHA abaixo de S. Decidido no fechamento, executado no open do candle seguinte. Tem prioridade sobre um TP1
  ainda nao decidido no mesmo candle (e um sinal de invalidacao, mais forte que o de realizacao parcial).
- Sem candles suficientes para fechar = `em_aberto`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .candles import Bar
from .costs import CostModel
from .detector_v1 import EventV1
from .params_v1 import ParamsV1


@dataclass
class LegV1:
    idx: int
    ts: int
    price: float
    frac: float
    reason: str
    cost_pct: float


@dataclass
class TradeResultV1:
    status: str                     # fechado | em_aberto | cancelado
    entry_idx: int
    entry_ts: Optional[int] = None
    entry_price: Optional[float] = None
    entry_cost_pct: Optional[float] = None
    stop: Optional[float] = None
    topo: Optional[float] = None
    legs: list[LegV1] = field(default_factory=list)
    gross_ret: Optional[float] = None
    net_ret: Optional[float] = None
    risk_frac: Optional[float] = None
    r_mult: Optional[float] = None
    bars_held: Optional[int] = None
    reason: str = ""
    pending_exit: str = ""
    pending_idx: Optional[int] = None
    pending_frac: float = 0.0
    max_high: Optional[float] = None


def _atr(bars: list[Bar], j: int, n: int) -> Optional[float]:
    if j < n:
        return None
    total = 0.0
    for k in range(j - n, j):
        prev = bars[k - 1].close if k > 0 else bars[k].open
        b = bars[k]
        total += max(b.high - b.low, abs(b.high - prev), abs(b.low - prev))
    return total / n


def _exhaustion(bar: Bar, atr: Optional[float], params: ParamsV1) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    power = atr is not None and rng >= params.power_atr_mult * atr
    body = abs(bar.close - bar.open)
    upper_wick = bar.high - max(bar.open, bar.close)
    if body > 1e-12:
        long_wick = upper_wick >= params.exhaustion_wick_mult * body
    else:
        long_wick = upper_wick >= params.exhaustion_doji_frac * rng
    return power or long_wick


def simulate_v1(
    bars: list[Bar],
    event: EventV1,
    params: ParamsV1,
    costs: CostModel,
    dex: str,
    l_bc: Optional[float],
    sol_usd_at: Callable[[float], Optional[float]],
    pool_fee_pct: Optional[float] = None,
    candle_confiavel: Optional[Callable[[int], Optional[str]]] = None,
) -> TradeResultV1:
    """`candle_confiavel(j)` -- PATCH 2026-10-27 (diagnostico McRib/yagi): `None` (motivo) para o
    candle no indice `j` do array `bars` = confiavel, decide normalmente; qualquer string = suspeito,
    NAO decide neste candle (nem stop, nem TP1, nem exit_full -- nem atualiza `max_high` com ele) ate
    confirmar por DexPaprika ou pelo candle seguinte (quem monta o callback, nao este modulo). Omitido
    (`None`) = todo candle confiavel, saida IDENTICA a antes do patch (equivalencia byte a byte)."""
    i = event.idx
    stop = float(event.data["stop"])
    topo = float(event.data["TOPO"])
    s_support = float(event.data["S"])
    res = TradeResultV1(status="em_aberto", entry_idx=i + 1, stop=stop, topo=topo)
    j0 = i + 1
    if j0 >= len(bars):
        return res
    entry = bars[j0].open
    res.entry_ts, res.entry_price = bars[j0].ts, entry
    if entry <= stop or entry >= topo:
        res.status = "cancelado"
        res.reason = "abriu abaixo do stop" if entry <= stop else "abriu acima do TOPO"
        return res

    def leg_cost(price: float, ts: int) -> float:
        return costs.leg_pct(dex, price, l_bc, sol_usd_at(ts), pool_fee_pct)

    res.entry_cost_pct = leg_cost(entry, bars[j0].ts)
    res.risk_frac = (entry - stop) / entry
    remaining = 1.0
    tp1_done = False
    max_high = entry

    def exit_leg(j: int, price: float, frac: float, reason: str) -> None:
        nonlocal remaining
        res.legs.append(LegV1(j, bars[j].ts, price, frac, reason, leg_cost(price, bars[j].ts)))
        remaining -= frac
        res.max_high = max(res.max_high or entry, max_high, price)

    def exit_next_open(j: int, reason: str, frac: float) -> bool:
        if j + 1 >= len(bars):
            res.pending_exit, res.pending_idx, res.pending_frac = reason, j, frac
            return False
        exit_leg(j + 1, bars[j + 1].open, frac, reason)
        return True

    confiavel = candle_confiavel or (lambda _j: None)
    j = j0
    while j < len(bars) and remaining > 1e-12:
        bar = bars[j]
        if confiavel(j) is not None:
            j += 1
            continue
        hit_stop = bar.low <= stop
        if hit_stop:
            exit_leg(j, min(bar.open, stop), remaining, "stop")
            break
        if bar.close < s_support:
            frac = remaining
            if not exit_next_open(j, "exit_full", frac):
                return _finish(res, entry, open_trade=True, max_high=max(max_high, bar.high))
            j += 1
            max_high = max(max_high, bar.high)
            continue
        if not tp1_done:
            atr = _atr(bars, j, params.atr_period)
            if bar.high >= topo and _exhaustion(bar, atr, params):
                if not exit_next_open(j, "tp1", params.tp1_frac):
                    return _finish(res, entry, open_trade=True, max_high=max(max_high, bar.high))
                tp1_done = True
                j += 1
                max_high = max(max_high, bar.high)
                continue
        max_high = max(max_high, bar.high)
        j += 1
    if remaining > 1e-12:
        return _finish(res, entry, open_trade=True, max_high=max_high)
    return _finish(res, entry, open_trade=False)


def _finish(res: TradeResultV1, entry: float, open_trade: bool, max_high: Optional[float] = None) -> TradeResultV1:
    if open_trade:
        res.status = "em_aberto"
        res.max_high = max(res.max_high or entry, max_high or entry)
        return res
    res.status = "fechado"
    c_in = (res.entry_cost_pct or 0.0) / 100.0
    gross = sum(leg.frac * leg.price / entry for leg in res.legs)
    net = sum(leg.frac * (leg.price / entry) * (1.0 - c_in) * (1.0 - leg.cost_pct / 100.0) for leg in res.legs)
    res.gross_ret = gross - 1.0
    res.net_ret = net - 1.0
    res.r_mult = res.net_ret / res.risk_frac if res.risk_frac else None
    res.bars_held = res.legs[-1].idx - res.entry_idx + 1 if res.legs else None
    res.reason = res.legs[-1].reason if res.legs else ""
    return res
