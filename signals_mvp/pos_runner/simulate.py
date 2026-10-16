"""Simulador de trade do POS-RUNNER-V0 (paper): saidas A e B com custos, a partir de um evento ENTRADA.

Convencoes (iguais no backtest e no paper ao vivo):
- Entrada no OPEN do candle seguinte ao sinal. Se esse open ja esta abaixo do stop ou acima do alvo, o trade e
  CANCELADO (o operador ve o preco fora do plano e nao entra) — reportado, nunca contado como trade.
- No mesmo candle, se a minima toca o stop e a maxima toca o alvo, a ordem e desconhecida: conta o STOP
  primeiro (conservador) e marca `ambiguo`.
- Stop preenche no nivel do stop, ou no open se o candle ja abriu abaixo (gap). Alvo idem para cima.
- Exaustao: candle verde com amplitude >= power_atr_mult x ATR(20) (20 candles anteriores) e fechamento
  >= entrada x (1 + exhaustion_gain) -> sai no open seguinte.
- Stop de tempo: depois de `time_stop_candles` candles no trade, sai no open seguinte.
- Saida B: no alvo vende `partial_frac`; o resto passa a ter stop = max(entrada, (1 - trail_frac) x maxima
  desde a entrada), valendo a partir do candle SEGUINTE ao do alvo (ordem dentro do candle e desconhecida).
- Sem candles suficientes para fechar = `em_aberto` (fica de fora das metricas ate fechar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .candles import Bar
from .costs import CostModel
from .detector import Event
from .params import Params


@dataclass
class Leg:
    idx: int
    ts: int
    price: float
    frac: float
    reason: str
    cost_pct: float


@dataclass
class TradeResult:
    variant: str
    status: str                     # fechado | em_aberto | cancelado
    entry_idx: int
    entry_ts: Optional[int] = None
    entry_price: Optional[float] = None
    entry_cost_pct: Optional[float] = None
    stop: Optional[float] = None
    tp: Optional[float] = None
    legs: list[Leg] = field(default_factory=list)
    ambiguous: bool = False
    hit_tp: bool = False
    gross_ret: Optional[float] = None
    net_ret: Optional[float] = None
    risk_frac: Optional[float] = None
    r_mult: Optional[float] = None
    bars_held: Optional[int] = None
    reason: str = ""
    # saida JA decidida no fechamento do candle `pending_idx` (exaustao/tempo), esperando o open do candle seguinte:
    # o bot ao vivo avisa nesse fechamento, sem esperar o proximo candle existir
    pending_exit: str = ""
    pending_idx: Optional[int] = None


def _atr(bars: list[Bar], j: int, n: int) -> Optional[float]:
    if j < n:
        return None
    total = 0.0
    for k in range(j - n, j):
        prev = bars[k - 1].close if k > 0 else bars[k].open
        b = bars[k]
        total += max(b.high - b.low, abs(b.high - prev), abs(b.low - prev))
    return total / n


def simulate(
    bars: list[Bar],
    event: Event,
    variant: str,
    params: Params,
    costs: CostModel,
    dex: str,
    l_bc: Optional[float],
    sol_usd_at: Callable[[float], Optional[float]],
    pool_fee_pct: Optional[float] = None,
) -> TradeResult:
    if variant not in ("A", "B"):
        raise ValueError("variante deve ser A ou B")
    i = event.idx
    stop = float(event.data["stop"])
    tp = float(event.data["tp"])
    res = TradeResult(variant=variant, status="em_aberto", entry_idx=i + 1, stop=stop, tp=tp)
    j0 = i + 1
    if j0 >= len(bars):
        return res
    entry = bars[j0].open
    res.entry_ts, res.entry_price = bars[j0].ts, entry
    if entry <= stop or entry >= tp:
        res.status = "cancelado"
        res.reason = "abriu abaixo do stop" if entry <= stop else "abriu acima do alvo"
        return res

    def leg_cost(price: float, ts: int) -> float:
        return costs.leg_pct(dex, price, l_bc, sol_usd_at(ts), pool_fee_pct)

    res.entry_cost_pct = leg_cost(entry, bars[j0].ts)
    res.risk_frac = (entry - stop) / entry
    remaining = 1.0
    tp1_done = False
    max_high = entry
    last = min(len(bars) - 1, j0 + params.time_stop_candles - 1)

    def exit_leg(j: int, price: float, frac: float, reason: str) -> None:
        nonlocal remaining
        res.legs.append(Leg(j, bars[j].ts, price, frac, reason, leg_cost(price, bars[j].ts)))
        remaining -= frac

    def exit_next_open(j: int, reason: str) -> bool:
        """Sai do restante no open do candle j+1. False se ainda nao existe esse candle."""
        if j + 1 >= len(bars):
            res.pending_exit, res.pending_idx = reason, j
            return False
        exit_leg(j + 1, bars[j + 1].open, remaining, reason)
        return True

    j = j0
    while j <= last and remaining > 1e-12:
        bar = bars[j]
        if not tp1_done:
            hit_stop = bar.low <= stop
            hit_tp = bar.high >= tp
            if hit_stop and hit_tp:
                res.ambiguous = True
            if hit_stop:
                exit_leg(j, min(bar.open, stop), remaining, "stop")
                break
            if hit_tp:
                fill = max(bar.open, tp)
                res.hit_tp = True
                if variant == "A":
                    exit_leg(j, fill, remaining, "alvo")
                    break
                exit_leg(j, fill, params.partial_frac, "alvo_parcial")
                tp1_done = True   # o trailing do resto vale a partir do proximo candle
        else:
            trail = max(entry, (1.0 - params.trail_frac) * max_high)
            if bar.low <= trail:
                exit_leg(j, min(bar.open, trail), remaining, "trailing" if trail > entry else "stop_na_entrada")
                break
        max_high = max(max_high, bar.high)
        atr = _atr(bars, j, params.atr_period)
        green_power = bar.close > bar.open and atr is not None and (bar.high - bar.low) >= params.power_atr_mult * atr
        if green_power and bar.close >= entry * (1.0 + params.exhaustion_gain):
            if not exit_next_open(j, "exaustao"):
                return _finish(res, entry, open_trade=True)
            break
        if j == j0 + params.time_stop_candles - 1:
            if not exit_next_open(j, "tempo"):
                return _finish(res, entry, open_trade=True)
            break
        j += 1
    if remaining > 1e-12:
        return _finish(res, entry, open_trade=True)
    return _finish(res, entry, open_trade=False)


def _finish(res: TradeResult, entry: float, open_trade: bool) -> TradeResult:
    if open_trade:
        res.status = "em_aberto"
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
