"""PEDIDO 2026-11-05 (PARTE 4). SOMENTE LEITURA, zero chamada de rede. Diagnostico de inatividade dos
pools ativos -- NENHUM criterio novo decidido aqui (a proposta de rotacao por inatividade fica so em
texto na emenda, ver docstring de `resumo()`), so medicao com dado ja persistido.

(a) Por pool ATIVO: `pr_bars` ja em cache -- quantos candles 1h tiveram volume>0 nas ultimas 24h/72h
(nunca so "tem candle", que `fill_gaps` pode ter preenchido vazio -- ver `auditar_negociacao.py`),
quantas horas desde o ULTIMO candle com volume>0 (nunca so "ultimo candle", mesma razao), e ha quanto
tempo o pool ocupa a vaga (`pr_pools.added_ts`, desde que foi admitido ao acompanhamento ao vivo).

(b) Para os sinais fechados das 3 fontes (ao_vivo/retro_lote1/replay_v3, reusa
`auditar_mfe.medir_versao`/`medir_retro_admitido`/`medir_v3_replay` -- MESMO campo aditivo
`n_candles_vol_pos_24h_antes`, nenhum replay novo): quantos candles tiveram volume>0 nas 24h ANTES da
entrada, em QUARTIS, por TOKEN DISTINTO (nunca por sinal -- um token com muitos sinais nao pesa mais).

(c) Motivo do pool sem candle novo reusa `saude._motivo_atraso_candle` (429/5xx/sem_negociacao_na_hora/
sem_tentativa, MESMA categorizacao, nenhuma nova) -- quando cai em "s/d" (http_status fora das
categorias conhecidas), mostra o `http_status`/`fonte`/`ts` BRUTOS da ultima tentativa
(`pr_api_uso_ultima_tentativa_poll_pool`) em vez de deixar o motivo opaco. Pool sem NENHUM candle 1h
ainda: `pr_bars` vazio para esse pool -- explicito, nunca confundido com "atrasado".

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.auditar_inatividade --db signals_mvp/dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..storage import Storage
from .auditar_mfe import medir_retro_admitido, medir_v3_replay, medir_versao
from .saude import _motivo_atraso_candle


def medir_pool_ativo(storage: Storage, row: Any, now: float) -> dict[str, Any]:
    bars = [Bar(*r) for r in storage.pr_bars(row["pool"], "1h")]
    bars_24h = [b for b in bars if b.ts >= now - 24 * 3600.0]
    bars_72h = [b for b in bars if b.ts >= now - 72 * 3600.0]
    n_vol_pos_24h = sum(1 for b in bars_24h if b.volume > 0)
    n_vol_pos_72h = sum(1 for b in bars_72h if b.volume > 0)
    ultimos_vol_pos = [b for b in bars if b.volume > 0]
    horas_desde_ultimo_vol_pos = (now - ultimos_vol_pos[-1].ts) / 3600.0 if ultimos_vol_pos else None
    added_ts = row["added_ts"]
    horas_na_vaga = (now - added_ts) / 3600.0 if added_ts is not None else None
    motivo = _motivo_atraso_candle(storage, row["pool"], bars[-1].ts if bars else None)
    detalhe_bruto = None
    if motivo == "s/d":
        tentativa = storage.pr_api_uso_ultima_tentativa_poll_pool(row["pool"], since_ts=(bars[-1].ts if bars else 0.0))
        if tentativa is not None:
            detalhe_bruto = f"fonte={tentativa['fonte']} http_status={tentativa['http_status']} ts={tentativa['ts']:.0f}"
    return {
        "pool": row["pool"], "symbol": row["symbol"] or row["pool"][:8],
        "n_candles_totais": len(bars), "n_candles_24h": len(bars_24h), "n_vol_pos_24h": n_vol_pos_24h,
        "n_candles_72h": len(bars_72h), "n_vol_pos_72h": n_vol_pos_72h,
        "horas_desde_ultimo_vol_pos": horas_desde_ultimo_vol_pos, "horas_na_vaga": horas_na_vaga,
        "motivo": motivo, "detalhe_bruto_quando_s_d": detalhe_bruto,
    }


def medir_pools_ativos(db_path: Path, now: Optional[float] = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        rows = storage.pr_pools("ativo")
        return [medir_pool_ativo(storage, row, now) for row in rows]
    finally:
        storage.close()


def _quartis(valores: list[float]) -> Optional[dict[str, float]]:
    if not valores:
        return None
    ordenados = sorted(valores)
    return {
        "q1": statistics.median(ordenados[: max(1, len(ordenados) // 2)]) if len(ordenados) > 1 else ordenados[0],
        "mediana": statistics.median(ordenados),
        "q3": statistics.median(ordenados[(len(ordenados) + 1) // 2:]) if len(ordenados) > 1 else ordenados[0],
        "n": len(ordenados),
    }


def atividade_pre_entrada_por_token(storage: Storage, db_path: Path) -> dict[str, Any]:
    """PEDIDO 2026-11-05 (PARTE 4b): reusa os sinais fechados das 3 fontes (campo aditivo
    `n_candles_vol_pos_24h_antes` de `auditar_mfe.py`), um valor POR TOKEN distinto (media quando o
    token tem mais de um sinal -- nunca deixa um token pesar 2x so por ter mais sinais), separado por
    origem (PARTE 2c/FRENTE A: nunca somar ao_vivo com retro_lote1/replay_v3)."""
    resultados = [r for v in ("v1", "v2", "v3") for r in medir_versao(storage, v)]
    resultados += medir_retro_admitido(storage, db_path)
    resultados += medir_v3_replay(storage, db_path)
    por_origem: dict[str, dict[str, list[float]]] = {}
    for r in resultados:
        n = r.get("n_candles_vol_pos_24h_antes")
        if n is None:
            continue
        por_origem.setdefault(r["origem"], {}).setdefault(r["token"], []).append(float(n))
    out: dict[str, Any] = {}
    for origem, por_token in por_origem.items():
        valores_por_token = [statistics.fmean(vs) for vs in por_token.values()]
        out[origem] = {"quartis": _quartis(valores_por_token), "n_tokens_distintos": len(por_token)}
    return out


def formatar(pools: list[dict[str, Any]], atividade_pre_entrada: dict[str, Any]) -> str:
    out = ["# auditar_inatividade -- candles com negociacao real, tempo na vaga, motivo (SOMENTE LEITURA)",
          "", "Nenhum criterio novo decidido aqui -- so medicao (proposta de rotacao por inatividade "
          "fica so em texto, ver emenda).", ""]
    out.append(f"## Pools ativos ({len(pools)})")
    out.append("")
    out.append("| token | candles vol>0 (24h) | candles vol>0 (72h) | horas desde ultimo vol>0 | "
              "horas na vaga | motivo |")
    out.append("|---|---|---|---|---|---|")
    for p in sorted(pools, key=lambda x: x["symbol"]):
        h_vol = f"{p['horas_desde_ultimo_vol_pos']:.0f}" if p["horas_desde_ultimo_vol_pos"] is not None else (
            "s/d (nenhum candle com volume>0 ainda)" if p["n_candles_totais"] == 0 else "s/d")
        h_vaga = f"{p['horas_na_vaga']:.0f}" if p["horas_na_vaga"] is not None else "s/d"
        motivo = p["motivo"]
        if p["detalhe_bruto_quando_s_d"]:
            motivo = f"{motivo} ({p['detalhe_bruto_quando_s_d']})"
        if p["n_candles_totais"] == 0:
            motivo = f"sem nenhum candle 1h ainda | {motivo}"
        out.append(f"| {p['symbol']} | {p['n_vol_pos_24h']}/{p['n_candles_24h']} | "
                  f"{p['n_vol_pos_72h']}/{p['n_candles_72h']} | {h_vol} | {h_vaga} | {motivo} |")
    out.append("")
    out.append("## Atividade pre-entrada (24h antes), candles com volume>0, por token distinto")
    out.append("")
    for origem in ("ao_vivo", "retro_lote1", "replay_v3"):
        info = atividade_pre_entrada.get(origem)
        if info is None or info["quartis"] is None:
            out.append(f"  {origem}: s/d (sem sinal fechado com dado de volume)")
            continue
        q = info["quartis"]
        out.append(f"  {origem} ({info['n_tokens_distintos']} token(s) distinto(s)): "
                  f"Q1={q['q1']:.1f} | mediana={q['mediana']:.1f} | Q3={q['q3']:.1f} candles/24h")
    out.append("")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        now = time.time()
        pools = [medir_pool_ativo(storage, row, now) for row in storage.pr_pools("ativo")]
        atividade = atividade_pre_entrada_por_token(storage, db_path)
    finally:
        storage.close()
    return formatar(pools, atividade)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="auditar_inatividade: candles vol>0/vaga/motivo (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
