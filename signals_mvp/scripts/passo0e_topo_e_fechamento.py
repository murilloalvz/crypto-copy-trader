"""PEDIDO 2026-11-02 (Passo 0e, item 5): medicao empirica, SOMENTE LEITURA, sobre o banco real da
VM (`pr1_signals`/`pr2_signals`/`pr3_signals` + `pr_trajetoria`). Zero chamada de rede, zero escrita.

Responde, por versao (v1/v2/v3):
  - tempo de entrada até o toque no TOPO (P_peak) -- `tp1_price`/`tp1_ts` do proprio sinal: TP1
    dispara exatamente quando `bar.high >= TOPO` (`simulate_v1.py`), entao `tp1_ts - entry_ts` E a
    definicao literal de "tempo até o topo anterior" -- nenhum numero novo, so leitura do que ja
    esta gravado.
  - distribuicao do MFE (`pr_trajetoria.mfe_r`/`mfe_h`).
  - % que saiu por stop / EXIT FULL / TP1 (`pr*_signals.reason`, so fechados).
  - quantos NUNCA tocaram o topo dentro da janela de trajetoria (72h, `evidencia.JANELA_FECHAMENTO_H`)
    -- proxy de "72h e curto demais": sinais `fechado=1` (trajetoria) sem `tp1_ts`.

Limitacao documentada (nunca escondida): a coorte retrospectiva (`avaliar_candidatos_retro.py`,
`pr_retro_resultados`) NAO grava `tp1_ts`/`mfe_h` por sinal -- so `status`/`net_ret`/`r_mult` por
ENTRADA (`_simular_entrada`) -- por isso fica FORA deste relatorio; estender a coorte pra isso e
trabalho novo, nao fabricado aqui.

Resposta a pergunta do Passo 0e ("o desfecho de H1 e o R simulado ou o retorno de 72h da
trajetoria?"): e o R SIMULADO (`live.py: _atualizar_baseline`, linha onde `r_sinal = 100.0 *
signal["result_net"] / risco_pct_sinal` -- `result_net` vem de `simulate_v1`, TP1/EXIT FULL/stop,
NUNCA da janela fixa de 72h). Os campos de trajetoria (`mfe_r`/`ret_r_Xh`) sao SO diagnostico/
descritivo -- `_atualizar_baseline` nunca os le.
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..storage import Storage

JANELA_FECHAMENTO_H = 72.0   # evidencia.py: JANELA_FECHAMENTO_H -- mesma constante, nunca duplicada com valor diferente


def _signals_de(storage: Storage, versao: str) -> list[Any]:
    return {"v1": storage.pr1_signals, "v2": storage.pr2_signals, "v3": storage.pr3_signals}[versao]()


def medir_versao(storage: Storage, versao: str) -> dict[str, Any]:
    sinais = [s for s in _signals_de(storage, versao) if s["evento"] == "ENTRADA"]
    traj_por_entry = {r["entry_id"]: r for r in storage.pr_trajetoria_all() if r["versao"] == versao}
    fechados = [s for s in sinais if s["status"] == "fechado"]
    tempos_ate_topo_h: list[float] = []
    mfe_r: list[float] = []
    mfe_h: list[float] = []
    motivos: dict[str, int] = {}
    nunca_tocou_topo_72h = 0
    for s in fechados:
        motivos[s["reason"] or "s/d"] = motivos.get(s["reason"] or "s/d", 0) + 1
        traj = traj_por_entry.get(s["id"])
        if traj is not None:
            if traj["mfe_r"] is not None:
                mfe_r.append(traj["mfe_r"])
            if traj["mfe_h"] is not None:
                mfe_h.append(traj["mfe_h"])
        if s["tp1_price"] is not None and s["tp1_ts"] is not None and s["entry_price"] is not None:
            entry_ts = (traj["t_entrada"] if traj is not None else None) or s["ts_fechamento"]
            tempos_ate_topo_h.append((s["tp1_ts"] - entry_ts) / 3600.0)
        elif traj is not None and traj["fechado"]:
            nunca_tocou_topo_72h += 1
    def _resumo(vs: list[float]) -> Optional[dict[str, float]]:
        if not vs:
            return None
        vs_ord = sorted(vs)
        n = len(vs_ord)
        return {"n": n, "min": vs_ord[0], "p50": statistics.median(vs_ord), "max": vs_ord[-1],
                "media": statistics.fmean(vs_ord)}
    return {
        "versao": versao, "n_entradas": len(sinais), "n_fechados": len(fechados),
        "tempo_ate_topo_h": _resumo(tempos_ate_topo_h),
        "mfe_r": _resumo(mfe_r), "mfe_h": _resumo(mfe_h),
        "motivos_saida_pct": {k: 100.0 * v / len(fechados) for k, v in motivos.items()} if fechados else {},
        "nunca_tocou_topo_em_72h": nunca_tocou_topo_72h,
        "nunca_tocou_topo_em_72h_pct": (100.0 * nunca_tocou_topo_72h / len(fechados)) if fechados else None,
    }


def formatar(resultados: list[dict[str, Any]]) -> str:
    out = ["# Passo 0e -- tempo até o topo, MFE, motivo de saída, 72h (SOMENTE LEITURA)", ""]
    for r in resultados:
        out.append(f"## {r['versao'].upper()}")
        out.append(f"ENTRADA: {r['n_entradas']} | fechados: {r['n_fechados']}")
        tt = r["tempo_ate_topo_h"]
        out.append("tempo até o topo (h), só quem tocou: " +
                   (f"n={tt['n']} p50={tt['p50']:.1f}h min={tt['min']:.1f}h max={tt['max']:.1f}h média={tt['media']:.1f}h"
                    if tt else "s/d"))
        mr = r["mfe_r"]
        out.append("MFE (R): " + (f"n={mr['n']} p50={mr['p50']:+.2f} min={mr['min']:+.2f} max={mr['max']:+.2f}" if mr else "s/d"))
        mh = r["mfe_h"]
        out.append("MFE (horas até o pico favorável): " +
                   (f"n={mh['n']} p50={mh['p50']:.1f}h max={mh['max']:.1f}h" if mh else "s/d"))
        out.append("motivo de saída (%% dos fechados): " +
                   (", ".join(f"{k}={v:.1f}%" for k, v in sorted(r["motivos_saida_pct"].items())) or "s/d"))
        pct = r["nunca_tocou_topo_em_72h_pct"]
        out.append(f"nunca tocou o topo dentro de 72h: {r['nunca_tocou_topo_em_72h']} "
                  f"({pct:.1f}% dos fechados)" if pct is not None else "nunca tocou o topo dentro de 72h: s/d")
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
    parser = argparse.ArgumentParser(description="Passo 0e: tempo até o topo/MFE/motivo de saída/72h (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
