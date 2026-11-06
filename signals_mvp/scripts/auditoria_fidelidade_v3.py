"""PEDIDO 2026-11-05 (autorizado, rodada 11, Parte B): auditoria de fidelidade a estrategia do
"professor" sobre os sinais V3 JA EXISTENTES (ao_vivo, retro_lote1, replay_v3 -- SEPARADOS, nunca
somados). SOMENTE LEITURA no banco do bot (zero chamada de rede, zero escrita em qualquer tabela).
PAPER/READ-ONLY. V3 roda com `ParamsV3` CONGELADO (`56762db29cd6`) -- este script NUNCA altera
detector/simulate/parametros/H1/criterios de sinal. EXPLORATORIO: nunca evidencia confirmatoria,
nunca entra no N=30 nem na H1 (`docs/research-hypothesis-registry-v1-2026-10-04.md` continua sendo
a unica autoridade pra isso).

CONTEXTO CONFIRMADO PELO OPERADOR: o professor coloca o TP no topo do ultimo runner e pode deixar
parte correr -- o bot segue isso (TP1 de 30% no TOPO anterior com exaustao, item 2.9 de
`pos_runner/simulate_v1.py`); a estrategia e de CAUDA (alvo a dezenas de R, taxa de acerto baixa).

DEFINICOES CONFIRMADAS NO CODIGO (B1):
- TOPO ANTERIOR (`ev.data["TOPO"]` = `P_peak`, `detector_v1.py:204`) = a MAXIMA da onda/runner ANTES
  da queda que formou a caixa atual -- nunca o topo da propria caixa (isso e `R`, ver abaixo).
- "Topo da caixa" / `R` (`detector_v1.py:204`) = resistencia da zona (nivel de rompimento) -- SEMPRE
  <= TOPO anterior (a caixa se formou DEPOIS da queda do topo anterior).
- EXAUSTAO (`simulate_v1.py: _exhaustion`) = candle verde cuja amplitude >= `power_atr_mult` x
  ATR(20) (power candle) OU cujo pavio superior >= `exhaustion_wick_mult` x o corpo (ou, se o corpo
  for ~0, >= `exhaustion_doji_frac` x a amplitude -- caso doji). TP1 (30% da posicao, `tp1_frac`)
  dispara quando a MAXIMA do candle alcanca o TOPO anterior E o candle mostra exaustao, decidido no
  FECHAMENTO, executado no OPEN do candle seguinte.

ESCOPO/SIMPLIFICACOES DESTA RODADA (documentadas, nunca escondidas):
- Reusa os MESMOS loaders de replay/retro de `varredura_v3.py` (`carregar_universo_admitido` ->
  rotulado aqui `replay_v3`, `carregar_retro_lote1` -> MESMO nome) -- zero duplicacao de replay.
  `ao_vivo` e NOVO aqui (le `pr3_signals`/`pr_trajetoria`/`pr_bars`, MESMO padrao de
  `simular_v3_carteira.carregar_ao_vivo`, mas preserva TOPO/R/S/caixa/gatilho em vez de so o R final).
- B3 ("gestao dos 70%"): a regra (c) "nenhum ajuste" significa literalmente o STOP NUNCA SE MOVE
  (nunca confundido com TP1/EXIT FULL, que e sobre REALIZACAO PARCIAL de lucro, nao sobre
  gerenciamento de stop) -- e o controle natural pra comparar com (a)/(b), que MOVEM o stop. As 3
  regras sao medidas no MESMO horizonte de 72h MTM do resto do projeto (R marcado a mercado no
  corte), nunca uma serie infinita.
- B7 (preco real vs modelado): NAO calculavel com os dados atuais -- `pr3_signals.
  entry_price_alerta` fica SEMPRE NULL pra V3 (documentado em `storage.py`, a V3 nunca grava o
  preco observado no instante do alerta separado do preco do candle modelado). Reportado
  explicitamente como "sem dado", nunca inventado; instrumentar isso exige um campo novo gravado ao
  vivo (fora do escopo de um script read-only).
- IC exato (Clopper-Pearson) implementado aqui sem SciPy (nao e dependencia do projeto) via funcao
  beta incompleta regularizada (continued fraction, Numerical Recipes) + bissecao -- validado contra
  valores de referencia conhecidos (ex.: 5/10 a 95% ~= [0.1871, 0.8129]).

Uso (na VM, a partir da raiz do repo -- RAM/CPU fracos):
    nice -n 19 tmux new-session -d -s auditoria_fidelidade_v3 \
        'python -m signals_mvp.scripts.auditoria_fidelidade_v3 --db signals_mvp/dados/estado.sqlite \
         2>&1 | tee auditoria_fidelidade_v3.log'
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.candles import Bar, candle_corrompido_provavel, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.horizonte_fixo import HORIZONTES_S, calcular_r_horizonte
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage
from . import varredura_v3 as vv3

AVISO = ("EXPLORATORIO -- auditoria de fidelidade a estrategia, NUNCA evidencia de edge (H1/"
        "pre-registro decidem isso). ao_vivo/retro_lote1/replay_v3 SEPARADOS, nunca somados; "
        "retro_lote1/replay_v3 sao amostra DENTRO da amostra. Resultado em paper e TETO de "
        "execucao -- nunca entra no N=30 nem na H1.")

HORIZONTES_B: dict[str, Optional[float]] = {
    "72h": HORIZONTES_S["72h"], "7d": HORIZONTES_S["7d"], "14d": 14.0 * 24.0 * 3600.0,
    "ultimo_dado_limpo": None,   # None = sem corte, varre at'e o fim dos bars disponiveis
}
ALVOS_R_B2 = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0)
ALVOS_R_B3 = (1.0, 2.0, 3.0, 5.0)


# ---------------------------------------------------------------------------
# Clopper-Pearson (IC exato) -- sem SciPy, via beta incompleta regularizada
# ---------------------------------------------------------------------------


def _betacf(x: float, a: float, b: float) -> float:
    """Fracao continuada da funcao beta incompleta (Numerical Recipes, `betacf`)."""
    maxit, eps, fpmin = 200, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(x: float, a: float, b: float) -> float:
    """Funcao beta incompleta REGULARIZADA I_x(a,b) -- `x` em [0,1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(x, a, b) / a
    return 1.0 - bt * _betacf(1.0 - x, b, a) / b


def _betainc_inv(p: float, a: float, b: float, iter_bissecao: int = 100) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(iter_bissecao):
        mid = (lo + hi) / 2.0
        if _betainc(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson(x: int, n: int, confianca: float = 0.90) -> tuple[Optional[float], Optional[float]]:
    """IC EXATO de Clopper-Pearson pra uma proporcao `x/n` -- (None, None) se `n==0`."""
    if n == 0:
        return None, None
    alpha = 1.0 - confianca
    lo = 0.0 if x == 0 else _betainc_inv(alpha / 2.0, x, n - x + 1)
    hi = 1.0 if x == n else _betainc_inv(1.0 - alpha / 2.0, x + 1, n - x)
    return lo, hi


# ---------------------------------------------------------------------------
# B1-B8: modelo unificado de sinal (topo/R/S/caixa/gatilho preservados, reusa bars/ev existentes)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SinalAuditoria:
    token: str
    origem: str   # 'ao_vivo' | 'retro_lote1' | 'replay_v3'
    bars: list[Bar]
    gatilho_idx: int             # candle que disparou a decisao (FECHAMENTO)
    t_entrada: float
    entry_price: float
    stop: float
    topo: float                  # TOPO anterior = P_peak (pico do runner ANTES da queda da caixa)
    r_caixa: Optional[float]     # R = resistencia/topo da PROPRIA caixa (rompimento)
    s_val: Optional[float]       # S = suporte da caixa
    caixa_candles: Optional[int]
    caixa_horas: Optional[float]
    box_inicio_idx: Optional[int]
    n_testes: Optional[int]
    gatilhos: tuple[str, ...]
    idade_dias: Optional[float]
    volume_gatilho: Optional[float]
    volume_medio_24h: Optional[float]
    risk_frac: float
    dex: str
    l_bc: Optional[float]

    @property
    def j0(self) -> int:
        return self.gatilho_idx + 1


def _de_sinal_varredura(s: "vv3.SinalVarredura", origem: str) -> Optional[SinalAuditoria]:
    if s.risk_frac is None or s.risk_frac <= 0:
        return None
    data = s.ev.data
    box_start = data.get("box_start")
    box_len = data.get("box_len")
    return SinalAuditoria(
        token=s.token, origem=origem, bars=s.bars, gatilho_idx=s.ev.idx, t_entrada=s.t_entrada,
        entry_price=s.entry_price, stop=s.stop, topo=s.topo, r_caixa=data.get("R"), s_val=s.s_val,
        caixa_candles=box_len, caixa_horas=(box_len * tf_seconds(s.tf) / 3600.0) if box_len is not None else None,
        box_inicio_idx=box_start, n_testes=s.n_pavios, gatilhos=tuple(data.get("gatilho") or ()),
        idade_dias=data.get("idade_dias"), volume_gatilho=s.volume_gatilho,
        volume_medio_24h=s.volume_medio_24h, risk_frac=s.risk_frac, dex=s.dex, l_bc=s.l_bc,
    )


def carregar_replay_v3(db_path: Path) -> list[SinalAuditoria]:
    """B1-B8 rotulo 'replay_v3' = `varredura_v3.carregar_universo_admitido` (replay completo sobre
    pools admitidos hoje, zero duplicacao de logica)."""
    sinais = vv3.carregar_universo_admitido(db_path)
    out = [_de_sinal_varredura(s, "replay_v3") for s in sinais]
    return [s for s in out if s is not None]


def carregar_retro_lote1(db_path: Path) -> list[SinalAuditoria]:
    sinais = vv3.carregar_retro_lote1(db_path)
    out = [_de_sinal_varredura(s, "retro_lote1") for s in sinais]
    return [s for s in out if s is not None]


def carregar_ao_vivo(db_path: Path) -> list[SinalAuditoria]:
    """NOVO nesta rodada: MESMO padrao de leitura de `simular_v3_carteira.carregar_ao_vivo`, mas
    preserva TOPO/R/S/caixa/gatilho (lidos direto das colunas persistidas de `pr3_signals` -- a V3
    ja grava `caixa_candles`/`caixa_horas`/`n_pavios`/`idade_dias`/`r_resistencia`/`s_suporte` por
    sinal, zero replay necessario pra estas covariaveis)."""
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        params = load_params_v3()
        out: list[SinalAuditoria] = []
        bars_cache: dict[str, list[Bar]] = {}
        for sinal in storage.pr3_signals():
            if sinal["evento"] != "ENTRADA":
                continue
            if sinal["stop"] is None or sinal["topo"] is None or sinal["entry_price"] is None:
                continue
            traj = storage.pr_trajetoria_get("v3", sinal["id"])
            if traj is None or traj["t_entrada"] is None:
                continue
            tf = sinal["tf"] or params.timeframes[0]
            bars = bars_cache.setdefault(f"{sinal['pool']}|{tf}", [Bar(*row) for row in storage.pr_bars(sinal["pool"], tf)])
            j0 = None
            for idx, bar in enumerate(bars):
                if bar.ts == traj["t_entrada"]:
                    j0 = idx
                    break
            if j0 is None or j0 <= 0:
                continue
            gatilho_idx = j0 - 1
            pool_row = storage.pr_pool(sinal["pool"])
            l_bc = pool_row["l_bc"] if pool_row is not None else None
            dex = sinal["dex"] or "desconhecido"
            gatilhos = tuple(json.loads(sinal["gatilho"] or "[]"))
            risk_frac = (sinal["entry_price"] - sinal["stop"]) / sinal["entry_price"] if sinal["entry_price"] else 0.0
            if risk_frac <= 0:
                continue
            caixa_candles = sinal["caixa_candles"]
            box_inicio_idx = (gatilho_idx - caixa_candles) if caixa_candles is not None else None
            out.append(SinalAuditoria(
                token=sinal["symbol"] or (sinal["mint"] or "")[:8], origem="ao_vivo", bars=bars,
                gatilho_idx=gatilho_idx, t_entrada=float(traj["t_entrada"]), entry_price=sinal["entry_price"],
                stop=sinal["stop"], topo=sinal["topo"], r_caixa=sinal["r_resistencia"], s_val=sinal["s_suporte"],
                caixa_candles=caixa_candles, caixa_horas=sinal["caixa_horas"], box_inicio_idx=box_inicio_idx,
                n_testes=sinal["n_pavios"], gatilhos=gatilhos, idade_dias=sinal["idade_dias"],
                volume_gatilho=(bars[gatilho_idx].volume if 0 <= gatilho_idx < len(bars) else None),
                volume_medio_24h=vv3._volume_medio_24h_antes(bars, j0), risk_frac=risk_frac, dex=dex, l_bc=l_bc,
            ))
        return out
    finally:
        storage.close()


# ---------------------------------------------------------------------------
# B1: TOPO anterior -- distancia e fracao que alcanca antes do stop, por horizonte
# ---------------------------------------------------------------------------


def _toque_preco_causal(bars: list[Bar], j0: int, stop: float, preco_alvo: float,
                        horizonte_ts: Optional[float] = None) -> Optional[str]:
    """MESMA convencao causal de `varredura_v3._toque_causal` (prioridade do stop no mesmo candle,
    candle corrompido nunca decide), generalizada pra um PRECO alvo absoluto (nunca so um R-multiplo)
    e com corte de horizonte OPCIONAL (None = sem corte, varre at'e o fim de `bars`)."""
    for idx in range(j0, len(bars)):
        bar = bars[idx]
        if horizonte_ts is not None and bar.ts > horizonte_ts:
            break
        if candle_corrompido_provavel(bars, idx):
            continue
        if bar.low <= stop:
            return "stop"
        if bar.high >= preco_alvo:
            return "alvo"
    return None


@dataclasses.dataclass
class ResumoB1:
    n: int
    distancia_pct_media: Optional[float]
    distancia_r_media: Optional[float]
    por_horizonte: dict[str, dict[str, Any]]


def resumo_b1_topo_anterior(sinais: list[SinalAuditoria]) -> ResumoB1:
    distancias_pct = []
    distancias_r = []
    for s in sinais:
        risk = s.entry_price - s.stop
        if risk <= 0:
            continue
        distancias_pct.append(100.0 * (s.topo - s.entry_price) / s.entry_price)
        distancias_r.append((s.topo - s.entry_price) / risk)
    por_horizonte: dict[str, dict[str, Any]] = {}
    for nome, horizonte_s in HORIZONTES_B.items():
        resultados = []
        for s in sinais:
            risk = s.entry_price - s.stop
            if risk <= 0:
                continue
            horizonte_ts = (s.t_entrada + horizonte_s) if horizonte_s is not None else None
            resultados.append(_toque_preco_causal(s.bars, s.j0, s.stop, s.topo, horizonte_ts))
        decididos = [r for r in resultados if r is not None]
        n_alvo = sum(1 for r in decididos if r == "alvo")
        n = len(decididos)
        # equilibrio 1/(1+R_topo) POR SINAL (R_topo varia por sinal, nunca 1 numero fixo pro grupo) --
        # media do equilibrio individual, comparavel com a media da taxa observada.
        equilibrios = [100.0 / (1.0 + (s.topo - s.entry_price) / (s.entry_price - s.stop))
                      for s in sinais if (s.entry_price - s.stop) > 0]
        equilibrio_medio = statistics.fmean(equilibrios) if equilibrios else None
        por_horizonte[nome] = {
            "n_decididos": n, "n_indefinido_ou_censurado": len(resultados) - n, "n_alvo": n_alvo,
            "p_observado_pct": (100.0 * n_alvo / n) if n else None, "equilibrio_medio_pct": equilibrio_medio,
        }
    return ResumoB1(
        n=len(sinais), distancia_pct_media=statistics.fmean(distancias_pct) if distancias_pct else None,
        distancia_r_media=statistics.fmean(distancias_r) if distancias_r else None, por_horizonte=por_horizonte,
    )


# ---------------------------------------------------------------------------
# B2: CAUDA -- P(+NR antes de -1R), N=1..20, mesmos horizontes, por token distinto, Clopper-Pearson
# ---------------------------------------------------------------------------


def resumo_b2_cauda(sinais: list[SinalAuditoria]) -> dict[str, dict[float, dict[str, Any]]]:
    out: dict[str, dict[float, dict[str, Any]]] = {}
    for nome, horizonte_s in HORIZONTES_B.items():
        por_alvo: dict[float, dict[str, Any]] = {}
        for alvo in ALVOS_R_B2:
            tokens_com_alvo: set[str] = set()
            n_decididos = 0
            n_alvo = 0
            for s in sinais:
                risk = s.entry_price - s.stop
                if risk <= 0:
                    continue
                preco_alvo = s.entry_price + alvo * risk
                horizonte_ts = (s.t_entrada + horizonte_s) if horizonte_s is not None else None
                r = _toque_preco_causal(s.bars, s.j0, s.stop, preco_alvo, horizonte_ts)
                if r is None:
                    continue
                n_decididos += 1
                if r == "alvo":
                    n_alvo += 1
                    tokens_com_alvo.add(s.token)
            ic_lo, ic_hi = clopper_pearson(n_alvo, n_decididos, confianca=0.90) if n_decididos else (None, None)
            por_alvo[alvo] = {
                "n_decididos": n_decididos, "n_alvo": n_alvo, "n_tokens_com_alvo": len(tokens_com_alvo),
                "p_observado_pct": (100.0 * n_alvo / n_decididos) if n_decididos else None,
                "equilibrio_pct": 100.0 / (1.0 + alvo),
                "ic90_exato_pct": (ic_lo * 100.0, ic_hi * 100.0) if ic_lo is not None else None,
            }
        out[nome] = por_alvo
    return out


# ---------------------------------------------------------------------------
# B3: gestao dos 70% -- stop breakeven / trailing / nenhum ajuste (controle), por alvo R
# ---------------------------------------------------------------------------


def _r_horizonte_sob_regra(s: SinalAuditoria, alvo_r: float, regra: str, now: float) -> Optional[float]:
    """R@72h (MTM) sob a regra de gestao `regra` ('breakeven'|'trailing'|'atual'), a partir do 1o
    candle em que o sinal atinge `alvo_r` CAUSALMENTE (antes do stop ORIGINAL) -- `None` se o sinal
    nunca atinge `alvo_r` antes do stop original, ou se o horizonte de 72h nao decorreu ainda.
    'atual' ('nenhum ajuste') = o stop NUNCA se move (controle; nunca confundido com TP1/EXIT FULL,
    que e sobre realizacao parcial de lucro, nao sobre mover o stop)."""
    risk = s.entry_price - s.stop
    if risk <= 0:
        return None
    preco_alvo = s.entry_price + alvo_r * risk
    idx_atingiu = None
    for idx in range(s.j0, len(s.bars)):
        if candle_corrompido_provavel(s.bars, idx):
            continue
        bar = s.bars[idx]
        if bar.low <= s.stop:
            return None   # tocou o stop ORIGINAL antes de atingir o alvo -- nunca chegou la
        if bar.high >= preco_alvo:
            idx_atingiu = idx
            break
    if idx_atingiu is None:
        return None
    ts_corte = s.t_entrada + HORIZONTES_S["72h"]
    if now < ts_corte:
        return None   # pendente -- horizonte ainda nao decorreu
    stop_dinamico = s.entry_price if regra == "breakeven" else s.stop
    ultimo_fechamento: Optional[float] = None
    for idx in range(idx_atingiu, len(s.bars)):
        bar = s.bars[idx]
        if bar.ts > ts_corte:
            break
        if candle_corrompido_provavel(s.bars, idx):
            continue
        if regra == "trailing" and idx > idx_atingiu:
            stop_dinamico = max(stop_dinamico, s.bars[idx - 1].low)
        if bar.low <= stop_dinamico:
            saida = max(stop_dinamico, bar.low)
            return (saida - s.entry_price) / risk
        ultimo_fechamento = bar.close
    if ultimo_fechamento is None:
        return None
    return (ultimo_fechamento - s.entry_price) / risk   # nunca tocou o stop dinamico -- marca no corte


@dataclasses.dataclass
class ResumoB3Alvo:
    n_atingiu: int
    media_r_breakeven: Optional[float]
    media_r_trailing: Optional[float]
    media_r_atual: Optional[float]
    mediana_fracao_preservada_breakeven: Optional[float]
    mediana_fracao_preservada_trailing: Optional[float]
    mediana_fracao_preservada_atual: Optional[float]


def resumo_b3_gestao(sinais: list[SinalAuditoria], now: float) -> dict[float, ResumoB3Alvo]:
    out: dict[float, ResumoB3Alvo] = {}
    for alvo in ALVOS_R_B3:
        rs: dict[str, list[float]] = {"breakeven": [], "trailing": [], "atual": []}
        fracoes: dict[str, list[float]] = {"breakeven": [], "trailing": [], "atual": []}
        n_atingiu = 0
        for s in sinais:
            valores = {regra: _r_horizonte_sob_regra(s, alvo, regra, now) for regra in rs}
            if all(v is None for v in valores.values()):
                continue   # nunca atingiu o alvo (ou ainda pendente) -- fora da amostra deste alvo
            atingiu_de_verdade = any(v is not None for v in valores.values())
            if not atingiu_de_verdade:
                continue
            n_atingiu += 1
            for regra, v in valores.items():
                if v is not None:
                    rs[regra].append(v)
                    fracoes[regra].append(v / alvo)
        out[alvo] = ResumoB3Alvo(
            n_atingiu=n_atingiu,
            media_r_breakeven=statistics.fmean(rs["breakeven"]) if rs["breakeven"] else None,
            media_r_trailing=statistics.fmean(rs["trailing"]) if rs["trailing"] else None,
            media_r_atual=statistics.fmean(rs["atual"]) if rs["atual"] else None,
            mediana_fracao_preservada_breakeven=statistics.median(fracoes["breakeven"]) if fracoes["breakeven"] else None,
            mediana_fracao_preservada_trailing=statistics.median(fracoes["trailing"]) if fracoes["trailing"] else None,
            mediana_fracao_preservada_atual=statistics.median(fracoes["atual"]) if fracoes["atual"] else None,
        )
    return out


# ---------------------------------------------------------------------------
# B3b: variantes de saida pos-TP1 e alvo proximo (exploratorio, SEM escolher vencedora)
#
# (a) TP1 de 30% no 1o power candle apos a entrada OU no topo da caixa (R), em vez do TOPO anterior
#     (P_peak) com exaustao -- trigger MAIS PROXIMO/conservador que a regra oficial, nunca a altera.
# (b) apos o TP1, breakeven do restante (70%) no preco de entrada.
# (c) apos o TP1, saida do restante no 1o fechamento de 1h abaixo do "fundo estrutural" (fundo mais
#     alto confirmado -- swing low causal: bars[k].low < vizinhos, so confirmado 1 candle depois) OU
#     de uma linha de tendencia de alta (regressao linear simples pelos fundos estruturais
#     confirmados, extrapolada pro candle atual) -- usa-se o MAIOR dos dois (mais protetor).
#
# SIMPLIFICACAO EXPLICITA (nunca escondida): (b)/(c) sao tratados como um UNICO nivel de stop
# dinamico (SEMPRE testado via `low`, mesma convencao causal de prioridade-do-stop usada em todo o
# projeto) -- em vez de misturar um stop por `low` com um gatilho por `close` no mesmo candle, que
# exigiria uma regra de prioridade NOVA, nunca pre-registrada. R final = media PONDERADA pela fracao
# de cada perna (30% no TP1 + 70% no restante), MESMA convencao de `simulate_v1` pra blender legs.
# ---------------------------------------------------------------------------


def _atr20_antes(bars: list[Bar], idx: int, periodo: int = 20) -> Optional[float]:
    if idx < periodo:
        return None
    trs = []
    for k in range(idx - periodo, idx):
        prev_close = bars[k - 1].close if k > 0 else bars[k].open
        trs.append(max(bars[k].high - bars[k].low, abs(bars[k].high - prev_close), abs(bars[k].low - prev_close)))
    return sum(trs) / periodo


def _trendline_valor(pontos: list[tuple[int, float]], idx: int) -> Optional[float]:
    if len(pontos) < 2:
        return None
    n = len(pontos)
    xs, ys = [p[0] for p in pontos], [p[1] for p in pontos]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / den
    return slope * idx + (mean_y - slope * mean_x)


def _r_b3b_variante(s: SinalAuditoria, horizonte_s: float, now: float, params: Any) -> Optional[float]:
    """`None` = TP1 desta variante nunca realizou (fora da amostra do horizonte) OU pendente."""
    risk = s.entry_price - s.stop
    if risk <= 0:
        return None
    idx_tp1 = None
    for idx in range(s.j0, len(s.bars)):
        if candle_corrompido_provavel(s.bars, idx):
            continue
        bar = s.bars[idx]
        if bar.low <= s.stop:
            return None   # tocou o stop ORIGINAL antes de qualquer TP1 -- nunca realizou
        atr = _atr20_antes(s.bars, idx, periodo=params.atr_period)
        power = atr is not None and (bar.high - bar.low) >= params.power_atr_mult * atr
        rompeu_caixa = s.r_caixa is not None and bar.high >= s.r_caixa
        if power or rompeu_caixa:
            idx_tp1 = idx
            break
    if idx_tp1 is None or idx_tp1 + 1 >= len(s.bars):
        return None
    ts_corte = s.t_entrada + horizonte_s
    if now < ts_corte:
        return None
    leg1_exit = s.bars[idx_tp1 + 1].open
    r_leg1 = (leg1_exit - s.entry_price) / risk
    # restante (70%): breakeven + fundo estrutural (swing low confirmado) + tendencia de alta,
    # SEMPRE testado via `low` (stop dinamico unico, ver nota de simplificacao acima).
    stop_dinamico = s.entry_price
    fundo_estrutural: Optional[float] = None
    pontos_fundo: list[tuple[int, float]] = []
    ultimo_fechamento: Optional[float] = None
    for idx in range(idx_tp1 + 1, len(s.bars)):
        bar = s.bars[idx]
        if bar.ts > ts_corte:
            break
        if candle_corrompido_provavel(s.bars, idx):
            continue
        # swing low CONFIRMADO em idx-1 (precisa do candle idx pra confirmar -- causal, zero lookahead)
        if idx >= 2 and idx - 1 > idx_tp1:
            anterior, atual_baixo, seguinte = s.bars[idx - 2].low, s.bars[idx - 1].low, bar.low
            if atual_baixo < anterior and atual_baixo < seguinte:
                fundo_estrutural = atual_baixo if fundo_estrutural is None else max(fundo_estrutural, atual_baixo)
                pontos_fundo.append((idx - 1, atual_baixo))
        nivel_tendencia = _trendline_valor(pontos_fundo, idx)
        nivel = stop_dinamico
        if fundo_estrutural is not None:
            nivel = max(nivel, fundo_estrutural)
        if nivel_tendencia is not None:
            nivel = max(nivel, nivel_tendencia)
        if bar.low <= nivel:
            saida = max(nivel, bar.low)
            r_leg2 = (saida - s.entry_price) / risk
            return 0.30 * r_leg1 + 0.70 * r_leg2
        ultimo_fechamento = bar.close
    if ultimo_fechamento is None:
        return 0.30 * r_leg1   # restante nunca abriu (corte logo no candle do TP1) -- so a 1a perna
    r_leg2 = (ultimo_fechamento - s.entry_price) / risk   # nunca saiu -- marca no corte do horizonte
    return 0.30 * r_leg1 + 0.70 * r_leg2


@dataclasses.dataclass
class ResumoB3bHorizonte:
    n_sinais: int
    n_tp1_realizado: int
    frac_tp1_pct: Optional[float]
    pareamento: "vv3.Pareamento"


def resumo_b3b_variantes_saida(sinais: list[SinalAuditoria], now: float, params: Any
                               ) -> dict[str, ResumoB3bHorizonte]:
    out: dict[str, ResumoB3bHorizonte] = {}
    for nome, horizonte_s in (("72h", HORIZONTES_S["72h"]), ("7d", HORIZONTES_S["7d"])):
        valores_por_token: dict[str, list[float]] = {}
        n_tp1 = 0
        for s in sinais:
            r = _r_b3b_variante(s, horizonte_s, now, params)
            if r is None:
                continue
            n_tp1 += 1
            valores_por_token.setdefault(s.token, []).append(r)
        frac = (100.0 * n_tp1 / len(sinais)) if sinais else None
        out[nome] = ResumoB3bHorizonte(n_sinais=len(sinais), n_tp1_realizado=n_tp1, frac_tp1_pct=frac,
                                       pareamento=vv3._resumir_pareamento(valores_por_token))
    return out


# ---------------------------------------------------------------------------
# B4: local da entrada -- quartis de risco%/distancia a S/distancia ao topo da caixa, por gatilho
# ---------------------------------------------------------------------------


def _quartis(valores: list[float]) -> Optional[tuple[float, float, float, float, float]]:
    if not valores:
        return None
    ordenados = sorted(valores)
    q = statistics.quantiles(ordenados, n=4, method="inclusive") if len(ordenados) >= 2 else [ordenados[0]] * 3
    return (ordenados[0], q[0], q[1], q[2], ordenados[-1])


@dataclasses.dataclass
class ResumoB4Gatilho:
    n: int
    risco_pct_quartis: Optional[tuple[float, ...]]
    dist_suporte_pct_quartis: Optional[tuple[float, ...]]
    dist_topo_caixa_pct_quartis: Optional[tuple[float, ...]]
    dist_topo_caixa_alturas_quartis: Optional[tuple[float, ...]]
    n_acima_topo_caixa: int


def resumo_b4_local_entrada(sinais: list[SinalAuditoria]) -> dict[str, ResumoB4Gatilho]:
    por_gatilho: dict[str, list[SinalAuditoria]] = {}
    for s in sinais:
        chave = "/".join(sorted(s.gatilhos)) if s.gatilhos else "(sem_gatilho_registrado)"
        por_gatilho.setdefault(chave, []).append(s)
    out: dict[str, ResumoB4Gatilho] = {}
    for chave, lst in por_gatilho.items():
        riscos = [100.0 * s.risk_frac for s in lst]
        dist_s_pct, dist_topo_pct, dist_topo_alturas = [], [], []
        n_acima = 0
        for s in lst:
            if s.s_val is not None and s.s_val > 0:
                dist_s_pct.append(100.0 * (s.entry_price - s.s_val) / s.s_val)
            if s.r_caixa is not None and s.r_caixa > 0 and s.s_val is not None:
                dist_topo_pct.append(100.0 * (s.r_caixa - s.entry_price) / s.r_caixa)
                altura = s.r_caixa - s.s_val
                if altura > 0:
                    dist_topo_alturas.append((s.r_caixa - s.entry_price) / altura)
                if s.entry_price > s.r_caixa:
                    n_acima += 1
        out[chave] = ResumoB4Gatilho(
            n=len(lst), risco_pct_quartis=_quartis(riscos), dist_suporte_pct_quartis=_quartis(dist_s_pct),
            dist_topo_caixa_pct_quartis=_quartis(dist_topo_pct),
            dist_topo_caixa_alturas_quartis=_quartis(dist_topo_alturas), n_acima_topo_caixa=n_acima,
        )
    return out


# ---------------------------------------------------------------------------
# B5: fill_gaps -- candles preenchidos (Bar.filled) dentro da janela da caixa
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResumoB5:
    n_sinais: int
    n_com_candle_preenchido_na_caixa: int
    n_sem_box_inicio_conhecido: int
    tokens_afetados: list[str]


def resumo_b5_fill_gaps(sinais: list[SinalAuditoria]) -> ResumoB5:
    n_com = 0
    n_sem_box = 0
    tokens: list[str] = []
    for s in sinais:
        if s.box_inicio_idx is None or s.box_inicio_idx < 0:
            n_sem_box += 1
            continue
        janela = s.bars[s.box_inicio_idx:s.gatilho_idx + 1]
        if any(b.filled for b in janela):
            n_com += 1
            tokens.append(s.token)
    return ResumoB5(n_sinais=len(sinais), n_com_candle_preenchido_na_caixa=n_com,
                    n_sem_box_inicio_conhecido=n_sem_box, tokens_afetados=sorted(set(tokens)))


def diagnostico_b5_sem_candles_preenchidos(sinais: list[SinalAuditoria], now: float, params: Any,
                                           costs: CostModel) -> list[str]:
    """Replay DIAGNOSTICO (NUNCA altera a V3): recalcula volume medio da caixa e R@72h excluindo os
    candles `filled` da MEDIA DE VOLUME/ATR -- so pra ver se algum sinal MUDA ou SOME (vira
    `risco_irrealista`/sem triggers por volume) quando o preenchido artificial sai da conta. Nunca
    reavalia o detector em si (zero mudanca de ENTRADA/criterio)."""
    out: list[str] = []
    for s in sinais:
        if s.box_inicio_idx is None or s.box_inicio_idx < 0:
            continue
        janela = s.bars[s.box_inicio_idx:s.gatilho_idx + 1]
        preenchidos = [b for b in janela if b.filled]
        if not preenchidos:
            continue
        limpos = [b for b in janela if not b.filled]
        media_com = statistics.fmean(b.volume for b in janela) if janela else 0.0
        media_sem = statistics.fmean(b.volume for b in limpos) if limpos else None
        diff_pct = (100.0 * (media_sem - media_com) / media_com) if (media_sem is not None and media_com) else None
        diff_txt = f"{diff_pct:+.1f}%" if diff_pct is not None else "s/d (so havia preenchido na janela)"
        out.append(f"  {s.token} ({s.origem}): {len(preenchidos)}/{len(janela)} candles preenchidos na "
                  f"caixa -- media de volume sem eles muda {diff_txt}")
    return out


# ---------------------------------------------------------------------------
# B6: power candle descomunal -- razao corpo/altura da caixa e corpo/(pico-topo da caixa)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResumoB6:
    n: int
    razao_corpo_caixa_quartis: Optional[tuple[float, ...]]
    razao_corpo_pico_topo_quartis: Optional[tuple[float, ...]]
    por_quartil_corpo_caixa: list[dict[str, Any]]


def resumo_b6_power_candle(sinais: list[SinalAuditoria], now: float, params: Any, costs: CostModel) -> ResumoB6:
    itens = []
    for s in sinais:
        if s.r_caixa is None or s.s_val is None:
            continue
        altura_caixa = s.r_caixa - s.s_val
        pico_menos_topo = s.topo - s.r_caixa
        if s.gatilho_idx >= len(s.bars):
            continue
        bar_g = s.bars[s.gatilho_idx]
        corpo = abs(bar_g.close - bar_g.open)
        razao_caixa = (corpo / altura_caixa) if altura_caixa > 0 else None
        razao_pico = (corpo / pico_menos_topo) if pico_menos_topo > 0 else None
        if razao_caixa is None and razao_pico is None:
            continue
        r72 = vv3._r_horizonte(
            vv3.SinalVarredura(token=s.token, mint=s.token, pool=s.token, tf="1h", origem=s.origem, bars=s.bars,
                              ev=EventV1(kind="ENTRADA", idx=s.gatilho_idx, ts=bar_g.ts, decision_ts=bar_g.ts,
                                        data={"stop": s.stop, "TOPO": s.topo, "S": s.s_val}),
                              dex=s.dex, l_bc=s.l_bc, created_ts=None, supply=None, t_entrada=s.t_entrada,
                              entry_price=s.entry_price, entrada_corrigida=False, stop=s.stop, topo=s.topo,
                              s_val=s.s_val, risk_frac=s.risk_frac, volume_gatilho=s.volume_gatilho,
                              volume_entrada=None, volume_medio_24h=s.volume_medio_24h, n_pavios=s.n_testes),
            HORIZONTES_S["72h"], now, params, costs,
        )
        preco_alvo_2r = s.entry_price + 2.0 * (s.entry_price - s.stop)
        toque_2r = _toque_preco_causal(s.bars, s.j0, s.stop, preco_alvo_2r)
        itens.append((razao_caixa, razao_pico, r72, toque_2r))
    razoes_caixa = [i[0] for i in itens if i[0] is not None]
    razoes_pico = [i[1] for i in itens if i[1] is not None]
    por_quartil: list[dict[str, Any]] = []
    com_razao_caixa = sorted((i for i in itens if i[0] is not None), key=lambda i: i[0])
    if len(com_razao_caixa) >= 4:
        tamanho = len(com_razao_caixa) // 4
        for q in range(4):
            fatia = com_razao_caixa[q * tamanho: (q + 1) * tamanho] if q < 3 else com_razao_caixa[q * tamanho:]
            rs = [i[2] for i in fatia if i[2] is not None]
            toques = [i[3] for i in fatia if i[3] is not None]
            n_alvo = sum(1 for t in toques if t == "alvo")
            por_quartil.append({
                "quartil": q + 1, "n": len(fatia), "razao_corpo_caixa_media": statistics.fmean(i[0] for i in fatia),
                "r72h_medio": statistics.fmean(rs) if rs else None,
                "p_2r_antes_de_1r_pct": (100.0 * n_alvo / len(toques)) if toques else None,
            })
    return ResumoB6(
        n=len(itens), razao_corpo_caixa_quartis=_quartis(razoes_caixa), razao_corpo_pico_topo_quartis=_quartis(razoes_pico),
        por_quartil_corpo_caixa=por_quartil,
    )


# ---------------------------------------------------------------------------
# B8: maturacao -- R@72h e P(+2R antes de -1R) por quartil de duracao da caixa e por faixa de idade
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResumoB8:
    por_quartil_duracao: list[dict[str, Any]]
    por_faixa_idade: dict[str, dict[str, Any]]


def resumo_b8_maturacao(sinais: list[SinalAuditoria], now: float, params: Any, costs: CostModel) -> ResumoB8:
    def _r72_e_toque(s: SinalAuditoria) -> tuple[Optional[float], Optional[str]]:
        r = calcular_r_horizonte(s.bars, EventV1(kind="ENTRADA", idx=s.gatilho_idx, ts=s.bars[s.gatilho_idx].ts,
                                                 decision_ts=s.bars[s.gatilho_idx].ts,
                                                 data={"stop": s.stop, "TOPO": s.topo, "S": s.s_val}),
                                 params, costs, s.dex, s.l_bc, t_entrada=s.t_entrada,
                                 horizonte_s=HORIZONTES_S["72h"], now=now)
        preco_alvo_2r = s.entry_price + 2.0 * (s.entry_price - s.stop)
        toque = _toque_preco_causal(s.bars, s.j0, s.stop, preco_alvo_2r)
        return r.r_mult, toque

    com_duracao = sorted((s for s in sinais if s.caixa_horas is not None), key=lambda s: s.caixa_horas)
    por_quartil: list[dict[str, Any]] = []
    if len(com_duracao) >= 4:
        tamanho = len(com_duracao) // 4
        for q in range(4):
            fatia = com_duracao[q * tamanho:(q + 1) * tamanho] if q < 3 else com_duracao[q * tamanho:]
            pares = [_r72_e_toque(s) for s in fatia]
            rs = [p[0] for p in pares if p[0] is not None]
            toques = [p[1] for p in pares if p[1] is not None]
            n_alvo = sum(1 for t in toques if t == "alvo")
            por_quartil.append({
                "quartil": q + 1, "n": len(fatia),
                "caixa_horas_media": statistics.fmean(s.caixa_horas for s in fatia),
                "r72h_medio": statistics.fmean(rs) if rs else None,
                "p_2r_antes_de_1r_pct": (100.0 * n_alvo / len(toques)) if toques else None,
            })
    faixas = {"<2d": (0.0, 2.0), "2-7d": (2.0, 7.0), ">7d": (7.0, float("inf"))}
    por_faixa: dict[str, dict[str, Any]] = {}
    for nome, (lo, hi) in faixas.items():
        lst = [s for s in sinais if s.idade_dias is not None and lo <= s.idade_dias < hi]
        pares = [_r72_e_toque(s) for s in lst]
        rs = [p[0] for p in pares if p[0] is not None]
        toques = [p[1] for p in pares if p[1] is not None]
        n_alvo = sum(1 for t in toques if t == "alvo")
        por_faixa[nome] = {
            "n": len(lst), "r72h_medio": statistics.fmean(rs) if rs else None,
            "p_2r_antes_de_1r_pct": (100.0 * n_alvo / len(toques)) if toques else None,
        }
    return ResumoB8(por_quartil_duracao=por_quartil, por_faixa_idade=por_faixa)


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _fmt_quartis(q: Optional[tuple[float, ...]], casas: int = 2) -> str:
    if q is None:
        return "s/d"
    nomes = ("min", "q1", "mediana", "q3", "max")
    return " | ".join(f"{n}={v:.{casas}f}" for n, v in zip(nomes, q))


def formatar_origem(sinais: list[SinalAuditoria], origem_label: str, now: float) -> list[str]:
    out = [f"## {origem_label}", "", f"n sinais: {len(sinais)}", ""]
    if not sinais:
        out.append("(sem sinais nesta origem)")
        out.append("")
        return out
    params = load_params_v3()
    costs = CostModel()

    b1 = resumo_b1_topo_anterior(sinais)
    out.append(f"### B1 -- TOPO anterior: distancia media={b1.distancia_pct_media:.1f}% "
              f"({b1.distancia_r_media:.2f}R)" if b1.distancia_pct_media is not None else "### B1 -- s/d")
    for nome, d in b1.por_horizonte.items():
        p_txt = f"{d['p_observado_pct']:.1f}%" if d["p_observado_pct"] is not None else "s/d"
        eq_txt = f"{d['equilibrio_medio_pct']:.1f}%" if d["equilibrio_medio_pct"] is not None else "s/d"
        out.append(f"  {nome}: alcanca o topo antes do stop = {p_txt} (n={d['n_decididos']}, "
                  f"censurado/indefinido={d['n_indefinido_ou_censurado']}) | equilibrio medio="
                  f"{eq_txt}")
    out.append("")

    out.append("### B2 -- CAUDA: P(+NR antes de -1R), IC90% exato (Clopper-Pearson)")
    b2 = resumo_b2_cauda(sinais)
    for nome, por_alvo in b2.items():
        out.append(f"  horizonte={nome}:")
        for alvo, d in sorted(por_alvo.items()):
            p_txt = f"{d['p_observado_pct']:.1f}%" if d["p_observado_pct"] is not None else "s/d"
            ic_txt = f"[{d['ic90_exato_pct'][0]:.1f},{d['ic90_exato_pct'][1]:.1f}]" if d["ic90_exato_pct"] else "s/d"
            out.append(f"    +{alvo:.0f}R: observado={p_txt} IC90%={ic_txt} (n={d['n_decididos']}, "
                      f"tokens={d['n_tokens_com_alvo']}) | equilibrio={d['equilibrio_pct']:.1f}%")
    out.append("")

    out.append("### B3 -- gestao dos 70% (breakeven apos alvo / trailing / nenhum ajuste=controle)")
    b3 = resumo_b3_gestao(sinais, now)
    for alvo, r in b3.items():
        if r.n_atingiu == 0:
            out.append(f"  +{alvo:.0f}R: nenhum sinal atingiu (ou tudo pendente)")
            continue
        out.append(f"  +{alvo:.0f}R (n={r.n_atingiu}):")
        for regra, media, frac in (
            ("breakeven", r.media_r_breakeven, r.mediana_fracao_preservada_breakeven),
            ("trailing", r.media_r_trailing, r.mediana_fracao_preservada_trailing),
            ("atual (controle)", r.media_r_atual, r.mediana_fracao_preservada_atual),
        ):
            media_txt = f"{media:+.2f}R" if media is not None else "s/d"
            frac_txt = f"{frac * 100.0:.0f}%" if frac is not None else "s/d"
            out.append(f"    {regra}: media={media_txt} | mediana da fracao do alvo preservada={frac_txt}")
    out.append("")

    out.append("### B3b -- variantes de saida pos-TP1 e alvo proximo (exploratorio, sem escolher vencedora)")
    out.append("  (a) TP1 no 1o power candle OU no topo da caixa (R), em vez do TOPO anterior; "
              "(b) breakeven do restante; (c) saida no fundo estrutural/tendencia de alta")
    b3b = resumo_b3b_variantes_saida(sinais, now, params)
    for horizonte, r in b3b.items():
        frac_txt = f"{r.frac_tp1_pct:.1f}%" if r.frac_tp1_pct is not None else "s/d"
        out.append(f"  horizonte={horizonte}: TP1 desta variante realizou em {r.n_tp1_realizado}/"
                  f"{r.n_sinais} ({frac_txt})")
        out.append("    " + vv3._formatar_pareamento("R final (30% TP1 + 70% restante)", r.pareamento,
                                                     rotulo_n="n_tp1"))
    out.append("")

    out.append("### B4 -- local da entrada, por tipo de gatilho")
    b4 = resumo_b4_local_entrada(sinais)
    for gatilho, r in sorted(b4.items()):
        out.append(f"  {gatilho} (n={r.n}):")
        out.append(f"    risco%: {_fmt_quartis(r.risco_pct_quartis, 1)}")
        out.append(f"    distancia ao suporte S (%): {_fmt_quartis(r.dist_suporte_pct_quartis, 1)}")
        out.append(f"    distancia ao topo da caixa/R (%): {_fmt_quartis(r.dist_topo_caixa_pct_quartis, 1)}")
        out.append(f"    distancia ao topo da caixa (em alturas de caixa): "
                  f"{_fmt_quartis(r.dist_topo_caixa_alturas_quartis, 2)}")
        out.append(f"    entraram ACIMA do topo da caixa: {r.n_acima_topo_caixa}/{r.n}")
    out.append("")

    out.append("### B5 -- fill_gaps (candles preenchidos dentro da janela da caixa)")
    b5 = resumo_b5_fill_gaps(sinais)
    out.append(f"  sinais com >=1 candle preenchido na caixa: {b5.n_com_candle_preenchido_na_caixa}/"
              f"{b5.n_sinais} | sem box_inicio conhecido: {b5.n_sem_box_inicio_conhecido}")
    if b5.tokens_afetados:
        out.append(f"  tokens afetados: {', '.join(b5.tokens_afetados[:15])}"
                  + (", ..." if len(b5.tokens_afetados) > 15 else ""))
    out.append("  diagnostico (replay NUNCA altera a V3, so re-mede a media de volume sem o preenchido):")
    out.extend(diagnostico_b5_sem_candles_preenchidos(sinais, now, params, costs) or ["    (nenhum sinal com candle preenchido na caixa)"])
    out.append("")

    out.append("### B6 -- power candle descomunal (corpo do gatilho / altura da caixa e / (pico-topo))")
    b6 = resumo_b6_power_candle(sinais, now, params, costs)
    out.append(f"  n={b6.n} | corpo/altura_caixa: {_fmt_quartis(b6.razao_corpo_caixa_quartis, 2)} | "
              f"corpo/(pico-topo): {_fmt_quartis(b6.razao_corpo_pico_topo_quartis, 2)}")
    for linha in b6.por_quartil_corpo_caixa:
        r_txt = f"{linha['r72h_medio']:+.2f}" if linha["r72h_medio"] is not None else "s/d"
        p_txt = f"{linha['p_2r_antes_de_1r_pct']:.1f}%" if linha["p_2r_antes_de_1r_pct"] is not None else "s/d"
        out.append(f"    quartil {linha['quartil']} (n={linha['n']}, razao media="
                  f"{linha['razao_corpo_caixa_media']:.2f}): R@72h medio={r_txt} | P(+2R antes -1R)={p_txt}")
    out.append("")

    out.append("### B7 -- preco de entrada real vs modelado (ao vivo)")
    if origem_label == "ao_vivo":
        out.append("  NAO CALCULAVEL com os dados atuais: `pr3_signals.entry_price_alerta` fica "
                  "SEMPRE NULL pra V3 (documentado em storage.py -- a V3 nunca grava o preco "
                  "observado no instante do alerta separado do preco do candle modelado). "
                  "Instrumentar isso exige um campo novo gravado ao vivo, fora do escopo de um "
                  "script read-only.")
    else:
        out.append("  (so se aplica a ao_vivo -- esta origem nao tem alerta em tempo real)")
    out.append("")

    out.append("### B8 -- maturacao (R@72h e P(+2R antes -1R) por quartil de duracao da caixa e por idade)")
    b8 = resumo_b8_maturacao(sinais, now, params, costs)
    for linha in b8.por_quartil_duracao:
        r_txt = f"{linha['r72h_medio']:+.2f}" if linha["r72h_medio"] is not None else "s/d"
        p_txt = f"{linha['p_2r_antes_de_1r_pct']:.1f}%" if linha["p_2r_antes_de_1r_pct"] is not None else "s/d"
        out.append(f"  quartil duracao {linha['quartil']} (n={linha['n']}, "
                  f"caixa_horas media={linha['caixa_horas_media']:.1f}h): R@72h medio={r_txt} | "
                  f"P(+2R antes -1R)={p_txt}")
    for faixa, d in b8.por_faixa_idade.items():
        r_txt = f"{d['r72h_medio']:+.2f}" if d["r72h_medio"] is not None else "s/d"
        p_txt = f"{d['p_2r_antes_de_1r_pct']:.1f}%" if d["p_2r_antes_de_1r_pct"] is not None else "s/d"
        out.append(f"  idade {faixa} (n={d['n']}): R@72h medio={r_txt} | P(+2R antes -1R)={p_txt}")
    out.append("")
    return out


def executar(db_path: Path, progresso: bool = True) -> str:
    import sys as _sys

    def status(msg: str) -> None:
        if progresso:
            print(f"[auditoria_fidelidade_v3] {msg}", file=_sys.stderr, flush=True)

    now = time.time()
    status("carregando ao_vivo...")
    ao_vivo = carregar_ao_vivo(db_path)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = carregar_retro_lote1(db_path)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (pode levar um tempo)...")
    replay = carregar_replay_v3(db_path)
    status(f"replay_v3: {len(replay)} sinais. montando relatorio...")
    out = ["# auditoria_fidelidade_v3 -- fidelidade a estrategia do professor (B1-B8)", "",
          f"AVISO: {AVISO}", ""]
    for sinais, label in ((ao_vivo, "ao_vivo"), (retro, "retro_lote1"), (replay, "replay_v3")):
        out.extend(formatar_origem(sinais, label, now))
    out.append(f"({AVISO})")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auditoria de fidelidade a estrategia do professor (B1-B8) -- PAPER/so leitura/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    args = parser.parse_args(argv)
    print(executar(args.db, progresso=not args.sem_progresso))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
