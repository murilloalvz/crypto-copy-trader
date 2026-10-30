"""PEDIDO 2026-10-30: diagnostico de vagas/rotacao do POS-RUNNER (ver scripts/saude.py, item
"candidatos novos sem vaga (max_pools, 48h)" e `live.py: _retire_estagnado`/`_promote`).

SOMENTE LEITURA, zero chamada de rede: abre o SQLite em `file:...?mode=ro` (mesmo padrao de
`scripts/sensibilidade_parametros.py` -- nunca passa por `Storage`, que roda migracao no
`__init__`). NUNCA toca `ParamsV1`/`ParamsV2`/`pos_runner_v1.yaml`/`pos_runner_v2.yaml` -- so le
`pr_bars` ja em cache e reproduz (replay) o MESMO `DetectorV1` em memoria pra reconstruir a fase
historica, exatamente como `live.py: _fase_label_v1`/`_fase_label_v2` fariam ao vivo.

A) pools ATIVOS hoje: token, idade (d, desde a criacao do token), horas em sem_fase (desde o
   ultimo candle em que V1 OU V2 esteve em runner/pullback -- mesma definicao de "elegivel" de
   `live.py: _carteiras_elegivel`; 0 se algum dos dois esta ativo AGORA), fase V1/V2 (label atual),
   queda desde o pico em % (maior entre V1 e V2, mesmo calculo de `live.py: _retire_estagnado`,
   `DetectorV1.drop_pct()`), MC atual (ultimo candle).

B) candidatos sem vaga (pr_vaga_descartes, janela de 48h, POOL DISTINTO -- mesma tabela/contagem
   do item 5b/saude.py): quantos passam HOJE nos filtros base (idade>=2d, MC>=100k, queda entre
   80% e 96% -- a faixa MAIS LARGA, de V2, que ja cobre a faixa mais estreita de V1 [80-90%]; um
   candidato que falha a faixa de V2 falharia tambem a de V1) vs. nao passam, e o motivo mais
   comum de reprovacao entre os que falham (1a condicao que falha, nesta ordem: sem_dados ->
   idade_baixa -> mc_baixo -> queda_fora_da_faixa). "Queda desde o pico" aqui e um proxy SEM
   detector (100*(1 - ultimo_close/maior_high_ja_visto)) -- mais simples que o replay causal de A,
   adequado pra um candidato que pode nunca ter ganho um detector de verdade (`status` != 'ativo').

C) dos pools ativos de A, quantos tem horas em sem_fase > 24h, > 48h, > 72h (buckets encaixados).

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.diagnostico_vagas --db signals_mvp/dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ..pos_runner.detector_v1 import PHASE_PULLBACK, PHASE_RUNNER, DetectorV1
from ..pos_runner.params_v1 import ParamsV1, load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from .sensibilidade_parametros import _bars_do_pool, _conectar_ro, _created_ts

FASE_LABEL = {PHASE_RUNNER: "runner", PHASE_PULLBACK: "pullback"}
QUEDA_MIN_PCT = 80.0
QUEDA_MAX_PCT = 96.0   # faixa larga (V2); V1 (80-90%) e um subconjunto desta.
MC_MIN_USD = 100_000.0
IDADE_MIN_DIAS = 2.0


def _fase_label(fase: int) -> str:
    return FASE_LABEL.get(fase, "sem_fase")


def _replay_historico(bars: list, params: ParamsV1, l_bc: Optional[float], grad_ts: Optional[float],
                      created_ts: Optional[float]) -> tuple[DetectorV1, list[tuple[float, int]]]:
    """Reproduz o MESMO `DetectorV1` candle a candle (causal, zero lookahead) -- devolve o detector
    no estado final e a timeline (ts, fase) de cada candle, pra reconstruir desde quando a fase
    ficou no estado atual."""
    det = DetectorV1(params, params.timeframes[0], l_bc, grad_ts, created_ts)
    timeline: list[tuple[float, int]] = []
    for bar in bars:
        det.update(bar)
        timeline.append((bar.ts, det.phase))
    return det, timeline


def _horas_sem_fase_combinada(tl_v1: list[tuple[float, int]], tl_v2: list[tuple[float, int]], now: float) -> float:
    """0.0 se V1 OU V2 esta em runner/pullback AGORA (ultimo candle); senao, horas desde o ultimo
    candle em que algum dos dois esteve ativo (nunca esteve ativo = desde o 1o candle em cache --
    subestima se houver historico mais antigo fora do cache, mesma ressalva de
    `sensibilidade_parametros.py`)."""
    n = max(len(tl_v1), len(tl_v2))
    if n == 0:
        return 0.0
    ultimo_ativo_ts: Optional[float] = None
    for i in range(n):
        ativo_v1 = i < len(tl_v1) and tl_v1[i][1] in (PHASE_RUNNER, PHASE_PULLBACK)
        ativo_v2 = i < len(tl_v2) and tl_v2[i][1] in (PHASE_RUNNER, PHASE_PULLBACK)
        if ativo_v1 or ativo_v2:
            ts = tl_v1[i][0] if i < len(tl_v1) else tl_v2[i][0]
            ultimo_ativo_ts = ts
    if ultimo_ativo_ts is None:
        ts_inicio = tl_v1[0][0] if tl_v1 else tl_v2[0][0]
        return max(0.0, (now - ts_inicio) / 3600.0)
    if ultimo_ativo_ts == (tl_v1[-1][0] if tl_v1 else tl_v2[-1][0]):
        return 0.0   # ativo agora mesmo (ultimo candle)
    return max(0.0, (now - ultimo_ativo_ts) / 3600.0)


def _pools_ativos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT pool, symbol, l_bc, grad_ts, info FROM pr_pools WHERE status='ativo'"
    ).fetchall()


def _pool_por_nome(con: sqlite3.Connection, pool: str) -> Optional[sqlite3.Row]:
    return con.execute("SELECT pool, symbol, l_bc, grad_ts, info FROM pr_pools WHERE pool=?", (pool,)).fetchone()


def _candidatos_sem_vaga_48h(con: sqlite3.Connection, now: float) -> list[str]:
    """POOL DISTINTO em `pr_vaga_descartes` nas ultimas 48h -- mesma tabela/janela do item 5b
    (`saude.py`: "candidatos novos sem vaga (max_pools, 48h)")."""
    rows = con.execute("SELECT DISTINCT pool FROM pr_vaga_descartes WHERE ts>=?", (now - 48 * 3600.0,)).fetchall()
    return [r["pool"] for r in rows]


def secao_a(con: sqlite3.Connection, params_v1: ParamsV1, params_v2: ParamsV1, now: float) -> list[dict[str, Any]]:
    linhas = []
    for row in _pools_ativos(con):
        pool = row["pool"]
        bars = _bars_do_pool(con, pool, params_v1.timeframes[0])
        created_ts = _created_ts(row["info"])
        idade_d = None if created_ts is None else (now - created_ts) / 86400.0
        if not bars:
            linhas.append({"pool": pool, "symbol": row["symbol"] or pool, "idade_d": idade_d,
                           "horas_sem_fase": None, "fase_v1": "sem_fase", "fase_v2": "sem_fase",
                           "queda_pct": None, "mc_atual": None})
            continue
        det_v1, tl_v1 = _replay_historico(bars, params_v1, row["l_bc"], row["grad_ts"], created_ts)
        det_v2, tl_v2 = _replay_historico(bars, params_v2, row["l_bc"], row["grad_ts"], created_ts)
        horas_sem_fase = _horas_sem_fase_combinada(tl_v1, tl_v2, now)
        quedas = [d for d in (det_v1.drop_pct(), det_v2.drop_pct()) if d is not None]
        linhas.append({
            "pool": pool, "symbol": row["symbol"] or pool, "idade_d": idade_d,
            "horas_sem_fase": horas_sem_fase, "fase_v1": _fase_label(det_v1.phase),
            "fase_v2": _fase_label(det_v2.phase), "queda_pct": max(quedas) if quedas else None,
            "mc_atual": bars[-1].close,
        })
    return linhas


def _motivo_reprovacao(idade_d: Optional[float], mc_atual: Optional[float],
                       queda_pct: Optional[float]) -> Optional[str]:
    """1a condicao que falha, nesta ordem -- devolve None se passa em todas."""
    if idade_d is None or mc_atual is None or queda_pct is None:
        return "sem_dados"
    if idade_d < IDADE_MIN_DIAS:
        return "idade_baixa"
    if mc_atual < MC_MIN_USD:
        return "mc_baixo"
    if not (QUEDA_MIN_PCT <= queda_pct <= QUEDA_MAX_PCT):
        return "queda_fora_da_faixa"
    return None


def secao_b(con: sqlite3.Connection, now: float) -> dict[str, Any]:
    pools = _candidatos_sem_vaga_48h(con, now)
    passam, reprovados = 0, 0
    motivos: Counter = Counter()
    for pool in pools:
        row = _pool_por_nome(con, pool)
        bars = _bars_do_pool(con, pool, "1h") if row else []
        created_ts = _created_ts(row["info"]) if row else None
        idade_d = None if created_ts is None else (now - created_ts) / 86400.0
        if bars:
            pico = max(b.high for b in bars)
            mc_atual = bars[-1].close
            queda_pct = 100.0 * (1.0 - mc_atual / pico) if pico else None
        else:
            mc_atual = queda_pct = None
        motivo = _motivo_reprovacao(idade_d, mc_atual, queda_pct)
        if motivo is None:
            passam += 1
        else:
            reprovados += 1
            motivos[motivo] += 1
    motivo_comum = motivos.most_common(1)[0] if motivos else None
    return {"n_candidatos": len(pools), "passam": passam, "reprovados": reprovados,
           "motivo_mais_comum": motivo_comum}


def secao_c(linhas_a: list[dict[str, Any]]) -> dict[str, int]:
    horas = [l["horas_sem_fase"] for l in linhas_a if l["horas_sem_fase"] is not None]
    return {">24h": sum(1 for h in horas if h > 24.0), ">48h": sum(1 for h in horas if h > 48.0),
           ">72h": sum(1 for h in horas if h > 72.0)}


def formatar(linhas_a: list[dict[str, Any]], b: dict[str, Any], c: dict[str, int]) -> str:
    out = ["# Diagnostico de vagas/rotacao -- POS-RUNNER", "",
          "## A) pools ativos hoje", "",
          "| token | idade (d) | horas em sem_fase | fase V1 | fase V2 | queda do pico (%) | MC atual |",
          "|---|---|---|---|---|---|---|"]
    for l in sorted(linhas_a, key=lambda x: x["horas_sem_fase"] or 0.0, reverse=True):
        idade = "s/d" if l["idade_d"] is None else f"{l['idade_d']:.1f}"
        horas = "s/d" if l["horas_sem_fase"] is None else f"{l['horas_sem_fase']:.1f}"
        queda = "s/d" if l["queda_pct"] is None else f"{l['queda_pct']:.1f}"
        mc = "s/d" if l["mc_atual"] is None else f"{l['mc_atual']:,.0f}"
        out.append(f"| {l['symbol']} | {idade} | {horas} | {l['fase_v1']} | {l['fase_v2']} | {queda} | {mc} |")
    out += ["", "## B) candidatos sem vaga nas ultimas 48h (pr_vaga_descartes, pool distinto)", "",
          f"candidatos: {b['n_candidatos']} | passam hoje nos filtros base (idade>=2d, MC>=100k, "
          f"queda 80-96%): {b['passam']} | nao passam: {b['reprovados']}"]
    if b["motivo_mais_comum"] is not None:
        motivo, n = b["motivo_mais_comum"]
        out.append(f"motivo mais comum de reprovacao: {motivo} ({n} de {b['reprovados']})")
    out += ["", "## C) pools ativos sem_fase (combinado V1/V2) ha mais de...", "",
          f">24h: {c['>24h']} | >48h: {c['>48h']} | >72h: {c['>72h']}"]
    return "\n".join(out)


def executar(db_path: Path) -> str:
    con = _conectar_ro(db_path)
    try:
        now = time.time()
        linhas_a = secao_a(con, load_params_v1(), load_params_v2(), now)
        b = secao_b(con, now)
        c = secao_c(linhas_a)
        return formatar(linhas_a, b, c)
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostico de vagas/rotacao do POS-RUNNER (PAPER / so leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
