"""Acompanhamento: o que aconteceu depois de CADA token avaliado (enviado ou nao).

Tudo e calculado a partir de candles OHLCV de 1 min do GeckoTerminal, de forma causal:
  * a entrada e o preco da foto de decisao (`decision_ts`);
  * so entram na simulacao candles que COMECAM depois da decisao (o candle que contem a
    decisao tem parte do movimento anterior a ela e e descartado — ate ~59 s de movimento
    nao sao simulados, o que e conservador);
  * checkpoints +5/+15/+60: close do ultimo candle FECHADO ate o instante alvo (carregado para
    frente se o minuto nao teve trade); MC = MC_entrada x preco/preco_entrada (oferta constante);
  * max/min: extremos de 1 min dentro da janela [primeiro candle apos a decisao, +60 min].

Simulacao do plano (TP1 parcial, SL, saida por tempo), por candle de 1 min:
  * TP e SL no MESMO candle => 'ambiguo' (nao da para saber quem veio primeiro com candle de
    1 min). Aproximacao documentada: o resultado_liq assume o PIOR caso (SL primeiro);
  * stop com gap: se o candle abre abaixo do stop, a saida e na abertura (pior que o stop);
  * TP preenche exatamente no nivel do TP (conservador: ignora abertura acima do nivel);
  * taxas por perna: taxa_terminal_pct do valor negociado + fee_rede_usd fixo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .models import Candle

CHECKPOINTS_MIN = (5, 15, 60)
WINDOW_MIN = 60


@dataclass(frozen=True)
class Plan:
    posicao_usd: float
    tp1_pct: float
    tp1_venda_pct: float
    sl_pct: float
    tempo_min: float
    sl_apos_tp1: str
    taxa_terminal_pct: float
    fee_rede_usd: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


def plan_from_config(plano_cfg: dict, fee_rede_usd: float) -> Plan:
    return Plan(
        posicao_usd=float(plano_cfg["posicao_usd"]),
        tp1_pct=float(plano_cfg["tp1_pct"]),
        tp1_venda_pct=float(plano_cfg["tp1_venda_pct"]),
        sl_pct=float(plano_cfg["sl_pct"]),
        tempo_min=float(plano_cfg["tempo_min"]),
        sl_apos_tp1=str(plano_cfg["sl_apos_tp1"]),
        taxa_terminal_pct=float(plano_cfg["taxa_terminal_pct"]),
        fee_rede_usd=float(fee_rede_usd),
    )


@dataclass
class Outcome:
    mc_5m: Optional[float] = None
    mc_15m: Optional[float] = None
    mc_1h: Optional[float] = None
    max_mc: Optional[float] = None
    min_mc: Optional[float] = None
    tp1_antes_sl: str = "sem_dado"          # sim | nao | ambiguo | nenhum | sem_dado
    resultado_liq_pct: Optional[float] = None
    detail: dict = field(default_factory=dict)


def _ceil_minute(ts: float) -> float:
    return math.ceil(ts / 60.0) * 60.0


def _last_close_until(candles: Sequence[Candle], end_ts: float) -> Optional[float]:
    """Close do ultimo candle FECHADO ate end_ts (candle.ts + 60 <= end_ts); None se nao ha nenhum."""
    last: Optional[Candle] = None
    for candle in candles:
        if candle.ts + 60 <= end_ts:
            last = candle
        else:
            break
    return None if last is None else last.close


def simulate_plan(path: Sequence[Candle], entry_price: float, plan: Plan, exit_price_if_flat: Optional[float] = None) -> tuple[str, float, dict]:
    """Devolve (tp1_antes_sl, resultado_liq_pct, detalhe) para a trilha de candles pos-decisao."""
    n = plan.posicao_usd
    term = plan.taxa_terminal_pct / 100.0
    fee_in = n * term + plan.fee_rede_usd
    tokens = (n - fee_in) / entry_price
    tp_level = entry_price * (1.0 + plan.tp1_pct / 100.0)
    sl_level = entry_price * (1.0 - plan.sl_pct / 100.0)
    sell_fraction = plan.tp1_venda_pct / 100.0

    total_net = 0.0
    remaining = 1.0
    tp_hit = False
    flag = "nenhum"
    legs: list[dict] = []
    exited = False

    def sell(fraction: float, price: float, why: str) -> None:
        nonlocal total_net
        gross = tokens * fraction * price
        net = gross - (gross * term + plan.fee_rede_usd)
        total_net += net
        legs.append({"motivo": why, "fracao": round(fraction, 4), "preco": price, "liquido_usd": round(net, 4)})

    def stop_fill(candle: Candle, level: float) -> float:
        return candle.open if candle.open < level else level  # gap abaixo do stop: sai na abertura

    for candle in path:
        if not tp_hit:
            hit_tp = candle.high >= tp_level
            hit_sl = candle.low <= sl_level
            if hit_tp and hit_sl:
                flag = "ambiguo"
                sell(remaining, stop_fill(candle, sl_level), "sl_pior_caso_ambiguo")
                remaining, exited = 0.0, True
                break
            if hit_sl:
                flag = "nao"
                sell(remaining, stop_fill(candle, sl_level), "sl")
                remaining, exited = 0.0, True
                break
            if hit_tp:
                flag = "sim"
                tp_hit = True
                sell(sell_fraction, tp_level, "tp1")
                remaining -= sell_fraction
                if plan.sl_apos_tp1 == "breakeven":
                    sl_level = entry_price
                # o resto da posicao segue; o SL (original ou breakeven) vale a partir do PROXIMO candle
                continue
        else:
            if candle.low <= sl_level:
                sell(remaining, stop_fill(candle, sl_level), "sl_pos_tp1" if plan.sl_apos_tp1 == "mantem" else "breakeven")
                remaining, exited = 0.0, True
                break

    if not exited and remaining > 1e-12:
        if path:
            price, why = path[-1].close, "tempo"
        else:
            price, why = (exit_price_if_flat or entry_price), "tempo_sem_candles"
        sell(remaining, price, why)

    result_pct = 100.0 * (total_net - n) / n
    return flag, result_pct, {"pernas": legs, "taxa_entrada_usd": round(fee_in, 4), "sl_nivel": sl_level, "tp_nivel": tp_level}


def compute_outcome(
    candles: Sequence[Candle], entry_price: float, entry_mc: Optional[float], decision_ts: float, plan: Plan
) -> Outcome:
    """Calcula tudo o que vai para o sinais.csv depois da janela. `candles` em ordem crescente."""
    if entry_price is None or entry_price <= 0 or not candles:
        return Outcome(detail={"flags": ["sem_candles" if not candles else "sem_preco_entrada"]})
    ordered = sorted(candles, key=lambda c: c.ts)
    first_ts = _ceil_minute(decision_ts)
    flags: list[str] = []

    def mc_at(price: Optional[float]) -> Optional[float]:
        if price is None or entry_mc is None:
            return None
        return entry_mc * price / entry_price

    # checkpoints (carrega o ultimo close para frente)
    marks = {}
    for minutes in CHECKPOINTS_MIN:
        marks[minutes] = _last_close_until(ordered, decision_ts + minutes * 60.0)

    # extremos da janela inteira (+60 min), so candles apos a decisao e ja fechados
    window_end = decision_ts + WINDOW_MIN * 60.0
    window = [c for c in ordered if c.ts >= first_ts and c.ts + 60 <= window_end]
    if window:
        highs, lows = max(c.high for c in window), min(c.low for c in window)
    else:
        highs = lows = None
        flags.append("sem_trades_na_janela")

    # trilha do plano: candles apos a decisao, fechados ate o fim do prazo
    stop_ts = decision_ts + plan.tempo_min * 60.0
    path = [c for c in ordered if c.ts >= first_ts and c.ts + 60 <= stop_ts]
    flag, result_pct, sim = simulate_plan(path, entry_price, plan, exit_price_if_flat=marks.get(5))
    if not path:
        flags.append("sem_candles_no_prazo")
    if flag == "ambiguo":
        flags.append("ambiguo_sl_primeiro")

    return Outcome(
        mc_5m=mc_at(marks[5]),
        mc_15m=mc_at(marks[15]),
        mc_1h=mc_at(marks[60]),
        max_mc=mc_at(highs),
        min_mc=mc_at(lows),
        tp1_antes_sl=flag,
        resultado_liq_pct=result_pct,
        detail={
            "flags": flags,
            "n_candles_janela": len(window),
            "n_candles_prazo": len(path),
            "max_pct": None if highs is None else round(100.0 * (highs / entry_price - 1.0), 2),
            "min_pct": None if lows is None else round(100.0 * (lows / entry_price - 1.0), 2),
            **sim,
        },
    )
