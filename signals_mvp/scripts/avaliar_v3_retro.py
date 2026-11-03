"""PEDIDO 2026-11-02 (continuacao, "Pendente" da emenda do mesmo dia)/2026-11-03 (Passo 0e, item 4):
script offline (ZERO chamada de rede) que aplica `ParamsV3` (congelado, `279b79ffa3f0`/`d57b4331d51d`
de V1/V2 NUNCA tocados -- hash proprio da V3, `56762db29cd6`, so leitura aqui) sobre duas fontes, as
DUAS a partir de `pr_bars` ja em cache:

  A) pools ADMITIDOS hoje (`pr_pools.status IN ('ativo','dormente','encerrado')`): replay causal
     COMPLETO do historico ja cacheado (mesmo padrao de `diagnostico_vagas.py: secao_a`) -- "o que a
     V3 teria visto desde que o bot comecou a acompanhar este pool", nunca uma comparacao controlada
     com/sem V3 (essa exigiria 2 rodadas reais, fora do escopo deste script).
  B) a coorte retrospectiva LOTE 1 ja congelada (`pr_retro_candidatos`, `avaliar_candidatos_retro.py`
     -- MESMA lista/hash, nunca recalculada), restrita ao subconjunto `admitido_apos_congelamento`
     (unico com candles em `pr_bars` sem precisar de rede -- ver
     `avaliar_candidatos_retro.py: _bars_truncados_de_pr_bars`/`processar_candidato`, reusado aqui
     SEM MUDANCA, so troca `params_v1`/`params_v2` por `params_v3` nos dois -- sinais_v1/sinais_v2
     saem identicos, o relatorio usa so `sinais_v1`). Candidatos do lote 1 NUNCA admitidos ficam fora
     (mesma limitacao documentada do Passo 0e/exit_lab para a coorte retro -- nunca escondida).

SOMENTE LEITURA: abre o banco com `mode=ro` (escrita e impossivel mesmo por engano). NUNCA chama
`_persistir_resultado`/grava em `pr_retro_resultados` -- essa tabela tem UMA linha por pool, o
resultado V1/V2 do lote 1 ja congelado; gravar aqui destruiria esse resultado. NUNCA toca
`ParamsV1`/`ParamsV2`/`ParamsV3`/hash/`pr1_signals`/`pr2_signals`/`pr3_signals`/`pr_retro_resultados`
-- relatorio NOVO, exploratorio, nunca soma a H1/H2-H7(V3)/qualquer desfecho confirmatorio.

Pendente explicito (nao feito aqui, por pedido do operador -- "e so depois o lote 2"): congelar um
NOVO lote 2 de candidatos (pools que apareceram em `pr_vaga_descartes` depois do congelamento do lote
1) fica para depois deste script existir e ser revisado -- nunca na mesma entrega.

Uso (na VM):
    python -m signals_mvp.scripts.avaliar_v3_retro --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.parte_a.pipeline import DEX_OF_LAUNCHPAD
from .avaliar_candidatos_retro import RISCO_IRREALISTA_MIN_PCT, _r_stats, _simular_entrada, processar_candidato
from .sensibilidade_parametros import _bars_do_pool, _created_ts

AVISO = "exploratorio/retro; offline a partir de pr_bars ja cacheado; nunca soma a H1/H2-H7 confirmatorio"


def _conectar_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def parte_a_pools_admitidos(con: sqlite3.Connection, params_v3: Any) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT pool, symbol, l_bc, grad_ts, launchpad, info FROM pr_pools WHERE status IN ('ativo', 'dormente', 'encerrado')"
    ).fetchall()
    costs = CostModel()
    tf = params_v3.timeframes[0]
    linhas: list[dict[str, Any]] = []
    for row in rows:
        bars = _bars_do_pool(con, row["pool"], tf)
        if not bars:
            linhas.append({"pool": row["pool"], "symbol": row["symbol"] or row["pool"],
                          "categoria": "sem_historico", "chegou_runner": False, "sinais": []})
            continue
        created_ts = _created_ts(row["info"])
        det = DetectorV1(params_v3, tf, row["l_bc"], row["grad_ts"], created_ts)
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        chegou_runner = False
        sinais: list[dict[str, Any]] = []
        for bar in bars:
            for ev in det.update(bar):
                if ev.kind == "RUNNER":
                    chegou_runner = True
                elif ev.kind == "ENTRADA":
                    sinais.append(_simular_entrada(bars, ev, params_v3, costs, dex, row["l_bc"]))
        linhas.append({"pool": row["pool"], "symbol": row["symbol"] or row["pool"], "categoria": "ok",
                      "chegou_runner": chegou_runner, "sinais": sinais})
    return linhas


def parte_b_coorte_lote1(con: sqlite3.Connection, params_v3: Any, now: float) -> tuple[list[dict[str, Any]], int]:
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "pr_retro_candidatos" not in tabelas:
        return [], 0
    candidatos = con.execute("SELECT * FROM pr_retro_candidatos").fetchall()
    costs = CostModel()
    linhas: list[dict[str, Any]] = []
    n_fora_do_alcance = 0
    for row in candidatos:
        pool_row = con.execute("SELECT added_ts FROM pr_pools WHERE pool=?", (row["pool"],)).fetchone()
        if pool_row is None or pool_row["added_ts"] is None:
            n_fora_do_alcance += 1
            continue
        resultado = processar_candidato(con, row, None, None, params_v3, params_v3, costs, now)
        linhas.append({"pool": resultado.pool, "symbol": resultado.symbol, "categoria": resultado.categoria,
                      "motivo_sem_historico": resultado.motivo_sem_historico,
                      "chegou_runner": resultado.chegou_runner, "sinais": resultado.sinais_v1})
    return linhas, n_fora_do_alcance


def formatar(linhas_a: list[dict[str, Any]], linhas_b: list[dict[str, Any]], n_fora_do_alcance_b: int,
            hash_v3: str) -> str:
    sinais_a = [s for l in linhas_a for s in l["sinais"]]
    sinais_b = [s for l in linhas_b for s in l["sinais"]]
    stats_a, stats_b = _r_stats(sinais_a), _r_stats(sinais_b)
    ok_a = [l for l in linhas_a if l["categoria"] == "ok"]
    ok_b = [l for l in linhas_b if l["categoria"] == "ok"]
    out = [f"# avaliar_v3_retro -- ParamsV3 ({hash_v3}) offline sobre pr_bars ({AVISO})", "",
          f"risco<{RISCO_IRREALISTA_MIN_PCT:.0f}% exclui o R (mesma regra de "
          f"`PosRunnerLive.RISCO_IRREALISTA_MIN_PCT`/avaliar_candidatos_retro.py, nunca uma regra nova).", ""]
    out.append("## A) pools admitidos hoje (ativo/dormente/encerrado), replay completo de pr_bars")
    out.append(f"pools: {len(linhas_a)} | com historico: {len(ok_a)} | chegaram a runner: "
              f"{sum(1 for l in ok_a if l['chegou_runner'])}")
    out.append(f"sinais: {stats_a['n_sinais']} | fechados: {stats_a['n_fechados']} | R valido: {stats_a['n_r_valido']} | "
              f"R medio: {stats_a['r_medio']:+.2f}" if stats_a['r_medio'] is not None else
              f"sinais: {stats_a['n_sinais']} | fechados: {stats_a['n_fechados']} | R valido: 0 | R medio: s/d")
    if stats_a["r_mediano"] is not None:
        out.append(f"R mediano: {stats_a['r_mediano']:+.2f} | taxa de acerto: {stats_a['taxa_acerto_pct']:.1f}%")
    out.append("")
    out.append(f"## B) coorte retrospectiva lote 1 (so admitido_apos_congelamento; fora do alcance "
              f"offline: {n_fora_do_alcance_b})")
    out.append(f"candidatos avaliados: {len(linhas_b)} | com historico: {len(ok_b)} | chegaram a runner: "
              f"{sum(1 for l in ok_b if l['chegou_runner'])}")
    if stats_b["r_medio"] is not None:
        out.append(f"sinais: {stats_b['n_sinais']} | fechados: {stats_b['n_fechados']} | R valido: {stats_b['n_r_valido']} | "
                  f"R medio: {stats_b['r_medio']:+.2f} | R mediano: {stats_b['r_mediano']:+.2f} | "
                  f"taxa de acerto: {stats_b['taxa_acerto_pct']:.1f}%")
    else:
        out.append(f"sinais: {stats_b['n_sinais']} | fechados: {stats_b['n_fechados']} | R valido: 0 | R medio: s/d")
    out.append("")
    out.append("Pendente (nao feito aqui, por pedido explicito): congelamento do lote 2 da coorte retro.")
    out.append("")
    out.append(f"({AVISO})")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    con = _conectar_ro(db_path)
    try:
        params_v3 = load_params_v3()
        linhas_a = parte_a_pools_admitidos(con, params_v3)
        linhas_b, n_fora = parte_b_coorte_lote1(con, params_v3, time.time())
        return formatar(linhas_a, linhas_b, n_fora, params_v3.version)
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="avaliar_v3_retro: ParamsV3 offline sobre pr_bars + coorte lote 1 (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
