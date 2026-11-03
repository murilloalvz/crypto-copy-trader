"""PEDIDO (PARTE 1 de 2), FASES 1-2: medicao "ao lado" da POS-RUNNER-V1/V2 (PAPER / so leitura).

Tudo aqui roda DEPOIS da decisao real de V1/V2 (`live.py` chama estas funcoes a partir de
`_update_evidencia_v1`/`_update_evidencia_v2`, nunca de dentro do detector/simulador oficiais) e NUNCA
altera deteccao, entrada, saida, banca, Telegram ou CSV existente de V1/V2 -- so grava medicao extra em
tabelas proprias (`pr_trajetoria`, `pr_baseline`). Reusa `simulate_v1` (nunca copia a logica de
saida/exaustao) e as mesmas `Bar`/`EventV1` do resto do POS-RUNNER-V1.

FASE 1 -- trajetoria pos-entrada (`calcular_trajetoria`): MFE/MAE em R e retorno em R em horizontes
fixos (1,2,4,8,24,48,72h), a partir dos candles 1h ja cacheados (`pr_bars`). "1R" (unidade de risco) =
`entry_price x risco_frac`, igual ao risco real do trade (entry-stop). Fecha (deixa de atualizar) 72h
depois da entrada; o que nao deu tempo de resolver fica NULL para sempre (nunca interpolado).

FASE 2a -- baseline pareada (`candidatos_elegiveis`/`sortear_controles`/`evento_controle`): para cada
ENTRADA real, um controle e um candle "parecido" (mesmo token, depois de um pico, queda >= 80% desde
esse pico, MC >= 100k, dentro da MESMA janela de idade da versao que gerou o sinal real) que NUNCA e o
candle do gatilho real. Simulado com o MESMO risco_pct do sinal real (stop = entry_controle x
(1 - risco_pct/100)) e a MESMA FORMA relativa de saida (TOPO e S escalados pela mesma razao
TOPO/entry e S/entry do sinal real -- unica forma de reusar `simulate_v1` sem inventar um novo alvo
para cada controle; documentado em docs/pos-runner-v1/INTERPRETACOES.md).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .candles import Bar
from .detector_v1 import EventV1
from .simulate_v1 import LegV1, simulate_v1

HORIZONTES_H: tuple[int, ...] = (1, 2, 4, 8, 24, 48, 72)
JANELA_FECHAMENTO_H = 72.0
N_CONTROLES_PADRAO = 10
N_CONTROLES_MINIMO = 3
DROP_MIN_CONTROLE = 0.80
MC_MIN_CONTROLE = 100_000.0


def r_de(preco: Optional[float], entry_price: float, risco_frac: float) -> Optional[float]:
    """R-multiplo de um preco relativo a entrada: (preco/entry - 1) / risco_frac. `None` se faltar dado
    (nunca interpolado) -- `risco_frac` precisa ser > 0 (risco nulo/negativo e dado invalido, nunca 0R)."""
    if preco is None or not risco_frac or risco_frac <= 0:
        return None
    return (preco / entry_price - 1.0) / risco_frac


@dataclass(frozen=True)
class TrajetoriaCalc:
    mfe_r: Optional[float]
    mfe_h: Optional[float]
    mae_r: Optional[float]
    mae_h: Optional[float]
    retornos_r: dict[int, Optional[float]]
    tocou_tp1: bool
    tocou_stop_antes_de_tp1: bool
    fechado: bool


def calcular_trajetoria(
    bars: Sequence[Bar], entry_idx: int, entry_ts: float, entry_price: float, risco_frac: float,
    step_s: int, legs: Sequence[LegV1], now: float, horizontes_h: Sequence[int] = HORIZONTES_H,
) -> TrajetoriaCalc:
    """FASE 1: MFE/MAE (maxima excursao favoravel/adversa, em R, com a hora em que ocorreu) e retorno em
    R nos horizontes fixos, a partir dos candles [entry_idx:] de `bars` (ja em cache, nunca busca nada
    nova aqui). `legs` e o resultado JA simulado por `simulate_v1` para o MESMO evento (reusado, nunca
    recalculado) -- so para saber se tocou TP1/stop. `fechado`: True depois de 72h reais (`now`), mesmo
    que algum horizonte tenha ficado sem candle (fica None para sempre, nunca interpolado)."""
    mfe_r: Optional[float] = None
    mfe_h: Optional[float] = None
    mae_r: Optional[float] = None
    mae_h: Optional[float] = None
    limite_h = float(max(horizontes_h)) if horizontes_h else JANELA_FECHAMENTO_H
    for j in range(entry_idx, len(bars)):
        bar = bars[j]
        if bar.ts < entry_ts:
            continue
        h = (bar.ts + step_s - entry_ts) / 3600.0
        if h > limite_h + 1e-9:
            break
        r_high = r_de(bar.high, entry_price, risco_frac)
        r_low = r_de(bar.low, entry_price, risco_frac)
        if r_high is not None and (mfe_r is None or r_high > mfe_r):
            mfe_r, mfe_h = r_high, h
        if r_low is not None and (mae_r is None or r_low < mae_r):
            mae_r, mae_h = r_low, h
    retornos: dict[int, Optional[float]] = {}
    for h in horizontes_h:
        offset_candles = round(h * 3600.0 / step_s)
        idx = entry_idx + offset_candles - 1
        retornos[h] = r_de(bars[idx].close, entry_price, risco_frac) if 0 <= idx < len(bars) else None
    tocou_tp1 = any(leg.reason == "tp1" for leg in legs)
    tocou_stop_antes_de_tp1 = False
    for leg in legs:
        if leg.reason == "tp1":
            break
        if leg.reason == "stop":
            tocou_stop_antes_de_tp1 = True
            break
    fechado = (now - entry_ts) >= JANELA_FECHAMENTO_H * 3600.0
    return TrajetoriaCalc(mfe_r, mfe_h, mae_r, mae_h, retornos, tocou_tp1, tocou_stop_antes_de_tp1, fechado)


def candidatos_elegiveis(
    bars: Sequence[Bar], created_ts: Optional[float], age_window_days: tuple[float, float], step_s: int,
    excluir_idx: int, drop_min: float = DROP_MIN_CONTROLE, mc_min: float = MC_MIN_CONTROLE,
) -> list[int]:
    """FASE 2a: indices de `bars` elegiveis como controle -- depois de um pico ANTERIOR (maxima de um
    candle i' < i), queda >= `drop_min` desde esse pico, MC (fechamento) >= `mc_min`, idade do token
    dentro de `age_window_days` (a MESMA janela da versao que gerou o sinal real -- V1 ou V2, conforme
    quem chama), e nunca o candle do gatilho real (`excluir_idx`). Idade `None` (sem `created_ts`) nunca
    e elegivel (nunca adivinha a janela)."""
    if created_ts is None:
        return []
    out: list[int] = []
    peak: Optional[float] = None
    for i, bar in enumerate(bars):
        if peak is not None and i != excluir_idx:
            age = (bar.ts + step_s - created_ts) / 86400.0
            if (bar.close >= mc_min and (1.0 - bar.close / peak) >= drop_min
                    and age_window_days[0] <= age <= age_window_days[1]):
                out.append(i)
        if peak is None or bar.high > peak:
            peak = bar.high
    return out


def seed_de_entrada(entry_id: int, versao: str) -> int:
    """Seed fixa (item 2a): mesma entrada sempre sorteia os MESMOS controles."""
    digest = hashlib.sha256(f"controle:{versao}:{entry_id}".encode("utf-8")).hexdigest()
    return int(digest, 16) % (2**32)


def sortear_controles(candidatos: Sequence[int], entry_id: int, versao: str, n: int = N_CONTROLES_PADRAO) -> list[int]:
    """Sorteio SEM reposicao, seed fixa = hash(entry_id). Devolve os indices ordenados (so para
    legibilidade/determinismo de teste; a ordem nao importa para a media)."""
    rng = random.Random(seed_de_entrada(entry_id, versao))
    pool = list(candidatos)
    rng.shuffle(pool)
    return sorted(pool[:n])


def evento_controle(bars: Sequence[Bar], idx: int, risco_pct_sinal: float, topo_mult: float, s_mult: float) -> Optional[EventV1]:
    """Evento sintetico ENTRADA no candle `idx`, para reusar `simulate_v1` sem copiar a logica de
    saida. `stop` usa o MESMO risco_pct do sinal real (item 2a: "mesmo risco_pct do sinal"); `TOPO`/`S`
    sao escalados pela MESMA razao preco/entry do sinal real (unica forma de preservar "as mesmas regras
    de saida em R" reusando `simulate_v1`, que precisa de um TOPO/S em preco absoluto -- ver
    INTERPRETACOES.md). `None` se nao houver candle seguinte para abrir a posicao (simulate_v1 exige
    bars[idx+1] para a entrada no open; sem ele o controle fica sem dado, nunca inventado)."""
    if idx + 1 >= len(bars) or not risco_pct_sinal or topo_mult is None or s_mult is None:
        return None
    entry_price = bars[idx + 1].open
    stop = entry_price * (1.0 - risco_pct_sinal / 100.0)
    topo = entry_price * topo_mult
    s = entry_price * s_mult
    ts = bars[idx].ts
    return EventV1(kind="ENTRADA", idx=idx, ts=ts, decision_ts=ts, data={"stop": stop, "TOPO": topo, "S": s})


def simular_controle(
    bars: Sequence[Bar], idx: int, risco_pct_sinal: float, topo_mult: float, s_mult: float,
    params: Any, costs: Any, dex: str, l_bc: Optional[float], sol_usd_at: Any,
) -> Optional[Any]:
    """Roda `simulate_v1` sobre o evento sintetico do controle. `None` = sem dado ainda (candle seguinte
    nao existe) -- quem chama guarda como pendente, nunca inventa um resultado."""
    ev = evento_controle(bars, idx, risco_pct_sinal, topo_mult, s_mult)
    if ev is None:
        return None
    return simulate_v1(bars, ev, params, costs, dex, l_bc, sol_usd_at)
