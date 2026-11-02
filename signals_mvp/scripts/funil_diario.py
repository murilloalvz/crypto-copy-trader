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

PEDIDO 2026-11-02 (FASE 1e): tabela ganha `aposentados`/`readmitidos` por dia (`pr_dormentes.ts_
dormente`/`ts_readmitido` -- MESMOS eventos que `saude.py` ja conta nas ultimas 24h, aqui por dia
completo). Nova secao "% runner (7d)": dos pools ADMITIDOS nos ultimos 7 dias, quantos ja chegaram
a `pr_funil_marcos.etapa='runner'` -- janela movel, nunca o total acumulado (um pool admitido ontem
ainda nao teve tempo de formar runner; a janela de 7d da chance real). Alertas Telegram em N=15/N=30
(`live.py: checar_e_alertar_marcos_funil`, idempotente) sao do bot ao vivo, nao deste script.

PEDIDO 2026-11-02 (FASE 1c, consolidado aqui -- `saude.py` ja estava no teto de 60 linhas): secao
"Uso de API (24h)" -- chamadas/h por finalidade (`pr_api_uso`; sombra/radar sempre 0 POR DESENHO,
reusam o candle que `poll_pool` ja buscou, nunca uma chamada propria; `baseline`/`trajetoria`/
`carteiras`/`verificacao_candidato`/`coorte_retro` ainda NAO instrumentados nesta rodada -- proximo
passo, ver ESTADO_2026-11-02.md) e 429/h; e "Latencia do candle (24h)" -- segundos entre o
FECHAMENTO do candle de 1h e o processamento pelo detector (`pr_candle_latencia`): p50/p95/max e
quantas ENTRADAS teriam ficado perto (>=80%) do limiar de `_late()` (1h, `max(900s, step)`) -- se o
p95 estiver perto do limiar, isto fica destacado.

