"""PEDIDO 2026-11-03/04 (continuacao -- FRENTE A). SOMENTE LEITURA, zero chamada de rede.

Para cada sinal FECHADO limpo (mesma exclusao de `analise.condicional`: `contaminado_candle` fora;
risco<3% reportado em % mas nunca em R) das TRES fontes -- (A) sinais ao vivo V1/V2/V3
(`pr1_signals`/`pr2_signals`/`pr3_signals`), (B) coorte retrospectiva lote 1 admitida apos o
congelamento (`pr_retro_candidatos`, MESMO replay de `exit_lab.linhas_retro_admitido`) e (C) replay
completo de V3 sobre pools admitidos hoje (MESMO evento bruto de
`avaliar_v3_retro.parte_a_pools_admitidos`) -- identifica O CANDLE exato que gerou o MFE e o MAE (ts,
high/low, volume, os 2 candles vizinhos). Cruza com `pr1_dexpaprika_divergencias` quando a origem e
V1 (unica versao com essa tabela -- V2/V3 saem `s/d` explicito).

Motivo do pedido original: um MAE mais profundo que o stop oficial (ex.: -72% com stop em -40%) so e
possivel se o candle que gerou isso aconteceu DEPOIS que a posicao ja tinha fechado -- a janela fixa
de 72h de `pr_trajetoria`/`evidencia.calcular_trajetoria` mistura "durante a posicao" com "pos-saida"
num unico MFE/MAE. Este script SEPARA os dois recortes, a partir dos MESMOS `pr_bars` e da MESMA
formula `evidencia.r_de` (nenhum numero novo):

  - `durante_posicao`: candles com `ts+step` entre a entrada e a saida (persistida para V1/V2/V3 ao
    vivo; RESSIMULADA com `simulate_v1` -- MESMOS parametros congelados -- para as fontes B/C, que
    nunca persistem um `closed_ts` proprio);
  - `pos_saida`: candles depois da saida, ate a janela de 72h -- SO diagnostico, nunca influencia P&L.

PEDIDO 2026-11-04: tambem responde, agregado (`resumo()`), quantos sinais ficaram no lucro em algum
momento ANTES da saida (MFE>0 na janela `durante_posicao`), o MFE tipico em multiplos do risco
(mediana, so risco>=3%), e R por TOKEN (nunca por sinal -- R oficial: `100*result_net/risco_pct`
para as fontes ao vivo, `simulate_v1.r_mult` para B/C, MESMA formula de `live.py:
_atualizar_baseline`/`avaliar_candidatos_retro.py: _simular_entrada`).

Nunca altera `pr_trajetoria`/`pr_baseline`/H1/`pr_retro_resultados`/qualquer sinal -- relatorio novo,
so leitura do que ja esta cacheado em `pr_bars`.

CORRECAO 2026-11-05 (mesma frente, sem tocar V1/V2/V3/H1/sinais/hashes):

1) `candle_corrompido_provavel`: candle com volume=0 (inclui lacuna preenchida por `fill_gaps`, nunca
   negociacao real) OU `high` > 10x o `high` de AMBOS os vizinhos (pico isolado, provavel erro de
   dado) NUNCA decide MFE/MAE -- descartado e contado por janela (`n_candles_corrompidos_descartados`),
   nunca silencioso. Retrospectivo, nunca o mesmo veto causal de `qualidade_candle.py` (V1/V2/V3).
2) `resumo()` agora dedup por padrao (`_deduplicar_por_entrada`, chave `(origem, pool, entrada_ts)`,
   prioridade v1<v2<v3): a MESMA zona/entrada costuma satisfazer V1 e V2 (ou V3) ao mesmo tempo --
   sem isso, o mesmo trade real contava 2-3x no resumo. `formatar()` separa ao_vivo/retro_lote1/
   replay_v3 em resumos INDEPENDENTES (nunca somados) -- replay_v3 rotulado (EXPLORATORIO): e replay
   retroativo completo, nunca uma coorte admitida de verdade.
3) Metricas novas no `resumo()`: tokens distintos com MFE>=+1R/+2R durante a posicao; trades que
   chegaram a +2R e AINDA terminaram em stop (devolucao, usa `reason` do sinal/`simulate_v1.reason`,
   MESMO campo que `live.py` ja grava); tokens distintos com stop seguido de alta>=+100% nas 72h
   seguintes (janela `pos_saida`, candle limpo).

PEDIDO 2026-11-05 (PARTE 3): esclarecimento + quantificacao, nenhuma mudanca de regra.

`vol_entrada`/`vol_24h_antes` (e o novo `n_candles_vol_pos_24h_antes`) usam `bars[j0]` -- "candle de
entrada" aqui e o candle ONDE O FILL ACONTECE (`j0`, cujo `open` e `entry_price`), que e o candle
SEGUINTE ao candle do gatilho (a ENTRADA e decidida no FECHAMENTO de `bars[j0-1]`, executada no OPEN
do candle seguinte -- mesma convencao causal de TP1/EXIT FULL, nunca lookahead; ver
`exit_lab.py: _variante_a`, `ev = _SyntheticEvent(j0-1, ...)`). Nunca o candle do proprio gatilho.

O modelo de custo (`pos_runner/costs.py: CostModel.slippage_pct`) usa SO `L_bc`/MC/`position_sol`
(aproximacao de reserva via produto constante) -- NAO le volume do candle de forma alguma; o volume
real do candle de entrada e um dado de mercado paralelo (medicao), nunca um insumo da slippage
simulada. `resumo()` conta quantas entradas tem `vol_entrada` < 25% da media horaria das 24h
anteriores (`vol_24h_antes/24`) -- so entre as com media horaria > 0 (nenhum limiar escolhido alem
dos 25% explicitamente pedidos).

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.auditar_mfe --db signals_mvp/dados/estado.sqlite
"""

