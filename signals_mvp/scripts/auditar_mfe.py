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

Uso (na VM):
    python -m signals_mvp.scripts.auditar_mfe --db dados/estado.sqlite
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
from ..pos_runner.candles import Bar, tf_seconds
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
                        ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Mesmo criterio/janela de `evidencia.calcular_trajetoria` (ranking por R e por % sao a MESMA
    ordem, pois dividir por `risco_frac`>0 preserva o maximo/minimo) -- aqui guarda tambem o indice do
    candle, nunca so o valor."""
    mfe = mae = None
    for j in range(j0, len(bars)):
        bar = bars[j]
        h = (bar.ts + step - entry_ts) / 3600.0
        if h <= h_lo_excl:
            continue
        if h > h_hi_incl + 1e-9:
            break
        pct_high = 100.0 * (bar.high / entry_price - 1.0)
        pct_low = 100.0 * (bar.low / entry_price - 1.0)
        r_high = r_de(bar.high, entry_price, risco_frac) if risco_frac else None
        r_low = r_de(bar.low, entry_price, risco_frac) if risco_frac else None
        if mfe is None or pct_high > mfe["pct"]:
            mfe = {"idx": j, "pct": pct_high, "r": r_high}
        if mae is None or pct_low < mae["pct"]:
            mae = {"idx": j, "pct": pct_low, "r": r_low}
    return mfe, mae


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


def medir_de_base(storage: Storage, versao: str, origem: str, token: str, pool: str, bars: list[Bar], j0: int,
                  entry_ts: float, entry_price: float, stop: float, risco_pct: Optional[float],
                  closed_ts: Optional[float], step: int, r_oficial: Optional[float]) -> dict[str, Any]:
    risco_frac = (entry_price - stop) / entry_price if entry_price else None
    h_exit = max(0.0, min(JANELA_FECHAMENTO_H, (closed_ts - entry_ts) / 3600.0)) if closed_ts is not None else None
    janelas_def: dict[str, tuple[float, float]] = {"pos_entrada_72h": (0.0, JANELA_FECHAMENTO_H)}
    if h_exit is not None:
        janelas_def["durante_posicao"] = (0.0, h_exit)
        if h_exit < JANELA_FECHAMENTO_H - 1e-9:
            janelas_def["pos_saida"] = (h_exit, JANELA_FECHAMENTO_H)
    janelas: dict[str, dict[str, Any]] = {}
    for nome, (lo, hi) in janelas_def.items():
        mfe, mae = _extremos_na_janela(bars, j0, entry_ts, step, entry_price, risco_frac, lo, hi)
        janelas[nome] = {
            "mfe": _detalhe_candle(storage, versao, pool, bars, mfe, risco_pct),
            "mae": _detalhe_candle(storage, versao, pool, bars, mae, risco_pct),
        }
    return {"token": token, "versao": versao, "origem": origem, "risco_pct": risco_pct,
           "r_oficial": r_oficial, "janelas": janelas}


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
                        risco_pct, s["closed_ts"], step, r_oficial)


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
                                                 bars[j0].ts, entry, stop, risco_pct, closed_ts, step, r_oficial))
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
                                     entry, stop, risco_pct, closed_ts, step, r_oficial))
    return out


def resumo(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """PEDIDO 2026-11-04: so os FECHADOS (tem janela `durante_posicao`) -- quantos lucraram em algum
    momento antes da saida (MFE>0 nessa janela) e o MFE tipico em R (mediana, so risco>=3%); R por
    TOKEN (nunca por sinal)."""
    fechados = [r for r in resultados if "durante_posicao" in r["janelas"]]
    com_mfe = [r["janelas"]["durante_posicao"]["mfe"] for r in fechados if r["janelas"]["durante_posicao"]["mfe"] is not None]
    lucraram = sum(1 for m in com_mfe if m["pct"] > 0)
    mfe_r_validos = [m["r"] for m in com_mfe if m["r"] is not None]
    por_token: dict[str, list[float]] = {}
    for r in resultados:
        if r["r_oficial"] is not None:
            por_token.setdefault(r["token"], []).append(r["r_oficial"])
    r_por_token = {t: {"n": len(vs), "r_medio": statistics.fmean(vs)} for t, vs in sorted(por_token.items())}
    return {
        "n_fechados": len(fechados), "n_lucraram_antes_da_saida": lucraram,
        "mfe_r_mediano": statistics.median(mfe_r_validos) if mfe_r_validos else None,
        "n_mfe_r_valido": len(mfe_r_validos),
        "n_tokens_distintos": len({r["token"] for r in resultados}),
        "r_por_token": r_por_token,
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


def formatar(resultados: list[dict[str, Any]]) -> str:
    out = ["# auditar_mfe -- candle exato do MFE/MAE, durante posicao vs pos-saida (SOMENTE LEITURA)", "",
          f"({AVISO})", ""]
    res = resumo(resultados)
    out.append(f"## Resumo: {res['n_fechados']} fechado(s) limpo(s), {res['n_tokens_distintos']} token(s) distinto(s)")
    out.append(f"lucraram em algum momento antes da saida: {res['n_lucraram_antes_da_saida']}/{res['n_fechados']}")
    out.append(f"MFE tipico em R (mediana, so risco>=3%): " +
              (f"{res['mfe_r_mediano']:+.2f}R (n={res['n_mfe_r_valido']})" if res["mfe_r_mediano"] is not None else "s/d"))
    out.append("R por token: " + (", ".join(f"{t}={v['r_medio']:+.2f}R(n={v['n']})" for t, v in res["r_por_token"].items())
                                  or "nenhum"))
    out.append("")
    for r in resultados:
        out.append(f"## {r['token']} ({r['versao']}/{r['origem']}) -- risco={r['risco_pct']:.1f}%" if r["risco_pct"] is not None
                   else f"## {r['token']} ({r['versao']}/{r['origem']}) -- risco=s/d")
        for nome in ("pos_entrada_72h", "durante_posicao", "pos_saida"):
            jan = r["janelas"].get(nome)
            if jan is None:
                continue
            out.append(f"  [{nome}]")
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
