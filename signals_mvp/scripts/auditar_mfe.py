"""PEDIDO 2026-11-03 (continuacao -- pendente 1 do Passo 0e). SOMENTE LEITURA, zero chamada de rede.

Para cada sinal LIMPO (mesma exclusao de `analise.condicional`/`passo0e_topo_e_fechamento.py`:
`contaminado_candle` fora; risco<3% reportado em % mas nunca em R) de V1/V2/V3, identifica O CANDLE
exato que gerou o MFE e o MAE (ts, high/low, volume, os 2 candles vizinhos) -- nunca so o numero, que
e tudo que `pr_trajetoria`/o Passo 0e ja mostravam. Cruza com `pr1_dexpaprika_divergencias` quando a
origem e V1 (unica versao com essa tabela -- V2/V3 saem `s/d` explicito, nunca uma comparacao
inventada).

Motivo do pedido: um MAE mais profundo que o stop oficial (ex.: -72% com stop em -40%) so e possivel
se o candle que gerou isso aconteceu DEPOIS que a posicao ja tinha fechado -- a janela fixa de 72h de
`pr_trajetoria`/`evidencia.calcular_trajetoria` (correta, documentada, nunca mudada aqui) mistura
"durante a posicao" com "pos-saida" num unico MFE/MAE. Este script SEPARA os dois recortes, a partir
dos MESMOS `pr_bars` e da MESMA formula `evidencia.r_de` (nenhum numero novo, so uma particao por
`closed_ts` do sinal):

  - `durante_posicao`: candles com `ts+step` entre a entrada e `closed_ts` do sinal (inclusive) --
    o MAE aqui nunca deveria passar do stop oficial (se passar, e evidencia de um fill tardio/gap, nao
    desta particao);
  - `pos_saida`: candles com `ts+step` depois de `closed_ts`, ate a janela de 72h -- SO diagnostico,
    nunca influencia P&L (a posicao ja estava fechada).

Nunca altera `pr_trajetoria`/`pr_baseline`/H1/qualquer sinal -- relatorio novo, so leitura do que ja
esta cacheado em `pr_bars`.

Uso (na VM):
    python -m signals_mvp.scripts.auditar_mfe --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Any, Optional

from ..analise.condicional import RISCO_IRREALISTA_MIN_PCT, _contaminado_candle, _risco_irrealista
from ..config import make_paths
from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.evidencia import JANELA_FECHAMENTO_H, r_de
from ..storage import Storage
from .exit_lab import _bar_idx_por_ts

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


def medir_sinal(storage: Storage, versao: str, s: Any, bars: list[Bar]) -> Optional[dict[str, Any]]:
    traj = storage.pr_trajetoria_get(versao, s["id"])
    if traj is None or traj["t_entrada"] is None or s["entry_price"] is None or s["stop"] is None:
        return None
    entry_ts, entry_price, stop = traj["t_entrada"], s["entry_price"], s["stop"]
    j0 = _bar_idx_por_ts(bars, entry_ts)
    if j0 is None:
        return None
    step = tf_seconds(s["tf"] or "1h")
    risco_frac = (entry_price - stop) / entry_price if entry_price else None
    risco_pct = traj["risco_pct"]
    closed_ts = s["closed_ts"]
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
            "mfe": _detalhe_candle(storage, versao, s["pool"], bars, mfe, risco_pct),
            "mae": _detalhe_candle(storage, versao, s["pool"], bars, mae, risco_pct),
        }
    return {"token": s["symbol"] or (s["mint"] or "")[:8], "versao": versao, "risco_pct": risco_pct,
           "janelas": janelas}


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
    for r in resultados:
        out.append(f"## {r['token']} ({r['versao']}) -- risco={r['risco_pct']:.1f}%" if r["risco_pct"] is not None
                   else f"## {r['token']} ({r['versao']}) -- risco=s/d")
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