from __future__ import annotations

import dataclasses
import sqlite3
import statistics
import argparse
from pathlib import Path
from typing import Any, Optional

from ..analise.condicional import RISCO_IRREALISTA_MIN_PCT, _contaminado_candle, _risco_irrealista
from ..config import make_paths
from ..pos_runner.candles import Bar, candle_corrompido_provavel, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.evidencia import JANELA_FECHAMENTO_H, r_de
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.simulate_v1 import simulate_v1
from ..storage import Storage
from .avaliar_v3_retro import _conectar_ro, parte_a_pools_admitidos
from .exit_lab import _bar_idx_por_ts, _bars_truncados

AVISO = "diagnostico (MFE/MAE do candle real, separado por janela); nunca altera H1/sinais/trajetoria"


def _signals_de(storage: Storage, versao: str) -> list[Any]:
    return {"v1": storage.pr1_signals, "v2": storage.pr2_signals, "v3": storage.pr3_signals}[versao]()


def _extremos_na_janela(bars: list[Bar], j0: int, entry_ts: float, step: int, entry_price: float,
                        risco_frac: Optional[float], h_lo_excl: float, h_hi_incl: float
                        ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], int]:
    """Mesmo criterio/janela de `evidencia.calcular_trajetoria` (ranking por R e por % sao a MESMA
    ordem, pois dividir por `risco_frac`>0 preserva o maximo/minimo) -- aqui guarda tambem o indice do
    candle, nunca so o valor. Candle `candle_corrompido_provavel` nunca concorre ao MFE/MAE (so
    conta no 3o valor devolvido -- quantos foram descartados nesta janela, nunca silencioso)."""
    mfe = mae = None
    n_descartados = 0
    for j in range(j0, len(bars)):
        bar = bars[j]
        h = (bar.ts + step - entry_ts) / 3600.0
        if h <= h_lo_excl:
            continue
        if h > h_hi_incl + 1e-9:
            break
        if candle_corrompido_provavel(bars, j):
            n_descartados += 1
            continue
        pct_high = 100.0 * (bar.high / entry_price - 1.0)
        pct_low = 100.0 * (bar.low / entry_price - 1.0)
        r_high = r_de(bar.high, entry_price, risco_frac) if risco_frac else None
        r_low = r_de(bar.low, entry_price, risco_frac) if risco_frac else None
        if mfe is None or pct_high > mfe["pct"]:
            mfe = {"idx": j, "pct": pct_high, "r": r_high}
        if mae is None or pct_low < mae["pct"]:
            mae = {"idx": j, "pct": pct_low, "r": r_low}
    return mfe, mae, n_descartados


