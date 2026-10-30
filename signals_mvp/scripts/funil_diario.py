"""PEDIDO 2026-10-30 (FASE 2, item 1): funil diario (descoberta -> admissao -> runner -> caixa ->
sinal -> fechado) + ETA em dias at 30 tokens distintos fechados -- SOMENTE LEITURA (abre o SQLite em
`file:...?mode=ro`, zero chamada de rede, mesmo padrao de `scripts/sensibilidade_parametros.py`).

Cada etapa conta POOL DISTINTO por dia UTC (`time.gmtime`), nunca linha crua:
- descobertos: `pr_pools.found_ts`;
- admitidos: `pr_pools.added_ts`;
- runner / caixa: `pr_funil_marcos` (1a vez que o pool chega a cada etapa, V1 OU V2 -- novo nesta
  entrega, "runner"/"caixa" nunca tinham tabela propria antes);
- sinal: `pr1_signals`/`pr2_signals.ts_fechamento` (candle-gatilho da ENTRADA);
- fechado: `pr1_signals`/`pr2_signals.closed_ts` com `status='fechado'`.

Inclui os contadores da FASE 1 (`entradas_atrasadas`, `eventos_pre_admissao`) por dia, pra contexto.

ETA: taxa media de tokens distintos FECHADOS por dia desde o 1o fechamento -- "s/d" se nunca houve
fechamento ou a taxa e 0 (nunca chegaria).

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.funil_diario --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

ALVO_TOKENS_FECHADOS = 30


def _conectar_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _dia_utc(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _dias_distintos_por_pool(con: sqlite3.Connection, query: str, params: tuple = ()) -> dict[str, set[str]]:
    """{dia_utc: {pools distintos}} -- cada linha de `query` precisa devolver (ts, pool)."""
    out: dict[str, set[str]] = defaultdict(set)
    for row in con.execute(query, params):
        ts, pool = row[0], row[1]
        if ts is not None and pool is not None:
            out[_dia_utc(ts)].add(pool)
    return out


def montar_funil(con: sqlite3.Connection) -> dict[str, dict[str, int]]:
    descobertos = _dias_distintos_por_pool(con, "SELECT found_ts, pool FROM pr_pools WHERE found_ts IS NOT NULL")
    admitidos = _dias_distintos_por_pool(con, "SELECT added_ts, pool FROM pr_pools WHERE added_ts IS NOT NULL")
    runner = _dias_distintos_por_pool(con, "SELECT ts, pool FROM pr_funil_marcos WHERE etapa='runner'")
    caixa = _dias_distintos_por_pool(con, "SELECT ts, pool FROM pr_funil_marcos WHERE etapa='caixa'")
    sinal = _dias_distintos_por_pool(
        con, "SELECT ts_fechamento, pool FROM pr1_signals WHERE evento='ENTRADA' "
            "UNION SELECT ts_fechamento, pool FROM pr2_signals WHERE evento='ENTRADA'")
    fechado = _dias_distintos_por_pool(
        con, "SELECT closed_ts, pool FROM pr1_signals WHERE status='fechado' "
            "UNION SELECT closed_ts, pool FROM pr2_signals WHERE status='fechado'")
    dias = sorted(set(descobertos) | set(admitidos) | set(runner) | set(caixa) | set(sinal) | set(fechado))
    out: dict[str, dict[str, int]] = {}
    for dia in dias:
        out[dia] = {
            "descobertos": len(descobertos.get(dia, ())), "admitidos": len(admitidos.get(dia, ())),
            "runner": len(runner.get(dia, ())), "caixa": len(caixa.get(dia, ())),
            "sinal": len(sinal.get(dia, ())), "fechado": len(fechado.get(dia, ())),
        }
    return out


def _fase1_por_dia(con: sqlite3.Connection) -> tuple[dict[str, int], dict[str, int]]:
    entradas_atrasadas: dict[str, int] = defaultdict(int)
    for (ts,) in con.execute("SELECT ts FROM pr_entradas_atrasadas"):
        entradas_atrasadas[_dia_utc(ts)] += 1
    eventos_pre_admissao: dict[str, int] = defaultdict(int)
    for (ts,) in con.execute("SELECT ts FROM pr_eventos_pre_admissao"):
        eventos_pre_admissao[_dia_utc(ts)] += 1
    return dict(entradas_atrasadas), dict(eventos_pre_admissao)


def eta_dias_30_fechados(con: sqlite3.Connection, now: float, alvo: int = ALVO_TOKENS_FECHADOS) -> Optional[float]:
    """Dias restantes (projecao linear, taxa media desde o 1o fechamento) at `alvo` tokens
    distintos fechados -- `None` ("s/d") sem nenhum fechamento ainda ou taxa 0 (nunca chegaria)."""
    rows = con.execute(
        "SELECT closed_ts, pool FROM pr1_signals WHERE status='fechado' AND closed_ts IS NOT NULL "
        "UNION SELECT closed_ts, pool FROM pr2_signals WHERE status='fechado' AND closed_ts IS NOT NULL").fetchall()
    if not rows:
        return None
    pools_fechados = {r["pool"] for r in rows}
    ja_fechados = len(pools_fechados)
    if ja_fechados >= alvo:
        return 0.0
    primeiro_ts = min(r["closed_ts"] for r in rows)
    dias_passados = max((now - primeiro_ts) / 86_400.0, 1e-9)
    taxa_por_dia = ja_fechados / dias_passados
    if taxa_por_dia <= 0:
        return None
    return (alvo - ja_fechados) / taxa_por_dia


def formatar(funil: dict[str, dict[str, int]], fase1_atrasadas: dict[str, int], fase1_pre_admissao: dict[str, int],
            ja_fechados: int, eta: Optional[float]) -> str:
    out = ["# Funil diario -- POS-RUNNER (descoberta -> admissao -> runner -> caixa -> sinal -> fechado)", "",
          f"tokens distintos fechados (total): {ja_fechados}/{ALVO_TOKENS_FECHADOS}",
          f"ETA at {ALVO_TOKENS_FECHADOS} tokens distintos fechados: " +
          ("s/d (sem fechamento ainda ou taxa 0 -- nunca chegaria no ritmo atual)" if eta is None
           else f"{eta:.1f} dia(s) (projecao linear pela taxa media)"), "",
          "| dia (UTC) | descobertos | admitidos | runner | caixa | sinal | fechado | "
          "entradas_atrasadas | eventos_pre_admissao |",
          "|---|---|---|---|---|---|---|---|---|"]
    for dia, c in funil.items():
        out.append(f"| {dia} | {c['descobertos']} | {c['admitidos']} | {c['runner']} | {c['caixa']} | "
                  f"{c['sinal']} | {c['fechado']} | {fase1_atrasadas.get(dia, 0)} | "
                  f"{fase1_pre_admissao.get(dia, 0)} |")
    if not funil:
        out.append("(sem dados ainda)")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    con = _conectar_ro(db_path)
    try:
        now = time.time()
        funil = montar_funil(con)
        atrasadas, pre_admissao = _fase1_por_dia(con)
        rows = con.execute(
            "SELECT pool FROM pr1_signals WHERE status='fechado' "
            "UNION SELECT pool FROM pr2_signals WHERE status='fechado'").fetchall()
        ja_fechados = len({r["pool"] for r in rows})
        eta = eta_dias_30_fechados(con, now)
        return formatar(funil, atrasadas, pre_admissao, ja_fechados, eta)
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Funil diario do POS-RUNNER (PAPER / so leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
