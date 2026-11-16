"""RODADA 23 (pedido 2026-11-17): RECONCILIACAO AO VIVO + PROFUNDIDADE DO STOP. PAPER/READ-ONLY.

Somente leitura do banco (mesmo `conectar_ro`/`Storage` sem `__init__` de `fase_a_vm.py`: `mode=ro` +
`query_only`, qualquer escrita falha). Zero rede. `os.nice(19)`. Nunca altera detector, parametros,
H1, hashes nem tabela alguma.

(1) RECONCILIACAO: para TODO sinal ENTRADA de V1/V2/V3 (qualquer status, inclusive `perdido_offline`),
    recalcula R@72h e R@7d marcado a mercado a partir de `pr_bars`, com a funcao OFICIAL
    `pos_runner.horizonte_fixo.calcular_r_horizonte` (mesmo custo offline e veto amplo do motor
    persistido). Compara lado a lado com:
      - H1 legado: `pr_baseline.r_sinal`/`dif_pareada` (so existe para `status='fechado'`);
      - horizonte fixo PERSISTIDO: `pr_horizonte_fixo` (versao, 'ao_vivo', id, horizonte);
    e classifica cada divergencia (ver `classificar`). Agrega por TOKEN (1a tentativa = menor
    `ts_fechamento` por mint, por versao): media, mediana, IC bootstrap por token, leave-one-token-out.
    POOL MORTO (restante MARCADO num preco sem negocio ha >=24h no fim dos dados): reporta tambem a
    sensibilidade "-100%" (fracao ainda aberta vale zero; pernas ja realizadas, ex. TP1, mantidas).
    CENSURADO (rastreio parou antes do corte -- pool saiu de 'ativo', ex. idade maxima -- com o pool
    ainda negociando): so marcado, contado a parte, sem -100% (nao ha evidencia de morte).
(2) PROFUNDIDADE DO STOP: para cada sinal ao vivo fechado por stop, localiza o candle do stop
    reexecutando `simulate_v1` (veto amplo) sobre `pr_bars`; mede (stop - low)/stop e recalcula o R
    com a venda do stop em 3 pontos: oficial (min(open, stop)), meio (media entre o fill oficial e o
    low) e low (pior caso do candle).

(3) FUNIL DE DESCOBERTA: candidatos/dia por lista do GT, ocupacao da fila/vagas, bloqueios e chamadas.

LIMITES DECLARADOS: custo = `CostModel()` offline (sol_usd=None, teto de fee + 1% de slippage) -- o
`result_net` ao vivo usou a cotacao SOL/USD cacheada; o veto offline nao tem o cruzamento DexPaprika do
ao vivo. Por isso o R recalculado pode diferir do ao vivo mesmo com os mesmos candles; a coluna
`r_regra_offline` isola essa parte (regra sem corte, custo offline) para a comparacao com o legado.

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.reconciliacao_ao_vivo --db signals_mvp/dados/estado.sqlite
    python -m signals_mvp.scripts.reconciliacao_ao_vivo --db signals_mvp/dados/estado.sqlite --csv ~/reconciliacao.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.horizonte_fixo import HORIZONTES_S, RISCO_IRREALISTA_MIN_PCT, calcular_r_horizonte
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.qualidade_candle import candle_confiavel_cb
from ..pos_runner.simulate_v1 import simulate_v1
from .exit_lab import _net_de_legs
from .fase_a_vm import TABELA_SINAIS, VERSOES, _fmt_ts, _quantis, _storage_somente_leitura, conectar_ro

PARAMS = {"v1": load_params_v1, "v2": load_params_v2, "v3": load_params_v3}
MORTO_SEM_NEGOCIO_S = 24 * 3600.0          # mesmo limiar de `live.RETIRADA_SEM_CANDLE_H`
TOL = 1e-6


@dataclass
class LinhaHorizonte:
    status: str
    r: Optional[float] = None
    marca_ts: Optional[float] = None
    morto: bool = False
    censurado: bool = False
    motivo_morto: str = ""
    r_menos100: Optional[float] = None
    persist_status: Optional[str] = None
    persist_r: Optional[float] = None
    persist_calc_ts: Optional[float] = None
    persist_marca_ts: Optional[float] = None
    divergencia: str = ""


@dataclass
class LinhaSinal:
    versao: str
    id: int
    symbol: str
    mint: str
    pool: str
    status_sinal: str
    pool_status: str
    pool_motivo: str
    ts_fechamento: int
    primeira_tentativa: bool = False
    t_entrada: Optional[float] = None
    risco_frac: Optional[float] = None
    n_candles: int = 0
    fim_serie_ts: Optional[float] = None
    situacao: str = "ok"                       # ok | sem_candles | sem_candle_entrada | risco<3%
    r_live_regra: Optional[float] = None       # result_net / risco (custo AO VIVO, saida pela regra)
    h1_r_sinal: Optional[float] = None
    h1_dif_pareada: Optional[float] = None
    r_regra_offline: Optional[float] = None    # simulate_v1 na serie inteira, custo offline (sem corte)
    status_regra_offline: str = ""
    horizontes: dict[str, LinhaHorizonte] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _bars(st: Any, pool: str, tf: str) -> list[Bar]:
    return [Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], bool(r[6])) for r in st.pr_bars(pool, tf)]


def _evento(bars: list[Bar], j0: int, sinal: Any) -> EventV1:
    return EventV1("ENTRADA", j0 - 1, bars[j0 - 1].ts, int(sinal["ts_fechamento"]),
                   {"stop": sinal["stop"], "TOPO": sinal["topo"], "S": sinal["s_suporte"]})


def _simular(bars: list[Bar], ev: EventV1, params: Any, costs: CostModel, dex: str, l_bc: Optional[float]):
    return simulate_v1(bars, ev, params, costs, dex, l_bc, lambda _t: None,
                       candle_confiavel=candle_confiavel_cb(bars, ev.data.get("TOPO")))


def _r(net: Optional[float], risco: Optional[float]) -> Optional[float]:
    if net is None or not risco or 100.0 * risco < RISCO_IRREALISTA_MIN_PCT:
        return None
    return net / risco


def r_menos100(bars_trunc: list[Bar], ev: EventV1, params: Any, costs: CostModel, dex: str,
               l_bc: Optional[float]) -> Optional[float]:
    """Sensibilidade de pool morto: pernas ja realizadas (stop/TP1/exit) mantidas; a fracao AINDA
    aberta no corte vale ZERO (perda total do principal restante, custo de saida nenhum)."""
    res = _simular(bars_trunc, ev, params, costs, dex, l_bc)
    if res.entry_price is None or res.entry_cost_pct is None or res.status == "cancelado":
        return None
    legs = [(leg.frac, leg.price, leg.cost_pct) for leg in res.legs]
    restante = 1.0 - sum(f for f, _, _ in legs)
    net = _net_de_legs(legs + ([(restante, 0.0, 0.0)] if restante > 1e-9 else []), res.entry_price,
                       res.entry_cost_pct)
    return _r(net, res.risk_frac)


def classificar(h: LinhaHorizonte, situacao: str) -> str:
    """Por que o R recalculado difere do PERSISTIDO (pr_horizonte_fixo)."""
    if situacao == "sem_candles":
        return "sem_candles_hoje (podados) -> vale o persistido; nao reproduzivel"
    if h.persist_status is None:
        return "nao_persistido (horizonte_fixo nunca calculou este sinal)"
    if h.persist_status == "pendente" and h.status != "pendente":
        return "persistido_desatualizado (era pendente quando calculado)"
    mesmo_r = (h.persist_r is None and h.r is None) or (
        h.persist_r is not None and h.r is not None and abs(h.persist_r - h.r) < TOL)
    if h.persist_status == h.status and mesmo_r:
        return "igual"
    if (h.persist_marca_ts is not None and h.marca_ts is not None and h.marca_ts > h.persist_marca_ts):
        return "candles_novos_apos_o_calculo (marca andou)"
    if h.persist_status == "marcado" and h.status == "resolvido_regra":
        return "regra_fechou_depois_do_calculo"
    return "outro (ver valores lado a lado)"


def _bootstrap_media(valores: list[float], n_boot: int, seed: int, conf: float) -> Optional[tuple[float, float]]:
    import numpy as np
    if len(valores) < 2:
        return None
    rng = np.random.default_rng(seed)
    arr = np.asarray(valores, dtype=float)
    medias = arr[rng.integers(0, len(arr), size=(n_boot, len(arr)))].mean(axis=1)
    a = (1.0 - conf) / 2.0
    return float(np.percentile(medias, 100 * a)), float(np.percentile(medias, 100 * (1 - a)))


def resumo_tokens(rotulo: str, valores: dict[str, float]) -> str:
    """1 valor por token (1a tentativa). Media, mediana, IC bootstrap, leave-one-token-out."""
    from ..analise.condicional import CONFIANCA_H1, N_BOOTSTRAP_PADRAO, SEED_PADRAO
    v = list(valores.values())
    if not v:
        return f"  {rotulo}: n=0 tokens"
    media = statistics.fmean(v)
    ic = _bootstrap_media(v, N_BOOTSTRAP_PADRAO, SEED_PADRAO, CONFIANCA_H1)
    loo = [statistics.fmean([x for k, x in valores.items() if k != tok]) for tok in valores] if len(v) > 1 else []
    melhor = max(valores, key=valores.get)
    ic_txt = f"IC{int(100 * CONFIANCA_H1)}% [{ic[0]:+.2f}; {ic[1]:+.2f}]" if ic else "IC s/d (n<2)"
    loo_txt = (f"leave-one-token-out min={min(loo):+.2f} max={max(loo):+.2f}; sem o melhor token "
               f"({melhor[:6]}…)={statistics.fmean([x for k, x in valores.items() if k != melhor]):+.2f}"
               if loo else "")
    return (f"  {rotulo}: n={len(v)} tokens | media={media:+.2f}R mediana={statistics.median(v):+.2f}R | "
            f"{ic_txt} | {loo_txt}")


# ---------------------------------------------------------------------------
# (1) reconciliacao
# ---------------------------------------------------------------------------


def reconciliar(st: Any, con: Any, now: float) -> list[LinhaSinal]:
    costs = CostModel()
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    linhas: list[LinhaSinal] = []
    for versao in VERSOES:
        tabela = TABELA_SINAIS[versao]
        if tabela not in tabelas:
            continue
        params = PARAMS[versao]()
        rows = con.execute(
            f"SELECT s.*, p.status AS pool_status, p.motivo AS pool_motivo, p.l_bc AS pool_l_bc FROM {tabela} s "
            "LEFT JOIN pr_pools p ON p.pool = s.pool WHERE s.evento='ENTRADA' ORDER BY s.ts_fechamento, s.id").fetchall()
        primeiro: dict[str, int] = {}
        for r in rows:
            primeiro.setdefault(r["mint"] or r["pool"], r["id"])
        cache: dict[str, list[Bar]] = {}
        for r in rows:
            tf = r["tf"] or params.timeframes[0]
            ls = LinhaSinal(versao, r["id"], r["symbol"] or (r["mint"] or "")[:8], r["mint"] or r["pool"], r["pool"],
                            r["status"], r["pool_status"] or "(sem linha)", r["pool_motivo"] or "",
                            int(r["ts_fechamento"]), primeira_tentativa=(primeiro[r["mint"] or r["pool"]] == r["id"]))
            base = con.execute("SELECT r_sinal, dif_pareada FROM pr_baseline WHERE versao=? AND entry_id=?",
                               (versao, r["id"])).fetchone() if "pr_baseline" in tabelas else None
            if base is not None:
                ls.h1_r_sinal, ls.h1_dif_pareada = base["r_sinal"], base["dif_pareada"]
            if r["status"] == "fechado" and r["result_net"] is not None and r["entry_price"] and r["stop"]:
                ls.r_live_regra = _r(r["result_net"], 1.0 - r["stop"] / r["entry_price"])
            persist = {}
            if "pr_horizonte_fixo" in tabelas:
                for p in con.execute("SELECT * FROM pr_horizonte_fixo WHERE versao=? AND origem='ao_vivo' AND entry_key=?",
                                     (versao, str(r["id"]))):
                    persist[p["horizonte"]] = p
            bars = cache.setdefault(f"{r['pool']}|{tf}", _bars(st, r["pool"], tf))
            ls.n_candles = len(bars)
            ls.fim_serie_ts = bars[-1].ts if bars else None
            j0 = next((k for k, b in enumerate(bars) if b.ts == int(r["ts_fechamento"])), None)
            if not bars:
                ls.situacao = "sem_candles"
            elif j0 is None or j0 <= 0 or r["stop"] is None or r["topo"] is None:
                ls.situacao = "sem_candle_entrada"
            if ls.situacao != "ok":
                for h in HORIZONTES_S:
                    p = persist.get(h)
                    lh = LinhaHorizonte("s/d", persist_status=p["status"] if p else None,
                                        persist_r=p["r_mult"] if p else None,
                                        persist_calc_ts=p["calculado_ts"] if p else None)
                    lh.divergencia = classificar(lh, ls.situacao)
                    ls.horizontes[h] = lh
                linhas.append(ls)
                continue
            ev = _evento(bars, j0, r)
            dex = r["dex"] or "desconhecido"
            l_bc = r["pool_l_bc"]
            ls.t_entrada = bars[j0].ts
            res_full = _simular(bars, ev, params, costs, dex, l_bc)
            ls.risco_frac = res_full.risk_frac
            ls.status_regra_offline = res_full.status
            if res_full.status == "fechado":
                ls.r_regra_offline = _r(res_full.net_ret, res_full.risk_frac)
            if ls.risco_frac is not None and 100.0 * ls.risco_frac < RISCO_IRREALISTA_MIN_PCT:
                ls.situacao = "risco<3%"
            step = tf_seconds(tf)
            for h, h_s in HORIZONTES_S.items():
                res = calcular_r_horizonte(bars, ev, params, costs, dex, l_bc, t_entrada=ls.t_entrada,
                                           horizonte_s=h_s, now=now)
                lh = LinhaHorizonte(res.status, res.r_mult, res.candle_marca_ts)
                corte = ls.t_entrada + h_s
                if res.status == "marcado":
                    trunc = [b for b in bars if b.ts <= corte]
                    fim_dados = min(corte, bars[-1].ts + step)
                    ult_negocio = max((b.ts for b in trunc if b.volume > 0), default=None)
                    if ult_negocio is None or fim_dados - (ult_negocio + step) > MORTO_SEM_NEGOCIO_S:
                        # MORTO: ja sem negocio >=24h antes do fim dos dados -> marcado num preco que
                        # ninguem mais negociava; sensibilidade: fracao aberta vale zero.
                        lh.morto = True
                        lh.motivo_morto = (f"sem negocio ha {(fim_dados - (ult_negocio or ev.ts)) / 3600:.0f}h no fim dos dados")
                        lh.r_menos100 = r_menos100(trunc, ev, params, costs, dex, l_bc)
                    elif bars[-1].ts + step < corte:
                        # CENSURADO: o rastreio parou (pool saiu de 'ativo') antes do corte com o pool
                        # ainda negociando -- valor marcado no ultimo preco conhecido; o resto e desconhecido.
                        lh.censurado = True
                        lh.motivo_morto = f"rastreio parou {(corte - bars[-1].ts - step) / 3600:.0f}h antes do corte"
                p = persist.get(h)
                if p is not None:
                    lh.persist_status, lh.persist_r = p["status"], p["r_mult"]
                    lh.persist_calc_ts, lh.persist_marca_ts = p["calculado_ts"], p["candle_marca_ts"]
                lh.divergencia = classificar(lh, ls.situacao)
                ls.horizontes[h] = lh
            linhas.append(ls)
    return linhas


def _persist(lh: Optional[LinhaHorizonte], f: Any) -> str:
    if lh is None or lh.persist_status is None:
        return "sem linha"
    return f"{lh.persist_status[:4]} {f(lh.persist_r)}"


def formatar_reconciliacao(linhas: list[LinhaSinal]) -> list[str]:
    out = ["## (1) Reconciliacao ao vivo — R@72h/7d recalculado de pr_bars vs H1 legado vs horizonte fixo persistido", ""]
    for versao in VERSOES:
        ls_v = [l for l in linhas if l.versao == versao]
        if not ls_v:
            continue
        por_status: dict[str, int] = {}
        for l in ls_v:
            por_status[l.status_sinal] = por_status.get(l.status_sinal, 0) + 1
        out.append(f"### {versao.upper()}: {len(ls_v)} sinais / {len({l.mint for l in ls_v})} tokens | status={por_status}")
        prim = [l for l in ls_v if l.primeira_tentativa]
        for h in HORIZONTES_S:
            recalc = {l.mint: l.horizontes[h].r for l in prim if l.horizontes.get(h) and l.horizontes[h].r is not None}
            sens = {l.mint: (l.horizontes[h].r_menos100 if l.horizontes[h].morto and l.horizontes[h].r_menos100 is not None
                             else l.horizontes[h].r) for l in prim if l.horizontes.get(h) and l.horizontes[h].r is not None}
            persist = {l.mint: l.horizontes[h].persist_r for l in prim
                       if l.horizontes.get(h) and l.horizontes[h].persist_r is not None}
            n_morto = sum(1 for l in prim if l.horizontes.get(h) and l.horizontes[h].morto)
            n_cens = sum(1 for l in prim if l.horizontes.get(h) and l.horizontes[h].censurado)
            pend = sum(1 for l in prim if l.horizontes.get(h) and l.horizontes[h].status == "pendente")
            out.append(f"- R@{h} (1a tentativa por token; pendentes fora: {pend}; pools mortos: {n_morto}; censurados (rastreio parou com pool vivo): {n_cens})")
            out.append(resumo_tokens("recalculado (pr_bars, MTM)", recalc))
            out.append(resumo_tokens("recalculado, morto=-100%", sens))
            out.append(resumo_tokens("persistido (pr_horizonte_fixo)", persist))
        legado = {l.mint: l.h1_r_sinal for l in prim if l.h1_r_sinal is not None}
        dif = {l.mint: l.h1_dif_pareada for l in prim if l.h1_dif_pareada is not None}
        out.append("- H1 legado (pr_baseline; so fechados com controles resolvidos)")
        out.append(resumo_tokens("r_sinal (regra, custo ao vivo)", legado))
        out.append(resumo_tokens("dif_pareada", dif))
        offline = {l.mint: l.r_regra_offline for l in prim if l.r_regra_offline is not None}
        out.append(resumo_tokens("regra sem corte, custo OFFLINE (isola custo/veto)", offline))
        contagem: dict[str, int] = {}
        for l in ls_v:
            for h, lh in l.horizontes.items():
                chave = f"{h}:{lh.divergencia.split(' ')[0]}"
                contagem[chave] = contagem.get(chave, 0) + 1
        out.append(f"- divergencias recalculado x persistido (todos os sinais): {dict(sorted(contagem.items()))}")
        out.append("")
        out.append("| id | token | 1a? | sinal | pool | R72 recalc | R72 persist | R7d recalc | R7d persist | morto -100% (72h/7d) | R legado | dif legado | R regra offline | divergencia 72h / 7d |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        f = lambda x: "s/d" if x is None else f"{x:+.2f}"
        for l in ls_v:
            h72, h7 = l.horizontes.get("72h"), l.horizontes.get("7d")
            m72 = f(h72.r_menos100) if h72 and h72.morto else ("cens" if h72 and h72.censurado else "-")
            m7 = f(h7.r_menos100) if h7 and h7.morto else ("cens" if h7 and h7.censurado else "-")
            out.append(
                f"| {l.id} | {l.symbol} | {'s' if l.primeira_tentativa else 'n'} | {l.status_sinal} | "
                f"{l.pool_status}{(' (' + l.pool_motivo[:28] + ')') if l.pool_motivo else ''} | "
                f"{(h72.status[:4] + ' ' + f(h72.r)) if h72 else 's/d'} | {_persist(h72, f)} | "
                f"{(h7.status[:4] + ' ' + f(h7.r)) if h7 else 's/d'} | {_persist(h7, f)} | "
                f"{m72} / {m7} | {f(l.h1_r_sinal)} | {f(l.h1_dif_pareada)} | {f(l.r_regra_offline)} | "
                f"{(h72.divergencia.split(' ')[0] if h72 else '-')} / {(h7.divergencia.split(' ')[0] if h7 else '-')}"
                + (f" [{l.situacao}]" if l.situacao != "ok" else ""))
        out.append("")
    return out


# ---------------------------------------------------------------------------
# (2) profundidade do stop
# ---------------------------------------------------------------------------


@dataclass
class LinhaStop:
    versao: str
    id: int
    mint: str
    symbol: str
    primeira_tentativa: bool
    reproduzido: bool
    gap: Optional[bool] = None
    profundidade: Optional[float] = None       # (stop - low) / stop
    r_live: Optional[float] = None
    r_oficial_offline: Optional[float] = None
    r_meio: Optional[float] = None
    r_low: Optional[float] = None
    motivo: str = ""


def profundidade_stops(st: Any, con: Any, linhas_recon: list[LinhaSinal]) -> list[LinhaStop]:
    costs = CostModel()
    prim = {(l.versao, l.id): l.primeira_tentativa for l in linhas_recon}
    out: list[LinhaStop] = []
    for versao in VERSOES:
        tabela = TABELA_SINAIS[versao]
        params = PARAMS[versao]()
        try:
            rows = con.execute(
                f"SELECT s.*, p.l_bc AS pool_l_bc FROM {tabela} s LEFT JOIN pr_pools p ON p.pool=s.pool "
                "WHERE s.evento='ENTRADA' AND s.status='fechado' AND s.reason='stop'").fetchall()
        except Exception:
            continue
        for r in rows:
            ls = LinhaStop(versao, r["id"], r["mint"] or r["pool"], r["symbol"] or "", prim.get((versao, r["id"]), False), False)
            if r["entry_price"] and r["stop"] and r["result_net"] is not None:
                ls.r_live = _r(r["result_net"], 1.0 - r["stop"] / r["entry_price"])
            bars = _bars(st, r["pool"], r["tf"] or "1h")
            j0 = next((k for k, b in enumerate(bars) if b.ts == int(r["ts_fechamento"])), None)
            if not bars or j0 is None or j0 <= 0:
                ls.motivo = "sem_candles" if not bars else "sem_candle_entrada"
                out.append(ls)
                continue
            ev = _evento(bars, j0, r)
            res = _simular(bars, ev, params, costs, r["dex"] or "desconhecido", r["pool_l_bc"])
            pernas_stop = [leg for leg in res.legs if leg.reason == "stop"]
            if res.status != "fechado" or not pernas_stop:
                ls.motivo = f"offline terminou {res.status}/{res.reason or '-'} (veto/custo divergem do ao vivo)"
                out.append(ls)
                continue
            ls.reproduzido = True
            perna = pernas_stop[0]
            barra = bars[perna.idx]
            stop = float(r["stop"])
            ls.gap = barra.open < stop
            ls.profundidade = max(0.0, (stop - barra.low) / stop)
            outras = [(leg.frac, leg.price, leg.cost_pct) for leg in res.legs if leg is not perna]
            fill = perna.price
            for nome, preco in (("r_oficial_offline", fill), ("r_meio", (fill + barra.low) / 2.0), ("r_low", barra.low)):
                net = _net_de_legs(outras + [(perna.frac, preco, perna.cost_pct)], res.entry_price, res.entry_cost_pct)
                setattr(ls, nome, _r(net, res.risk_frac))
            out.append(ls)
    return out


def formatar_stops(stops: list[LinhaStop]) -> list[str]:
    out = ["## (2) Profundidade do stop — (stop - low)/stop no candle que acionou", ""]
    for versao in VERSOES:
        sv = [s for s in stops if s.versao == versao]
        if not sv:
            continue
        rep = [s for s in sv if s.reproduzido]
        out.append(f"### {versao.upper()}: stops ao vivo={len(sv)} ({len({s.mint for s in sv})} tokens); "
                   f"candle reproduzido offline={len(rep)}; com gap (open<stop)={sum(1 for s in rep if s.gap)}")
        for rotulo, grupo in (("todos os stops", rep), ("1a tentativa por token", [s for s in rep if s.primeira_tentativa])):
            if not grupo:
                continue
            prof = [100.0 * s.profundidade for s in grupo if s.profundidade is not None]
            out.append(f"- {rotulo} (n={len(grupo)}): profundidade % {_quantis(prof)}")
            for campo, nome in (("r_live", "R ao vivo"), ("r_oficial_offline", "R oficial (offline)"),
                                ("r_meio", "R venda no meio stop-low"), ("r_low", "R venda no low")):
                vals = [getattr(s, campo) for s in grupo if getattr(s, campo) is not None]
                out.append(f"    {nome}: {_quantis(vals)}" + (f" | media={statistics.fmean(vals):+.2f}" if vals else ""))
        nao = [s for s in sv if not s.reproduzido]
        if nao:
            out.append("- nao reproduzidos: " + "; ".join(f"#{s.id} {s.symbol}: {s.motivo}" for s in nao))
        out.append("")
    return out


# ---------------------------------------------------------------------------
# (3) funil de descoberta
# ---------------------------------------------------------------------------


def funil_descoberta(con: Any) -> list[str]:
    """De onde vem pr_pools e onde ele trava: candidatos por dia e por lista do GT (`info.fonte`),
    ocupacao da fila (QUEUE_MAX) e das vagas (max_pools), bloqueios por vaga e chamadas de descoberta."""
    from ..pos_runner.live import QUEUE_MAX
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = ["## (3) Funil de descoberta (pr_pools e afins)", ""]
    if "pr_pools" not in tabelas:
        return out + ["pr_pools ausente"]
    dias = con.execute(
        "SELECT date(found_ts,'unixepoch') d, COUNT(*) n, SUM(added_ts IS NOT NULL) adm, "
        "GROUP_CONCAT(DISTINCT json_extract(info,'$.fonte')) fontes FROM pr_pools WHERE found_ts IS NOT NULL "
        "GROUP BY d ORDER BY d").fetchall()
    if dias:
        ns = [r["n"] for r in dias]
        out.append(f"- candidatos novos por dia (found_ts): dias={len(dias)} mediana={statistics.median(ns):.0f} "
                   f"min={min(ns)} max={max(ns)} total={sum(ns)}; admitidos (added_ts) total={sum(r['adm'] or 0 for r in dias)}")
        out.append("    " + " ".join(f"{r['d'][5:]}:{r['n']}" for r in dias[-21:]))
    por_fonte = con.execute("SELECT COALESCE(json_extract(info,'$.fonte'),'?') f, COUNT(*) n FROM pr_pools GROUP BY f "
                            "ORDER BY n DESC").fetchall()
    out.append("- por lista de origem: " + ", ".join(f"{r['f']}={r['n']}" for r in por_fonte))
    st = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM pr_pools GROUP BY status")}
    fila = st.get("pendente", 0) + st.get("verificado", 0)
    out.append(f"- agora: fila pendente+verificado={fila}/{QUEUE_MAX} (cheia => offer() para de aceitar candidatos, "
               f"live.py:995) | ativo={st.get('ativo', 0)} | status={st}")
    motivos = con.execute("SELECT motivo, COUNT(*) n FROM pr_pools WHERE motivo IS NOT NULL GROUP BY motivo "
                          "ORDER BY n DESC LIMIT 8").fetchall()
    out.append("- motivos de saida (top 8): " + "; ".join(f"{r['motivo'][:50]}={r['n']}" for r in motivos))
    espera = [r[0] for r in con.execute("SELECT (added_ts - found_ts)/3600.0 FROM pr_pools WHERE added_ts IS NOT NULL "
                                        "AND found_ts IS NOT NULL AND added_ts >= found_ts")]
    if espera:
        out.append(f"- espera descoberta->vaga (h): {_quantis(espera)}")
    if "pr_vaga_descartes" in tabelas:
        vd = con.execute("SELECT date(ts,'unixepoch') d, COUNT(DISTINCT pool) n FROM pr_vaga_descartes GROUP BY d "
                         "ORDER BY d DESC LIMIT 14").fetchall()
        out.append("- pools barrados por vaga (distintos/dia, ultimos 14): " + " ".join(f"{r['d'][5:]}:{r['n']}" for r in vd[::-1]))
    if "pr_api_uso" in tabelas:
        api = con.execute("SELECT date(ts,'unixepoch') d, COUNT(*) n, SUM(rate_limited) rl FROM pr_api_uso "
                          "WHERE fonte='gt' AND finalidade='descoberta' GROUP BY d ORDER BY d DESC LIMIT 7").fetchall()
        out.append("- chamadas GT de descoberta/dia (ultimos 7; 429 entre parenteses): "
                   + " ".join(f"{r['d'][5:]}:{r['n']}({r['rl'] or 0})" for r in api[::-1]))
    return out


# ---------------------------------------------------------------------------


def executar(db_path: Path, now: Optional[float] = None, csv_path: Optional[Path] = None) -> str:
    now = time.time() if now is None else now
    con = conectar_ro(db_path)
    try:
        st = _storage_somente_leitura(con)
        linhas = reconciliar(st, con, now)
        stops = profundidade_stops(st, con, linhas)
    finally:
        con.close()
    if csv_path is not None:
        with csv_path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["versao", "id", "symbol", "mint", "primeira_tentativa", "status_sinal", "pool_status",
                        "situacao", "horizonte", "status_recalc", "r_recalc", "morto", "censurado", "motivo_morto", "r_menos100",
                        "persist_status", "persist_r", "r_live_regra", "h1_r_sinal", "h1_dif_pareada",
                        "r_regra_offline", "divergencia"])
            for l in linhas:
                for h, lh in l.horizontes.items():
                    w.writerow([l.versao, l.id, l.symbol, l.mint, int(l.primeira_tentativa), l.status_sinal,
                                l.pool_status, l.situacao, h, lh.status, lh.r, int(lh.morto), int(lh.censurado), lh.motivo_morto,
                                lh.r_menos100, lh.persist_status, lh.persist_r, l.r_live_regra, l.h1_r_sinal,
                                l.h1_dif_pareada, l.r_regra_offline, lh.divergencia])
    out = [f"# Reconciliacao ao vivo + profundidade do stop (somente leitura) — {_fmt_ts(now)}", f"banco: {db_path}", ""]
    out += formatar_reconciliacao(linhas)
    out += formatar_stops(stops)
    con = conectar_ro(db_path)
    try:
        out += funil_descoberta(con)
    finally:
        con.close()
    out.append("")
    out.append("Custo do recalculo = CostModel offline (sol_usd=None); veto amplo sem DexPaprika. EXPLORATORIO.")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Reconciliacao ao vivo + profundidade do stop (somente leitura).")
    ap.add_argument("--db", type=Path, default=Path("signals_mvp/dados/estado.sqlite"))
    ap.add_argument("--csv", type=Path, default=None, help="tabela por sinal x horizonte (arquivo proprio)")
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    print(executar(args.db, csv_path=args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