def _vizinho(bars: list[Bar], idx: int) -> Optional[dict[str, Any]]:
    if idx < 0 or idx >= len(bars):
        return None
    b = bars[idx]
    return {"ts": b.ts, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}


def _divergencia_v1(storage: Storage, pool: str, candle_ts: float) -> str:
    divs = [d for d in storage.pr1_dexpaprika_divergencias() if d["pool"] == pool and d["candle_ts"] == candle_ts]
    if not divs:
        return "sem divergencia confirmada"
    d = divs[0]
    return f"{d['campo']}: GT={d['valor_gt']:.6g} DexPaprika={d['valor_dexpaprika']:.6g} ({d['diff_pct']:.1f}%)"


def _detalhe_candle(storage: Storage, versao: str, pool: str, bars: list[Bar], extremo: Optional[dict[str, Any]],
                    risco_pct: Optional[float]) -> Optional[dict[str, Any]]:
    if extremo is None:
        return None
    idx = extremo["idx"]
    bar = bars[idx]
    r_mostrar = extremo["r"] if (risco_pct is not None and risco_pct >= RISCO_IRREALISTA_MIN_PCT) else None
    divergencia = _divergencia_v1(storage, pool, bar.ts) if versao == "v1" else "s/d (DexPaprika so audita V1)"
    return {"ts": bar.ts, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume,
           "pct": extremo["pct"], "r": r_mostrar, "vizinho_antes": _vizinho(bars, idx - 1),
           "vizinho_depois": _vizinho(bars, idx + 1), "divergencia_dexpaprika": divergencia}


def _volume_entrada_e_24h_antes(bars: list[Bar], j0: int, entry_ts: float
                                ) -> tuple[Optional[float], Optional[float], Optional[int]]:
    """PEDIDO 2026-11-05 (FRENTE B/PARTE 4b): volume do candle de entrada (`bars[j0]`, onde o FILL
    acontece -- ver docstring do modulo), soma de volume das 24h ANTERIORES a ele, e quantos desses
    candles tiveram volume>0 (`n_candles_vol_pos_24h_antes`, reusado por `auditar_inatividade.py`) --
    mesmo `pr_bars` ja carregado, nenhuma chamada nova, nenhum limiar escolhido aqui."""
    if j0 >= len(bars):
        return None, None, None
    vol_entrada = bars[j0].volume
    bars_24h_antes = [b for b in bars if entry_ts - 24 * 3600.0 <= b.ts < entry_ts]
    vol_24h_antes = sum(b.volume for b in bars_24h_antes)
    n_candles_vol_pos_24h_antes = sum(1 for b in bars_24h_antes if b.volume > 0)
    return vol_entrada, vol_24h_antes, n_candles_vol_pos_24h_antes


def medir_de_base(storage: Storage, versao: str, origem: str, token: str, pool: str, bars: list[Bar], j0: int,
                  entry_ts: float, entry_price: float, stop: float, risco_pct: Optional[float],
                  closed_ts: Optional[float], step: int, r_oficial: Optional[float],
                  reason: Optional[str] = None) -> dict[str, Any]:
    risco_frac = (entry_price - stop) / entry_price if entry_price else None
    h_exit = max(0.0, min(JANELA_FECHAMENTO_H, (closed_ts - entry_ts) / 3600.0)) if closed_ts is not None else None
    janelas_def: dict[str, tuple[float, float]] = {"pos_entrada_72h": (0.0, JANELA_FECHAMENTO_H)}
    if h_exit is not None:
        janelas_def["durante_posicao"] = (0.0, h_exit)
        if h_exit < JANELA_FECHAMENTO_H - 1e-9:
            janelas_def["pos_saida"] = (h_exit, JANELA_FECHAMENTO_H)
    janelas: dict[str, dict[str, Any]] = {}
    for nome, (lo, hi) in janelas_def.items():
        mfe, mae, n_descartados = _extremos_na_janela(bars, j0, entry_ts, step, entry_price, risco_frac, lo, hi)
        janelas[nome] = {
            "mfe": _detalhe_candle(storage, versao, pool, bars, mfe, risco_pct),
            "mae": _detalhe_candle(storage, versao, pool, bars, mae, risco_pct),
            "n_candles_corrompidos_descartados": n_descartados,
        }
    vol_entrada, vol_24h_antes, n_candles_vol_pos_24h_antes = _volume_entrada_e_24h_antes(bars, j0, entry_ts)
    return {"token": token, "pool": pool, "entrada_ts": entry_ts, "versao": versao, "origem": origem,
           "risco_pct": risco_pct, "r_oficial": r_oficial, "reason": reason, "janelas": janelas,
           "vol_entrada": vol_entrada, "vol_24h_antes": vol_24h_antes,
           "n_candles_vol_pos_24h_antes": n_candles_vol_pos_24h_antes}


