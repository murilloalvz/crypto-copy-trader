"""PEDIDO 2026-11-02 (Passo 0e, item 5; CORRIGIDO na rodada seguinte -- relato do operador: MFE
+1.378.027 R na 1a versao). SOMENTE LEITURA sobre o banco real da VM (`pr1_signals`/`pr2_signals`/
`pr3_signals` + `pr_trajetoria`). Zero chamada de rede, zero escrita.

BUG da 1a versao: `pr_trajetoria.mfe_r`/`mae_r` sao R-multiplos (`movimento_% / risco_%`,
`evidencia.r_de`) -- com risco real colado perto de 0% (o MESMO caso que ja produziu os
-561R/-564R do McRib, `RISCO_IRREALISTA_MIN_PCT`/tag `risco_irrealista`), a divisao explode pra um
numero gigante e sem significado. A 1a versao deste script nunca aplicava a MESMA exclusao que
`/analise`/`_stats_r_de_fechados` ja aplicam ha rodadas -- corrigido aqui, reusando as MESMAS
funcoes (`analise.condicional._risco_irrealista`/`_contaminado_candle`/`RISCO_IRREALISTA_MIN_PCT`),
nunca uma regra nova.

Responde, por versao (v1/v2/v3), SO sobre a amostra limpa (contaminado_candle fora; risco<3%
reportado A PARTE, nunca misturado no R):
  - tempo de entrada até o toque no TOPO (P_peak) -- `tp1_ts - entry_ts`: TP1 dispara exatamente
    quando `bar.high >= TOPO` (`simulate_v1.py`), entao isso E a definicao literal de "tempo até o
    topo anterior" -- nenhum numero novo, so leitura do que ja esta gravado.
  - MFE/MAE em **% do preço de entrada** (`mfe_r * risco_pct` -- desfaz a divisao pelo risco, volta
    pro movimento de preço bruto; NUNCA em R quando risco<3%, sempre em % independente do risco).
  - R (MFE/MAE) SO para quem tem risco>=3% -- mesma régua de `RISCO_IRREALISTA_MIN_PCT`.
  - % que saiu por stop / EXIT FULL / TP1 (`reason`, só fechados, amostra limpa).
  - quantos NUNCA tocaram o topo dentro da janela de trajetória (72h) -- proxy de "72h é curto
    demais".
  - **listagem por sinal** (token, versão, entrada (preço), risco%, MFE%, MAE%, horas até o MFE,
    motivo de saída, se tocou o topo anterior).
  - **contagem por status/motivo de exclusão** -- explica por que `n_entradas` > `n_fechados`
    (aberto/cancelado/descontinuado/perdido_offline, e quantos saíram da amostra limpa por
    contaminado_candle/risco_irrealista) -- SEM isso, a pergunta "por que V1 tem 7 ENTRADA e 4
    fechadas" não tem resposta rastreável.

Limitação documentada (nunca escondida): a coorte retrospectiva (`avaliar_candidatos_retro.py`,
`pr_retro_resultados`) NÃO grava `tp1_ts`/`mfe_h` por sinal -- só `status`/`net_ret`/`r_mult` por
ENTRADA (`_simular_entrada`) -- por isso fica FORA deste relatório.

Resposta à pergunta do Passo 0e ("o desfecho de H1 é o R simulado ou o retorno de 72h da
trajetória?"): é o R SIMULADO (`live.py: _atualizar_baseline`, `r_sinal = 100.0 *
signal["result_net"] / risco_pct_sinal` -- `result_net` vem de `simulate_v1`, TP1/EXIT FULL/stop,
NUNCA da janela fixa de 72h). Os campos de trajetória (`mfe_r`/`ret_r_Xh`) são SÓ diagnóstico/
descritivo -- `_atualizar_baseline` nunca os lê.
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics
from pathlib import Path
from typing import Any, Optional

from ..analise.condicional import RISCO_IRREALISTA_MIN_PCT, _contaminado_candle, _risco_irrealista
from ..config import make_paths
from ..storage import Storage

JANELA_FECHAMENTO_H = 72.0   # evidencia.py: JANELA_FECHAMENTO_H -- mesma constante, nunca duplicada com valor diferente


def _signals_de(storage: Storage, versao: str) -> list[Any]:
    return {"v1": storage.pr1_signals, "v2": storage.pr2_signals, "v3": storage.pr3_signals}[versao]()


def _resumo(vs: list[float]) -> Optional[dict[str, float]]:
    if not vs:
        return None
    vs_ord = sorted(vs)
    n = len(vs_ord)
    return {"n": n, "min": vs_ord[0], "p50": statistics.median(vs_ord), "max": vs_ord[-1], "media": statistics.fmean(vs_ord)}


def medir_versao(storage: Storage, versao: str) -> dict[str, Any]:
    todos = [s for s in _signals_de(storage, versao) if s["evento"] == "ENTRADA"]
    traj_por_entry = {r["entry_id"]: r for r in storage.pr_trajetoria_all() if r["versao"] == versao}

    # PEDIDO (correcao): contagem por status/exclusao -- responde "por que n_entradas > n_fechados".
    contagem_status: dict[str, int] = {}
    for s in todos:
        contagem_status[s["status"]] = contagem_status.get(s["status"], 0) + 1
    fechados_brutos = [s for s in todos if s["status"] == "fechado"]
    contaminados = [s for s in fechados_brutos if _contaminado_candle(s)]
    risco_baixo = [s for s in fechados_brutos if not _contaminado_candle(s) and _risco_irrealista(s)]
    limpos = [s for s in fechados_brutos if not _contaminado_candle(s) and not _risco_irrealista(s)]

    def _linha(s: Any, limpo: bool) -> dict[str, Any]:
        traj = traj_por_entry.get(s["id"])
        risco_pct = traj["risco_pct"] if traj is not None and traj["risco_pct"] else None
        mfe_pct = (traj["mfe_r"] * risco_pct) if (traj is not None and traj["mfe_r"] is not None and risco_pct) else None
        mae_pct = (traj["mae_r"] * risco_pct) if (traj is not None and traj["mae_r"] is not None and risco_pct) else None
        return {
            "token": s["symbol"] or (s["mint"] or "")[:8], "versao": versao,
            "entrada": s["entry_price"], "risco_pct": risco_pct,
            "mfe_pct": mfe_pct, "mae_pct": mae_pct,
            "mfe_r": (traj["mfe_r"] if (limpo and traj is not None) else None),
            "mae_r": (traj["mae_r"] if (limpo and traj is not None) else None),
            "mfe_h": traj["mfe_h"] if traj is not None else None,
            "motivo_saida": s["reason"] or "s/d",
            "tocou_topo": s["tp1_price"] is not None and s["tp1_ts"] is not None,
        }

    linhas_limpas = [_linha(s, True) for s in limpos]
    linhas_risco_baixo = [_linha(s, False) for s in risco_baixo]

    tempos_ate_topo_h = []
    nunca_tocou_topo_72h = 0
    motivos: dict[str, int] = {}
    for s in limpos:
        motivos[s["reason"] or "s/d"] = motivos.get(s["reason"] or "s/d", 0) + 1
        traj = traj_por_entry.get(s["id"])
        if s["tp1_price"] is not None and s["tp1_ts"] is not None:
            entry_ts = (traj["t_entrada"] if traj is not None else None) or s["ts_fechamento"]
            tempos_ate_topo_h.append((s["tp1_ts"] - entry_ts) / 3600.0)
        elif traj is not None and traj["fechado"]:
            nunca_tocou_topo_72h += 1

    return {
        "versao": versao, "n_entradas": len(todos), "contagem_status": contagem_status,
        "n_fechados_brutos": len(fechados_brutos), "n_contaminados": len(contaminados),
        "n_risco_baixo": len(risco_baixo), "n_limpos": len(limpos),
        "tempo_ate_topo_h": _resumo(tempos_ate_topo_h),
        "mfe_pct": _resumo([l["mfe_pct"] for l in linhas_limpas if l["mfe_pct"] is not None]),
        "mae_pct": _resumo([l["mae_pct"] for l in linhas_limpas if l["mae_pct"] is not None]),
        "mfe_r": _resumo([l["mfe_r"] for l in linhas_limpas if l["mfe_r"] is not None]),
        "mfe_h": _resumo([l["mfe_h"] for l in linhas_limpas if l["mfe_h"] is not None]),
        "motivos_saida_pct": {k: 100.0 * v / len(limpos) for k, v in motivos.items()} if limpos else {},
        "nunca_tocou_topo_em_72h": nunca_tocou_topo_72h,
        "nunca_tocou_topo_em_72h_pct": (100.0 * nunca_tocou_topo_72h / len(limpos)) if limpos else None,
        "linhas_limpas": linhas_limpas, "linhas_risco_baixo": linhas_risco_baixo,
    }


def _fmt_linha(l: dict[str, Any]) -> str:
    entrada = f"{l['entrada']:,.0f}" if l["entrada"] is not None else "s/d"
    risco = f"{l['risco_pct']:.1f}%" if l["risco_pct"] is not None else "s/d"
    mfe = f"{l['mfe_pct']:+.1f}%" if l["mfe_pct"] is not None else "s/d"
    mae = f"{l['mae_pct']:+.1f}%" if l["mae_pct"] is not None else "s/d"
    mfe_r_txt = f" ({l['mfe_r']:+.2f}R)" if l["mfe_r"] is not None else ""
    h = f"{l['mfe_h']:.1f}h" if l["mfe_h"] is not None else "s/d"
    topo = "sim" if l["tocou_topo"] else "não"
    return (f"| {l['token']} | {l['versao']} | {entrada} | {risco} | {mfe}{mfe_r_txt} | {mae} | "
           f"{h} | {l['motivo_saida']} | {topo} |")


def formatar(resultados: list[dict[str, Any]]) -> str:
    out = ["# Passo 0e -- tempo até o topo, MFE/MAE, motivo de saída, 72h (SOMENTE LEITURA)", "",
          f"Exclusões aplicadas (MESMAS de `/analise`): `contaminado_candle` fora; risco<"
          f"{RISCO_IRREALISTA_MIN_PCT:.0f}% reportado à parte, nunca misturado no R/MFE%/MAE% da "
          f"amostra limpa.", ""]
    for r in resultados:
        out.append(f"## {r['versao'].upper()}")
        status_txt = ", ".join(f"{k}={v}" for k, v in sorted(r["contagem_status"].items()))
        out.append(f"ENTRADA: {r['n_entradas']} | por status: {status_txt or 's/d'}")
        out.append(f"fechados: {r['n_fechados_brutos']} | contaminado_candle (fora): {r['n_contaminados']} | "
                  f"risco<{RISCO_IRREALISTA_MIN_PCT:.0f}% (à parte): {r['n_risco_baixo']} | "
                  f"amostra limpa: {r['n_limpos']}")
        tt = r["tempo_ate_topo_h"]
        out.append("tempo até o topo (h), só quem tocou (amostra limpa): " +
                   (f"n={tt['n']} p50={tt['p50']:.1f}h min={tt['min']:.1f}h max={tt['max']:.1f}h média={tt['media']:.1f}h"
                    if tt else "s/d"))
        mp = r["mfe_pct"]
        out.append("MFE (% do preço de entrada, amostra limpa): " +
                   (f"n={mp['n']} p50={mp['p50']:+.1f}% min={mp['min']:+.1f}% max={mp['max']:+.1f}%" if mp else "s/d"))
        ap = r["mae_pct"]
        out.append("MAE (% do preço de entrada, amostra limpa): " +
                   (f"n={ap['n']} p50={ap['p50']:+.1f}% min={ap['min']:+.1f}% max={ap['max']:+.1f}%" if ap else "s/d"))
        mr = r["mfe_r"]
        out.append(f"MFE (R, só risco>={RISCO_IRREALISTA_MIN_PCT:.0f}%): " +
                   (f"n={mr['n']} p50={mr['p50']:+.2f} min={mr['min']:+.2f} max={mr['max']:+.2f}" if mr else "s/d"))
        mh = r["mfe_h"]
        out.append("MFE (horas até o pico favorável): " +
                   (f"n={mh['n']} p50={mh['p50']:.1f}h max={mh['max']:.1f}h" if mh else "s/d"))
        out.append("motivo de saída (%% da amostra limpa): " +
                   (", ".join(f"{k}={v:.1f}%" for k, v in sorted(r["motivos_saida_pct"].items())) or "s/d"))
        pct = r["nunca_tocou_topo_em_72h_pct"]
        out.append(f"nunca tocou o topo dentro de 72h: {r['nunca_tocou_topo_em_72h']} "
                  f"({pct:.1f}% da amostra limpa)" if pct is not None else "nunca tocou o topo dentro de 72h: s/d")
        out.append("")
    out.append("## Por sinal (amostra limpa)")
    out.append("")
    out.append("| token | versão | entrada | risco% | MFE% | MAE% | h até MFE | motivo saída | tocou topo? |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in resultados:
        for l in r["linhas_limpas"]:
            out.append(_fmt_linha(l))
    linhas_risco = [l for r in resultados for l in r["linhas_risco_baixo"]]
    if linhas_risco:
        out.append("")
        out.append(f"## Por sinal -- risco<{RISCO_IRREALISTA_MIN_PCT:.0f}% (à parte, R/MFE-R nunca calculados)")
        out.append("")
        out.append("| token | versão | entrada | risco% | MFE% | MAE% | h até MFE | motivo saída | tocou topo? |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for l in linhas_risco:
            out.append(_fmt_linha(l))
    out.append("")
    out.append("Limitação: coorte retrospectiva (avaliar_candidatos_retro.py) não grava tp1_ts/mfe_h "
              "por sinal -- fora deste relatório (ver docstring do módulo).")
    out.append("")
    out.append("Resposta à pergunta do Passo 0e: H1 decide pelo R SIMULADO (live.py: "
              "_atualizar_baseline, `r_sinal = 100.0 * signal['result_net'] / risco_pct_sinal` -- "
              "result_net vem de simulate_v1/TP1-EXIT FULL-stop), NUNCA pelo retorno fixo de 72h "
              "da trajetória (mfe_r/ret_r_Xh são só diagnóstico, nunca lidos por _atualizar_baseline).")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        resultados = [medir_versao(storage, v) for v in ("v1", "v2", "v3")]
        return formatar(resultados)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Passo 0e: tempo até o topo/MFE-MAE/motivo de saída/72h (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