PEDIDO 2026-11-02 (FASE 1d, consolidado aqui pelo mesmo motivo): secao "Capacidade (RSS)" -- RSS
atual do processo (`/proc/self/status`) / pools ativos NAQUELE instante, media e pior caso das
amostras das ultimas 24h (`pr_rss_amostra`, a cada 15min no bot ao vivo), e quantos pools A MAIS
cabem com 200MB de folga ALEM do uso atual (nunca um teto absoluto do sistema -- so "quanto sobra
daqui"). Aproximacao HONESTA: RSS/pool aqui inclui a memoria FIXA do processo (nao so por pool),
entao supervaloriza o custo marginal real de cada pool extra -- documentado, nao corrigido nesta
rodada. NUNCA sugere/altera `max_pools`.

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.funil_diario --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

ALVO_TOKENS_FECHADOS = 30
LATE_LIMIAR_S = 3600.0   # mesmo limiar de `_late()` p/ ENTRADA 1h (`max(900.0, float(det.step))`)
LATE_PROXIMO_FRACAO = 0.8   # "perto do limiar" = >= 80% dele


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
    # PEDIDO 2026-11-02 (FASE 1e): aposentados (rotacao por incapacidade estrutural, vai pra
    # 'dormente') e readmitidos (`_recheck_dormentes`) -- MESMOS eventos de `pr_dormentes` que
    # `saude.py` ja conta nas ultimas 24h.
    aposentados = _dias_distintos_por_pool(con, "SELECT ts_dormente, pool FROM pr_dormentes")
    readmitidos = _dias_distintos_por_pool(
        con, "SELECT ts_readmitido, pool FROM pr_dormentes WHERE status='readmitido'")
    dias = sorted(set(descobertos) | set(admitidos) | set(runner) | set(caixa) | set(sinal) | set(fechado)
                 | set(aposentados) | set(readmitidos))
    out: dict[str, dict[str, int]] = {}
    for dia in dias:
        out[dia] = {
            "descobertos": len(descobertos.get(dia, ())), "admitidos": len(admitidos.get(dia, ())),
            "runner": len(runner.get(dia, ())), "caixa": len(caixa.get(dia, ())),
            "sinal": len(sinal.get(dia, ())), "fechado": len(fechado.get(dia, ())),
            "aposentados": len(aposentados.get(dia, ())), "readmitidos": len(readmitidos.get(dia, ())),
        }
    return out


def pct_runner_7d(con: sqlite3.Connection, now: float) -> Optional[float]:
    """Dos pools ADMITIDOS nos ultimos 7 dias (janela movel -- um pool admitido ontem ainda nao
    teve tempo de formar runner), quantos ja chegaram a `etapa='runner'` -- `None` ("s/d") sem
    nenhum admitido na janela."""
    desde = now - 7 * 86_400.0
    admitidos = {r["pool"] for r in con.execute(
        "SELECT pool FROM pr_pools WHERE added_ts IS NOT NULL AND added_ts>=?", (desde,))}
    if not admitidos:
        return None
    runners = {r["pool"] for r in con.execute(
        "SELECT DISTINCT pool FROM pr_funil_marcos WHERE etapa='runner' AND ts>=?", (desde,))}
    return 100.0 * len(admitidos & runners) / len(admitidos)


def uso_api_24h(con: sqlite3.Connection, now: float) -> dict[str, Any]:
    """PEDIDO 2026-11-02 (FASE 1c; 3a rodada Fix B: 429/h TAMBEM por finalidade, nao so agregado):
    chamadas/h por finalidade + 429/h por finalidade, ultimas 24h."""
    desde = now - 24 * 3600.0
    por_finalidade: dict[str, int] = defaultdict(int)
    for r in con.execute("SELECT finalidade, COUNT(*) AS n FROM pr_api_uso WHERE ts>=? GROUP BY finalidade", (desde,)):
        por_finalidade[r["finalidade"]] = r["n"]
    rate_limited_por_finalidade: dict[str, int] = defaultdict(int)
    for r in con.execute(
        "SELECT finalidade, COUNT(*) AS n FROM pr_api_uso WHERE ts>=? AND rate_limited=1 GROUP BY finalidade", (desde,)
    ):
        rate_limited_por_finalidade[r["finalidade"]] = r["n"]
    return {
        "chamadas_h": {k: v / 24.0 for k, v in por_finalidade.items()},
        "rate_limited_h": sum(rate_limited_por_finalidade.values()) / 24.0,
        "rate_limited_h_por_finalidade": {k: v / 24.0 for k, v in rate_limited_por_finalidade.items()},
    }


def latencia_candle_24h(con: sqlite3.Connection, now: float) -> dict[str, Any]:
    """PEDIDO 2026-11-02 (FASE 1c): p50/p95/max da latencia do candle (24h) + quantas ficaram perto
    (>=80%) do limiar de `_late()` (1h)."""
    desde = now - 24 * 3600.0
    valores = sorted(r["latencia_s"] for r in con.execute("SELECT latencia_s FROM pr_candle_latencia WHERE ts>=?", (desde,)))
    if not valores:
        return {"p50": None, "p95": None, "max": None, "n_perto_do_limiar": 0, "n": 0}
    quantis = statistics.quantiles(valores, n=100, method="inclusive") if len(valores) >= 2 else [valores[0]] * 99
    p50 = quantis[49] if len(valores) >= 2 else valores[0]
    p95 = quantis[94] if len(valores) >= 2 else valores[0]
    perto = sum(1 for v in valores if v >= LATE_PROXIMO_FRACAO * LATE_LIMIAR_S)
    return {"p50": p50, "p95": p95, "max": valores[-1], "n_perto_do_limiar": perto, "n": len(valores)}


FOLGA_RSS_KB = 200 * 1024   # PEDIDO 2026-11-02 (FASE 1d): 200MB de folga ALEM do uso atual


def capacidade_rss_24h(con: sqlite3.Connection, now: float) -> dict[str, Any]:
    """PEDIDO 2026-11-02 (FASE 1d): RSS/pool medio e pior caso das amostras das ultimas 24h, e
    quantos pools A MAIS cabem com `FOLGA_RSS_KB` de folga -- aproximacao (RSS/pool inclui memoria
    FIXA do processo, nunca so o custo marginal -- ver docstring do modulo). NUNCA sugere alterar
    `max_pools`."""
    desde = now - 24 * 3600.0
    por_pool = [r["rss_kb"] / r["n_pools_ativos"] for r in con.execute(
        "SELECT rss_kb, n_pools_ativos FROM pr_rss_amostra WHERE ts>=?", (desde,)) if r["n_pools_ativos"] > 0]
    if not por_pool:
        return {"n": 0, "medio_kb": None, "pior_kb": None, "pools_extras_com_folga": None}
    medio = statistics.fmean(por_pool)
    pior = max(por_pool)
    return {"n": len(por_pool), "medio_kb": medio, "pior_kb": pior,
           "pools_extras_com_folga": int(FOLGA_RSS_KB // medio) if medio > 0 else None}


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
            ja_fechados: int, eta: Optional[float], pct_runner: Optional[float], uso_api: dict[str, Any],
            latencia: dict[str, Any], capacidade: dict[str, Any]) -> str:
    out = ["# Funil diario -- POS-RUNNER (descoberta -> admissao -> runner -> caixa -> sinal -> fechado)", "",
          f"tokens distintos fechados (total): {ja_fechados}/{ALVO_TOKENS_FECHADOS}",
          f"ETA at {ALVO_TOKENS_FECHADOS} tokens distintos fechados: " +
          ("s/d (sem fechamento ainda ou taxa 0 -- nunca chegaria no ritmo atual)" if eta is None
           else f"{eta:.1f} dia(s) (projecao linear pela taxa media)"),
          f"% runner (admitidos nos ultimos 7d): " + ("s/d (nenhum admitido na janela)" if pct_runner is None
                                                       else f"{pct_runner:.1f}%"), "",
          "| dia (UTC) | descobertos | admitidos | runner | caixa | sinal | fechado | aposentados | "
          "readmitidos | entradas_atrasadas | eventos_pre_admissao |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for dia, c in funil.items():
        out.append(f"| {dia} | {c['descobertos']} | {c['admitidos']} | {c['runner']} | {c['caixa']} | "
                  f"{c['sinal']} | {c['fechado']} | {c['aposentados']} | {c['readmitidos']} | "
                  f"{fase1_atrasadas.get(dia, 0)} | {fase1_pre_admissao.get(dia, 0)} |")
    if not funil:
        out.append("(sem dados ainda)")
    out += ["", "## Uso de API (24h)", "",
          "chamadas/h por finalidade: " +
          (", ".join(f"{k}={v:.2f}" for k, v in sorted(uso_api["chamadas_h"].items())) or "0 (sem chamada registrada)"),
          f"429/h: {uso_api['rate_limited_h']:.2f}" +
          (" (" + ", ".join(f"{k}={v:.2f}" for k, v in sorted(uso_api["rate_limited_h_por_finalidade"].items())) + ")"
           if uso_api["rate_limited_h_por_finalidade"] else "")]
    out += ["", "## Latencia do candle (24h)", ""]
    if latencia["n"] == 0:
        out.append("s/d (sem candle processado ainda nesta janela)")
    else:
        destaque = " <<< PERTO DO LIMIAR DE _late() (1h)" if latencia["p95"] >= LATE_PROXIMO_FRACAO * LATE_LIMIAR_S else ""
        out.append(f"n={latencia['n']} | p50={latencia['p50']:.0f}s | p95={latencia['p95']:.0f}s{destaque} | "
                  f"max={latencia['max']:.0f}s | perto do limiar (>={LATE_PROXIMO_FRACAO*100:.0f}% de "
                  f"{LATE_LIMIAR_S:.0f}s): {latencia['n_perto_do_limiar']}")
    out += ["", "## Capacidade (RSS)", ""]
    if capacidade["n"] == 0:
        out.append("s/d (sem amostra ainda nesta janela)")
    else:
        out.append(f"RSS/pool (24h, n={capacidade['n']} amostras): medio={capacidade['medio_kb']/1024.0:.1f}MB | "
                  f"pior={capacidade['pior_kb']/1024.0:.1f}MB | pools extras com {FOLGA_RSS_KB//1024}MB de folga: "
                  f"{capacidade['pools_extras_com_folga']} (aproximacao -- ver docstring do modulo; NUNCA sugere "
                  f"mudar max_pools)")
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
        pct_runner = pct_runner_7d(con, now)
        uso_api = uso_api_24h(con, now)
        latencia = latencia_candle_24h(con, now)
        capacidade = capacidade_rss_24h(con, now)
        return formatar(funil, atrasadas, pre_admissao, ja_fechados, eta, pct_runner, uso_api, latencia, capacidade)
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
