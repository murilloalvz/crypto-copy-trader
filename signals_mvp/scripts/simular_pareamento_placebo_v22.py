"""RODADA 22 (2026-11-17), condição 2 do operador (aceite condicional): simulação RETROATIVA, SEM
DESFECHO (nunca mede R/outcome, só CONTAGEM de candidatos), de quantos placebos a regra NOVA de
pareamento (`PosRunnerLive._carteiras_pools_controle`, fase+tf+idade±50%+volume 0,1x-10x) teria
produzido para cada sinal V3 JÁ EXISTENTE (`pr3_signals`, evento=ENTRADA), comparado com a regra
ANTIGA (só fase+tf). PAPER/READ-ONLY, zero chamada de rede, zero escrita em qualquer tabela.
Detector/ParamsV1/ParamsV3/H1/critério de sinal NUNCA alterados — reusa `DetectorV1`/`ParamsV1`
exatamente como `avaliar_v3_retro.py`/`varredura_v3.py` já fazem para backtest.

ESTA SESSÃO (cloud isolada) NÃO TEM ACESSO ao banco SQLite real da VM (os 21 sinais citados pelo
operador) — este script foi ESCRITO e testado com dados SINTÉTICOS
(`signals_mvp/tests/test_simular_pareamento_placebo_v22.py`), mas NUNCA RODADO contra o banco real.
O operador precisa rodar o comando abaixo na VM e colar o resultado.

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.simular_pareamento_placebo_v22 --db signals_mvp/dados/estado.sqlite

LIMITAÇÕES DE DADO, declaradas explicitamente (nunca escondidas):
1. **Idade** (`grad_ts`) é reconstruída com precisão histórica exata — `pr_pools.grad_ts` é
   imutável por pool, nunca muda depois de gravado.
2. **Volume** (`info.vol_h24_usd`) usa o valor ATUAL de `pr_pools.info` — `pr_pools` NUNCA guarda uma
   série histórica de volume, só o último valor lido. Para sinais antigos, isto é uma APROXIMAÇÃO
   (o volume real do candidato NO INSTANTE do sinal histórico pode ter sido diferente do atual) —
   nunca um dado inventado, mas também nunca o dado exato daquele instante. Reportado separadamente
   (com e sem o filtro de volume) para o operador avaliar o impacto desta aproximação.
3. **Posição aberta** usa o status ATUAL (hoje) de `pr1_signals`/`pr2_signals`/`pr3_signals` para
   decidir se um candidato "tinha posição aberta" — não o status HISTÓRICO no instante do sinal
   (o schema atual não grava quando uma posição abriu/fechou de forma que permita reconstruir o
   status em um instante arbitrário do passado). Isto pode excluir candidatos que hoje estão
   abertos mas não estavam no instante do sinal antigo (subestima levemente a contagem antiga), ou
   incluir candidatos que fecharam depois (superestima levemente) — efeito esperado pequeno dado que
   a maioria dos sinais é recente.
4. **Fase** (runner/pullback/sem_fase) É reconstruída com precisão (replay completo de `DetectorV1`
   sobre `pr_bars` até o instante do sinal, nunca lookahead) — não é uma aproximação.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import PHASE_PULLBACK, PHASE_RUNNER, DetectorV1
from ..pos_runner.params_v1 import load_params_v1

PLACEBO_FAIXA_IDADE_FRAC = 0.5
PLACEBO_FAIXA_VOLUME_MULT = 10.0


def _conectar_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _bars_ate(con: sqlite3.Connection, pool: str, tf: str, ate_ts: float) -> list[Bar]:
    rows = con.execute(
        "SELECT ts,o,h,l,c,v,filled FROM pr_bars WHERE pool=? AND tf=? AND ts<=? ORDER BY ts",
        (pool, tf, ate_ts),
    ).fetchall()
    return [Bar(int(r["ts"]), r["o"], r["h"], r["l"], r["c"], r["v"], bool(r["filled"])) for r in rows]


def _fase_em(con: sqlite3.Connection, pool: str, tf: str, ate_ts: float, l_bc: Optional[float],
            grad_ts: Optional[float], created_ts: Optional[float]) -> str:
    """MESMO mapeamento de `PosRunnerLive._fase_label_v1` -- replay de `DetectorV1` (ParamsV1
    CONGELADO) sobre os candles JA fechados ate `ate_ts` (nunca lookahead: bar.ts<=ate_ts)."""
    bars = _bars_ate(con, pool, tf, ate_ts)
    if not bars:
        return "sem_fase"
    det = DetectorV1(load_params_v1(), tf, l_bc, grad_ts, created_ts)
    for bar in bars:
        list(det.update(bar))
    if det.phase == PHASE_PULLBACK:
        return "pullback"
    if det.phase == PHASE_RUNNER:
        return "runner"
    return "sem_fase"


def _vol_h24(info_json: Optional[str]) -> Optional[float]:
    try:
        info = json.loads(info_json or "{}")
    except (TypeError, ValueError):
        return None
    vol = info.get("vol_h24_usd") if isinstance(info, dict) else None
    return float(vol) if isinstance(vol, (int, float)) else None


def _posicao_aberta_hoje(con: sqlite3.Connection, pool: str) -> bool:
    """APROXIMAÇÃO declarada no docstring do módulo -- status ATUAL, nunca o histórico exato."""
    for tabela in ("pr1_signals", "pr2_signals", "pr3_signals"):
        row = con.execute(f"SELECT 1 FROM {tabela} WHERE pool=? AND status='aberto' LIMIT 1", (pool,)).fetchone()
        if row is not None:
            return True
    return False


def candidatos_para_sinal(con: sqlite3.Connection, pool_gatilho: str, tf: str, ts_corte: float,
                          k: int, usar_idade_volume: bool) -> list[str]:
    """MESMA lógica de `PosRunnerLive._carteiras_pools_controle`, reconstruída retroativamente.
    `usar_idade_volume=False` reproduz a regra ANTIGA (só fase+tf); `True` aplica a regra NOVA desta
    rodada. Nunca lê nada depois de `ts_corte` (sem lookahead)."""
    pools = con.execute(
        "SELECT pool, l_bc, grad_ts, info FROM pr_pools WHERE status IN ('ativo', 'dormente', 'encerrado')"
    ).fetchall()
    l_bc_g, grad_ts_g, info_g = _covariaveis(con, pool_gatilho)
    fase_gatilho = _fase_em(con, pool_gatilho, tf, ts_corte, l_bc_g, grad_ts_g, None)
    idade_gatilho = (ts_corte - grad_ts_g) if grad_ts_g else None
    vol_gatilho = _vol_h24(info_g)

    candidatos = []
    for row in pools:
        pool = row["pool"]
        if pool == pool_gatilho:
            continue
        if _fase_em(con, pool, tf, ts_corte, row["l_bc"], row["grad_ts"], None) != fase_gatilho:
            continue
        if _posicao_aberta_hoje(con, pool):
            continue
        if usar_idade_volume and (idade_gatilho is not None or vol_gatilho is not None):
            if idade_gatilho is not None:
                if not row["grad_ts"]:
                    continue
                idade_c = ts_corte - row["grad_ts"]
                if not (idade_gatilho * (1.0 - PLACEBO_FAIXA_IDADE_FRAC)
                        <= idade_c <= idade_gatilho * (1.0 + PLACEBO_FAIXA_IDADE_FRAC)):
                    continue
            if vol_gatilho is not None:
                vol_c = _vol_h24(row["info"])
                if vol_c is None:
                    continue
                if not (vol_gatilho / PLACEBO_FAIXA_VOLUME_MULT
                        <= vol_c <= vol_gatilho * PLACEBO_FAIXA_VOLUME_MULT):
                    continue
        candidatos.append(pool)
    return sorted(candidatos)[:k]


def _covariaveis(con: sqlite3.Connection, pool: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    row = con.execute("SELECT l_bc, grad_ts, info FROM pr_pools WHERE pool=?", (pool,)).fetchone()
    if row is None:
        return None, None, None
    return row["l_bc"], row["grad_ts"], row["info"]


def simular(con: sqlite3.Connection, k: int = 3) -> dict[str, Any]:
    sinais = con.execute(
        "SELECT pool, tf, ts_fechamento FROM pr3_signals WHERE evento='ENTRADA' ORDER BY ts_fechamento"
    ).fetchall()
    linhas = []
    for s in sinais:
        antiga = candidatos_para_sinal(con, s["pool"], s["tf"], s["ts_fechamento"], k, usar_idade_volume=False)
        nova = candidatos_para_sinal(con, s["pool"], s["tf"], s["ts_fechamento"], k, usar_idade_volume=True)
        linhas.append({"pool": s["pool"], "tf": s["tf"], "ts_fechamento": s["ts_fechamento"],
                      "n_antiga": len(antiga), "n_nova": len(nova)})
    n = len(linhas)
    n_com_1_antiga = sum(1 for l in linhas if l["n_antiga"] >= 1)
    n_com_3_antiga = sum(1 for l in linhas if l["n_antiga"] >= k)
    n_com_1_nova = sum(1 for l in linhas if l["n_nova"] >= 1)
    n_com_3_nova = sum(1 for l in linhas if l["n_nova"] >= k)
    return {"n_sinais": n, "linhas": linhas,
           "pct_1_antiga": (100.0 * n_com_1_antiga / n) if n else None,
           "pct_3_antiga": (100.0 * n_com_3_antiga / n) if n else None,
           "pct_1_nova": (100.0 * n_com_1_nova / n) if n else None,
           "pct_3_nova": (100.0 * n_com_3_nova / n) if n else None,
           "n_com_1_antiga": n_com_1_antiga, "n_com_3_antiga": n_com_3_antiga,
           "n_com_1_nova": n_com_1_nova, "n_com_3_nova": n_com_3_nova}


def relatorio(resultado: dict[str, Any]) -> str:
    n = resultado["n_sinais"]
    out = [
        "# simular_pareamento_placebo_v22 -- RETROATIVO, SEM DESFECHO, EXPLORATÓRIO",
        "",
        "AVISO: nunca mede R/outcome, nunca entra em H1/N=30/N=60. Volume usa o valor ATUAL de "
        "pr_pools.info (aproximação para sinais antigos); posição aberta usa o status ATUAL (hoje), "
        "nunca o histórico exato -- ver docstring do módulo para as 4 limitações declaradas.",
        "",
        f"Sinais V3 (ENTRADA) encontrados: {n}",
    ]
    if n == 0:
        out.append("(nenhum sinal -- nada a reportar)")
        return "\n".join(out)
    out.append(f"Regra ANTIGA (só fase+tf): >=1 placebo em {resultado['n_com_1_antiga']}/{n} "
              f"({resultado['pct_1_antiga']:.0f}%) | >=3 (K cheio) em {resultado['n_com_3_antiga']}/{n} "
              f"({resultado['pct_3_antiga']:.0f}%)")
    out.append(f"Regra NOVA (fase+tf+idade±50%+volume 0,1x-10x): >=1 placebo em "
              f"{resultado['n_com_1_nova']}/{n} ({resultado['pct_1_nova']:.0f}%) | >=3 (K cheio) em "
              f"{resultado['n_com_3_nova']}/{n} ({resultado['pct_3_nova']:.0f}%)")
    if resultado["pct_1_nova"] is not None and resultado["pct_1_nova"] < 60.0:
        out.append("")
        out.append(f"!!! <60% dos sinais teriam >=1 placebo sob a regra nova "
                  f"({resultado['pct_1_nova']:.0f}%) -- proposta de afrouxamento (escolha do "
                  f"operador, nenhuma aplicada automaticamente):")
        out.append("  (a) ampliar as faixas: idade ±50% -> ±100%, volume 0,1x-10x -> 0,03x-30x "
                  "(1,5 ordem de grandeza pra cada lado em vez de 1);")
        out.append("  (b) ampliar o universo de candidatos: hoje só pools com status "
                  "ativo/dormente/encerrado E mesmo tf do sinal -- considerar incluir pools "
                  "'verificado' (ainda sem lineage completa) se a amostra continuar pequena;")
        out.append("  (c) manter a regra antiga (só fase+tf) e usar idade/volume só como "
                  "DIAGNÓSTICO reportado, nunca como filtro que reduz K -- perde o pareamento mas "
                  "preserva o tamanho da amostra do braço placebo.")
    out.append("")
    out.append("Detalhe por sinal (pool, tf, ts_fechamento, n_antiga, n_nova):")
    for l in resultado["linhas"]:
        out.append(f"  {l['pool']} {l['tf']} {l['ts_fechamento']}: antiga={l['n_antiga']} nova={l['n_nova']}")
    return "\n".join(out)


def executar(db_path: Path, k: int = 3) -> str:
    con = _conectar_ro(db_path)
    try:
        resultado = simular(con, k)
    finally:
        con.close()
    return relatorio(resultado)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--k", type=int, default=3, help="MESMO K de carteiras_placebo_k (padrão 3)")
    args = parser.parse_args(argv)
    print(executar(args.db, args.k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