def medir_sinal(storage: Storage, versao: str, s: Any, bars: list[Bar]) -> Optional[dict[str, Any]]:
    traj = storage.pr_trajetoria_get(versao, s["id"])
    if traj is None or traj["t_entrada"] is None or s["entry_price"] is None or s["stop"] is None:
        return None
    entry_ts, entry_price, stop = traj["t_entrada"], s["entry_price"], s["stop"]
    j0 = _bar_idx_por_ts(bars, entry_ts)
    if j0 is None:
        return None
    step = tf_seconds(s["tf"] or "1h")
    risco_pct = traj["risco_pct"]
    r_oficial = (100.0 * s["result_net"] / risco_pct) if (s["result_net"] is not None and risco_pct
                                                          and risco_pct >= RISCO_IRREALISTA_MIN_PCT) else None
    token = s["symbol"] or (s["mint"] or "")[:8]
    return medir_de_base(storage, versao, "ao_vivo", token, s["pool"], bars, j0, entry_ts, entry_price, stop,
                        risco_pct, s["closed_ts"], step, r_oficial, reason=s["reason"])


def medir_versao(storage: Storage, versao: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bars_cache: dict[str, list[Bar]] = {}
    for s in _signals_de(storage, versao):
        if s["evento"] != "ENTRADA" or s["status"] != "fechado":
            continue
        if _contaminado_candle(s) or _risco_irrealista(s):
            continue
        tf = s["tf"] or "1h"
        bars = bars_cache.setdefault(f"{s['pool']}|{tf}", [Bar(*row) for row in storage.pr_bars(s["pool"], tf)])
        r = medir_sinal(storage, versao, s, bars)
        if r is not None:
            out.append(r)
    return out


def _closed_ts_da_simulacao(bars: list[Bar], j0: int, step: int, res: Any) -> Optional[float]:
    """`simulate_v1` nunca persiste `closed_ts` (fontes B/C sao simuladas, nunca sinais reais) -- a
    saida e o ts+step da ULTIMA perna, SO quando `status=='fechado'` (em_aberto fica None, nunca
    inventado -- a janela toda conta como `durante_posicao`, igual a um sinal real sem saida ainda)."""
    if res.status != "fechado" or not res.legs:
        return None
    return float(res.legs[-1].ts) + step


def medir_retro_admitido(storage: Storage, db_path: Path) -> list[dict[str, Any]]:
    """Fonte B: coorte retro lote 1, SO admitido_apos_congelamento -- MESMO replay de
    `exit_lab.linhas_retro_admitido` (candles truncados, `ParamsV1`/`ParamsV2` congelados), reusado
    aqui SEM MUDANCA de regra, so pra extrair MFE/MAE em vez das 4 saidas alternativas."""
    con = _conectar_ro(db_path)
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "pr_retro_candidatos" not in tabelas:
            return []
        candidatos = con.execute("SELECT pool, symbol, launchpad, grad_ts, criado_ts FROM pr_retro_candidatos").fetchall()
        costs = CostModel()
        out: list[dict[str, Any]] = []
        for row in candidatos:
            pool_row = con.execute("SELECT added_ts, l_bc, launchpad FROM pr_pools WHERE pool=?", (row["pool"],)).fetchone()
            if pool_row is None or pool_row["added_ts"] is None or pool_row["l_bc"] is None:
                continue
            for versao, params in (("v1", load_params_v1()), ("v2", load_params_v2())):
                tf = params.timeframes[0]
                step = tf_seconds(tf)
                bars = _bars_truncados(con, row["pool"], tf, step, pool_row["added_ts"])
                if not bars:
                    continue
                # CORRECAO 2026-11-04 (mesma de exit_lab.py: linhas_retro_admitido): `criado_ts` tem
                # que vir da linha congelada (nunca None), senao `in_age_window()` sempre falha e
                # nenhuma ENTRADA jamais aparece aqui.
                det = DetectorV1(params, tf, pool_row["l_bc"], row["grad_ts"], row["criado_ts"])
                dex = pool_row["launchpad"] or row["launchpad"] or "desconhecido"
                for bar in bars:
                    for ev in det.update(bar):
                        if ev.kind != "ENTRADA":
                            continue
                        j0 = ev.idx + 1
                        if j0 >= len(bars):
                            continue
                        entry = bars[j0].open
                        stop = ev.data["stop"]
                        risco_pct = ev.data.get("risco_pct")
                        res = simulate_v1(bars, ev, params, costs, dex, pool_row["l_bc"], lambda _t: None)
                        # coorte retro nunca tem fill real confirmado -- contaminado_candle (marcacao
                        # manual pos-fill) nunca se aplica aqui, so risco<3% exclui o R (MESMA regra).
                        r_oficial = None if (risco_pct is None or risco_pct < RISCO_IRREALISTA_MIN_PCT) else res.r_mult
                        closed_ts = _closed_ts_da_simulacao(bars, j0, step, res)
                        token = row["symbol"] or row["pool"][:8]
                        out.append(medir_de_base(storage, versao, "retro_lote1", token, row["pool"], bars, j0,
                                                 bars[j0].ts, entry, stop, risco_pct, closed_ts, step, r_oficial,
                                                 reason=res.reason or None))
        return out
    finally:
        con.close()


def medir_v3_replay(storage: Storage, db_path: Path) -> list[dict[str, Any]]:
    """Fonte C: replay completo de `ParamsV3` sobre pools admitidos hoje -- reusa o evento bruto de
    `avaliar_v3_retro.parte_a_pools_admitidos` (`eventos_raw`), nunca duplica o replay."""
    con = _conectar_ro(db_path)
    try:
        params_v3 = load_params_v3()
        linhas_pool = parte_a_pools_admitidos(con, params_v3)
    finally:
        con.close()
    costs = CostModel()
    out: list[dict[str, Any]] = []
    for lp in linhas_pool:
        for bars, ev, dex, l_bc in lp["eventos_raw"]:
            j0 = ev.idx + 1
            if j0 >= len(bars):
                continue
            entry = bars[j0].open
            stop = ev.data["stop"]
            risco_pct = ev.data.get("risco_pct")
            step = tf_seconds(params_v3.timeframes[0])
            res = simulate_v1(bars, ev, params_v3, costs, dex, l_bc, lambda _t: None)
            r_oficial = None if (risco_pct is None or risco_pct < RISCO_IRREALISTA_MIN_PCT) else res.r_mult
            closed_ts = _closed_ts_da_simulacao(bars, j0, step, res)
            out.append(medir_de_base(storage, "v3", "replay_v3", lp["symbol"], lp["pool"], bars, j0, bars[j0].ts,
                                     entry, stop, risco_pct, closed_ts, step, r_oficial, reason=res.reason or None))
    return out


def _deduplicar_por_entrada(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PEDIDO 2026-11-05 (correcao FRENTE A): o MESMO trade real aparece em V1/V2/V3 quando a mesma
    zona/entrada satisfaz os 3 conjuntos de parametros ao mesmo tempo (V2/V3 so afrouxam idade/
    zone_min_candles da V1 -- nunca uma regra nova). Um so por (origem, pool, entrada_ts) -- prioridade
    v1 < v2 < v3 (ordem alfabetica, deterministica, nunca aleatoria). `origem` entra na chave de
    proposito: retro_lote1/replay_v3 nunca se fundem com ao_vivo so por coincidir pool+ts."""
    grupos: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for i, r in enumerate(resultados):
        # `.get(..., i)` no entrada_ts: so entra em fixture de teste minimo sem essa chave -- cada
        # linha fica no seu proprio grupo (nunca funde por engano quando a identidade real nao existe).
        chave = (r.get("origem"), r.get("pool", r.get("token")), r.get("entrada_ts", i))
        grupos.setdefault(chave, []).append(r)
    out: list[dict[str, Any]] = []
    for g in grupos.values():
        g_ordenado = sorted(g, key=lambda r: r.get("versao", ""))
        escolhido = dict(g_ordenado[0])
        escolhido["_versoes_agrupadas"] = sorted({r.get("versao", "") for r in g_ordenado})
        out.append(escolhido)
    return out


def resumo(resultados: list[dict[str, Any]], deduplicar: bool = True) -> dict[str, Any]:
    """PEDIDO 2026-11-04/05: so os FECHADOS (tem janela `durante_posicao`), SO candles limpos (MFE/MAE
    ja excluem `candle_corrompido_provavel` em `_extremos_na_janela`) e, por padrao, deduplicados por
    trade real (`_deduplicar_por_entrada` -- nunca conta o mesmo trade 3x so por V1/V2/V3 coincidirem).
    Quantos lucraram em algum momento antes da saida (MFE>0 na janela `durante_posicao`); MFE tipico em
    R (mediana, so risco>=3%); tokens distintos que chegaram a +1R/+2R durante a posicao; trades que
    chegaram a +2R e AINDA terminaram em stop (devolucao); tokens distintos onde um stop foi seguido de
    alta >=+100% nas 72h seguintes (janela `pos_saida`, candle limpo); R por TOKEN (nunca por sinal)."""
    base = _deduplicar_por_entrada(resultados) if deduplicar else list(resultados)
    fechados = [r for r in base if "durante_posicao" in r["janelas"]]
    com_mfe = [r for r in fechados if r["janelas"]["durante_posicao"]["mfe"] is not None]
    lucraram = sum(1 for r in com_mfe if r["janelas"]["durante_posicao"]["mfe"]["pct"] > 0)
    mfe_r_validos = [r["janelas"]["durante_posicao"]["mfe"]["r"] for r in com_mfe
                     if r["janelas"]["durante_posicao"]["mfe"]["r"] is not None]
    tokens_mfe_1r: set[str] = set()
    tokens_mfe_2r: set[str] = set()
    n_devolucao_2r_para_stop = 0
    for r in com_mfe:
        r_mfe = r["janelas"]["durante_posicao"]["mfe"]["r"]
        if r_mfe is None:
            continue
        if r_mfe >= 1.0:
            tokens_mfe_1r.add(r["token"])
        if r_mfe >= 2.0:
            tokens_mfe_2r.add(r["token"])
            if r.get("reason") == "stop":
                n_devolucao_2r_para_stop += 1
    tokens_stop_seguido_alta_72h: set[str] = set()
    for r in fechados:
        if r.get("reason") != "stop":
            continue
        pos_saida = r["janelas"].get("pos_saida")
        if pos_saida is None or pos_saida["mfe"] is None:
            continue
        if pos_saida["mfe"]["pct"] >= 100.0:
            tokens_stop_seguido_alta_72h.add(r["token"])
    por_token: dict[str, list[float]] = {}
    for r in base:
        if r["r_oficial"] is not None:
            por_token.setdefault(r["token"], []).append(r["r_oficial"])
    r_por_token = {t: {"n": len(vs), "r_medio": statistics.fmean(vs)} for t, vs in sorted(por_token.items())}
    vol_entrada_validos = [r["vol_entrada"] for r in base if r.get("vol_entrada") is not None]
    vol_24h_antes_validos = [r["vol_24h_antes"] for r in base if r.get("vol_24h_antes") is not None]
    n_24h_antes_zero = sum(1 for v in vol_24h_antes_validos if v == 0.0)
    # PEDIDO 2026-11-05 (PARTE 3): media horaria das 24h ANTES (vol_24h_antes/24) comparada ao volume
    # do candle de entrada -- so entre pares com media horaria > 0 (media==0 ja conta em
    # n_24h_antes_sem_negociacao acima; 25% e o limiar literal pedido, nenhum outro escolhido aqui).
    pares_media_horaria = [(r["vol_entrada"], r["vol_24h_antes"] / 24.0) for r in base
                          if r.get("vol_entrada") is not None and r.get("vol_24h_antes") is not None
                          and r["vol_24h_antes"] / 24.0 > 0.0]
    n_entrada_abaixo_25pct_media_horaria = sum(1 for ve, mh in pares_media_horaria if ve < 0.25 * mh)
    n_candles_descartados = sum(jan.get("n_candles_corrompidos_descartados", 0)
                                for r in base for jan in r["janelas"].values())
    return {
        "n_antes_dedup": len(resultados), "n_depois_dedup": len(base),
        "n_fechados": len(fechados), "n_lucraram_antes_da_saida": lucraram,
        "mfe_r_mediano": statistics.median(mfe_r_validos) if mfe_r_validos else None,
        "n_mfe_r_valido": len(mfe_r_validos),
        "n_tokens_mfe_1r": len(tokens_mfe_1r), "n_tokens_mfe_2r": len(tokens_mfe_2r),
        "n_devolucao_2r_para_stop": n_devolucao_2r_para_stop,
        "n_tokens_stop_seguido_alta_100pct_72h": len(tokens_stop_seguido_alta_72h),
        "n_tokens_distintos": len({r["token"] for r in base}),
        "r_por_token": r_por_token,
        "vol_entrada_mediano": statistics.median(vol_entrada_validos) if vol_entrada_validos else None,
        "vol_24h_antes_mediano": statistics.median(vol_24h_antes_validos) if vol_24h_antes_validos else None,
        "n_24h_antes_sem_negociacao": n_24h_antes_zero,
        "n_vol_entrada_valido": len(vol_entrada_validos),
        "n_candles_corrompidos_descartados": n_candles_descartados,
        "n_entrada_abaixo_25pct_media_horaria": n_entrada_abaixo_25pct_media_horaria,
        "n_media_horaria_valida": len(pares_media_horaria),
    }


def _fmt_cand(c: Optional[dict[str, Any]]) -> str:
    if c is None:
        return "s/d"
    pct = f"{c['pct']:+.1f}%"
    r = f" ({c['r']:+.2f}R)" if c["r"] is not None else ""
    v = f"vol={c['volume']:.0f}" if c["volume"] is not None else "vol=s/d"
    viz = []
    if c["vizinho_antes"] is not None:
        viz.append(f"antes: h={c['vizinho_antes']['high']:.6g} l={c['vizinho_antes']['low']:.6g}")
    if c["vizinho_depois"] is not None:
        viz.append(f"depois: h={c['vizinho_depois']['high']:.6g} l={c['vizinho_depois']['low']:.6g}")
    viz_txt = " | ".join(viz) or "sem vizinho"
    return (f"ts={c['ts']:.0f} high={c['high']:.6g} low={c['low']:.6g} close={c['close']:.6g} {v} "
           f"{pct}{r} | vizinhos: {viz_txt} | DexPaprika: {c['divergencia_dexpaprika']}")


_ORIGENS_EM_ORDEM = (
    ("ao_vivo", "ao vivo (V1/V2/V3)", False),
    ("retro_lote1", "coorte retro lote 1 (admitida apos congelamento)", False),
    ("replay_v3", "replay V3 sobre pools admitidos hoje", True),
)


def _formatar_resumo(res: dict[str, Any], titulo: str) -> list[str]:
    out = [f"## {titulo} -- resumo", ""]
    dedup_txt = (f" ({res['n_antes_dedup']} linhas V1/V2/V3 -> {res['n_depois_dedup']} trade(s) reais, "
                "mesmo trade nunca conta 2x)" if res["n_antes_dedup"] != res["n_depois_dedup"] else "")
    out.append(f"{res['n_fechados']} fechado(s) limpo(s){dedup_txt}, {res['n_tokens_distintos']} token(s) distinto(s)")
    out.append(f"candles corrompidos descartados do MFE/MAE (vol=0 ou pico isolado vs 2 vizinhos): "
              f"{res['n_candles_corrompidos_descartados']}")
    out.append(f"lucraram em algum momento antes da saida: {res['n_lucraram_antes_da_saida']}/{res['n_fechados']}")
    out.append("MFE tipico em R (mediana, so risco>=3%): " +
              (f"{res['mfe_r_mediano']:+.2f}R (n={res['n_mfe_r_valido']})" if res["mfe_r_mediano"] is not None else "s/d"))
    out.append(f"tokens distintos que chegaram a >=+1R durante a posicao: {res['n_tokens_mfe_1r']}")
    out.append(f"tokens distintos que chegaram a >=+2R durante a posicao: {res['n_tokens_mfe_2r']}")
    out.append(f"trades que chegaram a >=+2R e AINDA terminaram em stop (devolucao): {res['n_devolucao_2r_para_stop']}")
    out.append("tokens distintos onde um stop foi seguido de alta >=+100% nas 72h seguintes (pos-saida): " +
              str(res["n_tokens_stop_seguido_alta_100pct_72h"]))
    out.append("R por token: " + (", ".join(f"{t}={v['r_medio']:+.2f}R(n={v['n']})" for t, v in res["r_por_token"].items())
                                  or "nenhum"))
    out.append("Volume (FRENTE B, nenhum limiar escolhido): candle de entrada mediano=" +
              (f"{res['vol_entrada_mediano']:.0f}" if res["vol_entrada_mediano"] is not None else "s/d") +
              ", 24h ANTES da entrada mediano=" +
              (f"{res['vol_24h_antes_mediano']:.0f}" if res["vol_24h_antes_mediano"] is not None else "s/d") +
              f", sem NENHUMA negociacao nas 24h antes: {res['n_24h_antes_sem_negociacao']}/{res['n_vol_entrada_valido']}")
    out.append("PARTE 3 -- 'candle de entrada' = bars[j0] (onde o FILL acontece, abertura do candle "
              "SEGUINTE ao gatilho); slippage simulada (costs.py) NAO le volume do candle, so L_bc/MC. "
              f"entradas com volume < 25% da media horaria das 24h antes: "
              f"{res['n_entrada_abaixo_25pct_media_horaria']}/{res['n_media_horaria_valida']}")
    out.append("")
    return out


def formatar(resultados: list[dict[str, Any]]) -> str:
    out = ["# auditar_mfe -- candle exato do MFE/MAE, durante posicao vs pos-saida (SOMENTE LEITURA)", "",
          f"({AVISO})", "",
          "Fontes SEPARADAS (nunca somadas num resumo unico -- origens/metodos diferentes): ao_vivo e "
          "retro_lote1 sao sinais reais/candidatos realmente admitidos; replay_v3 e EXPLORATORIO (replay "
          "retroativo completo, nao e coorte admitida de verdade -- nunca tratar como validacao).", ""]
    por_origem: dict[str, list[dict[str, Any]]] = {}
    for r in resultados:
        por_origem.setdefault(r["origem"], []).append(r)
    for origem, titulo, exploratorio in _ORIGENS_EM_ORDEM:
        linhas_origem = por_origem.get(origem, [])
        if not linhas_origem:
            continue
        rotulo = f"{titulo} (EXPLORATORIO)" if exploratorio else titulo
        res = resumo(linhas_origem)
        out.extend(_formatar_resumo(res, rotulo))
        for r in _deduplicar_por_entrada(linhas_origem):
            versoes = "+".join(r["_versoes_agrupadas"])
            out.append(f"### {r['token']} ({versoes}/{r['origem']}) -- risco={r['risco_pct']:.1f}%" if r["risco_pct"] is not None
                       else f"### {r['token']} ({versoes}/{r['origem']}) -- risco=s/d")
            vol_e = f"{r['vol_entrada']:.0f}" if r.get("vol_entrada") is not None else "s/d"
            vol_24 = f"{r['vol_24h_antes']:.0f}" if r.get("vol_24h_antes") is not None else "s/d"
            out.append(f"  reason={r.get('reason') or 's/d'} | vol candle entrada={vol_e} | vol 24h antes da entrada={vol_24}")
            for nome in ("pos_entrada_72h", "durante_posicao", "pos_saida"):
                jan = r["janelas"].get(nome)
                if jan is None:
                    continue
                out.append(f"  [{nome}] (candles corrompidos descartados: {jan['n_candles_corrompidos_descartados']})")
                out.append(f"    MFE: {_fmt_cand(jan['mfe'])}")
                out.append(f"    MAE: {_fmt_cand(jan['mae'])}")
            out.append("")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        resultados = [r for v in ("v1", "v2", "v3") for r in medir_versao(storage, v)]
        resultados += medir_retro_admitido(storage, db_path)
        resultados += medir_v3_replay(storage, db_path)
        return formatar(resultados)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="auditar_mfe: candle exato do MFE/MAE por janela (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
