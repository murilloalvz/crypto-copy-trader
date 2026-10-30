"""PEDIDO 2026-10-27 (diagnostico McRib/yagi): auditoria SOMENTE LEITURA de todas as ENTRADAs de
pr1_signals/pr2_signals -- candles brutos (o,h,l,c,vol,fonte) de 3 candles antes da entrada at 1
candle depois da saida, conferencia DexPaprika quando houver, e um veredito por candle (LIMPO /
SUSPEITO(motivo), mesma logica de signals_mvp.pos_runner.qualidade_candle.motivo_suspeito -- ver
docs/pos-runner-v1/INTERPRETACOES.md #13). Uma linha de veredito por TRADE no final.

NUNCA escreve no banco: abre o arquivo SQLite em modo read-only (`file:...?mode=ro`), direto por
`sqlite3`, sem passar por `signals_mvp.storage.Storage` (que roda migracao idempotente -- ALTER
TABLE/CREATE TABLE IF NOT EXISTS -- no `__init__`; este script nao quer escrever NADA, nem
migracao, no banco real). Roda contra o banco de producao ou uma copia, a escolha do operador
(`--db`).

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.auditar_trades --db dados/estado.sqlite
    python -m signals_mvp.scripts.auditar_trades --db dados/estado.sqlite --versao v2
    python -m signals_mvp.scripts.auditar_trades --db dados/estado.sqlite --simbolo McRib
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..util import fmt_usd
from ..pos_runner.candles import Bar
from ..pos_runner.qualidade_candle import motivo_suspeito

VERSOES = (("v1", "pr1_signals", "pr1_dexpaprika_divergencias"), ("v2", "pr2_signals", "pr1_dexpaprika_divergencias"))
# pr2 nao tem conferencia cruzada DexPaprika propria (so V1 chama `_conferencia_cruzada_dexpaprika`) --
# reusa a tabela pr1_* (mesmos candles do mesmo pool, a divergencia e do CANDLE, nao da versao).


def _conectar_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _bars_do_pool(con: sqlite3.Connection, pool: str, tf: str) -> list[Bar]:
    rows = con.execute(
        "SELECT ts,o,h,l,c,v,filled FROM pr_bars WHERE pool=? AND tf=? ORDER BY ts", (pool, tf)
    ).fetchall()
    return [Bar(int(r["ts"]), r["o"], r["h"], r["l"], r["c"], r["v"], bool(r["filled"])) for r in rows]


def _idx_do_ts(bars: list[Bar], ts: Optional[float]) -> Optional[int]:
    if ts is None:
        return None
    ts_int = int(ts)
    for i, b in enumerate(bars):
        if b.ts == ts_int:
            return i
    return None


def _divergencias_do_pool(con: sqlite3.Connection, tabela_dex: str, pool: str) -> dict[int, list[sqlite3.Row]]:
    try:
        rows = con.execute(f"SELECT * FROM {tabela_dex} WHERE pool=?", (pool,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        out.setdefault(int(r["candle_ts"]), []).append(r)
    return out


def _linha_candle(i: int, bar: Bar, motivo: Optional[str], divergencias: list[sqlite3.Row]) -> str:
    marca = "LIMPO" if motivo is None else f"SUSPEITO({motivo})"
    linha = (f"  [{i}] ts={bar.ts} o={fmt_usd(bar.open)} h={fmt_usd(bar.high)} l={fmt_usd(bar.low)} "
             f"c={fmt_usd(bar.close)} vol={bar.volume:.0f} filled={int(bar.filled)} -> {marca}")
    for d in divergencias:
        linha += (f"\n      DexPaprika: campo={d['campo']} gt={d['valor_gt']} dexpaprika={d['valor_dexpaprika']} "
                  f"diff_pct={d['diff_pct']:.1f}%")
    return linha


def auditar_trade(con: sqlite3.Connection, versao: str, tabela_dex: str, signal: sqlite3.Row) -> str:
    pool, tf = signal["pool"], signal["tf"]
    bars = _bars_do_pool(con, pool, tf)
    if not bars:
        return f"=== {versao} #{signal['id']} {signal['symbol']} ({pool}) -- SEM CANDLES EM CACHE ===\n"
    divergencias = _divergencias_do_pool(con, tabela_dex, pool)
    idx_entrada = _idx_do_ts(bars, signal["ts_fechamento"])
    idx_saida = _idx_do_ts(bars, signal["exit_full_ts"]) or _idx_do_ts(bars, signal["tp1_ts"])
    ancora_inicio = idx_entrada if idx_entrada is not None else 0
    ancora_fim = idx_saida if idx_saida is not None else (idx_entrada if idx_entrada is not None else len(bars) - 1)
    inicio = max(0, ancora_inicio - 3)
    fim = min(len(bars) - 1, ancora_fim + 1)

    try:
        import json
        ev = json.loads(signal["event_json"] or "{}")
        peak = (ev.get("data") or {}).get("TOPO") or (ev.get("data") or {}).get("P_peak")
    except Exception:  # noqa: BLE001 -- auditoria nunca trava por 1 sinal com event_json malformado
        peak = None

    linhas = [
        f"=== {versao} #{signal['id']} {signal['symbol']} ({pool}) status={signal['status']} "
        f"gatilho_ts={signal['ts_fechamento']} entry_price_alerta={signal['entry_price_alerta']} "
        f"entry_price={signal['entry_price']} stop={signal['stop']} topo={signal['topo']} "
        f"tp1_price={signal['tp1_price']} exit_full_price={signal['exit_full_price']} "
        f"fonte_candle={signal['fonte_candle']} ===",
    ]
    motivos: list[str] = []
    for i in range(inicio, fim + 1):
        bar = bars[i]
        anterior = bars[i - 1].close if i > 0 else None
        seguinte = bars[i + 1].open if i + 1 < len(bars) else None
        dex_divergente = bool(divergencias.get(bar.ts))
        motivo = motivo_suspeito(bar, anterior, peak, seguinte, dex_divergente)
        if motivo is not None:
            motivos.append(f"candle[{i}]:{motivo}")
        linhas.append(_linha_candle(i, bar, motivo, divergencias.get(bar.ts, [])))
    veredito = "LIMPO" if not motivos else "SUSPEITO(" + "; ".join(motivos) + ")"
    linhas.append(f"VEREDITO {versao} #{signal['id']} {signal['symbol']}: {veredito}")
    return "\n".join(linhas) + "\n"


def executar(db_path: Path, versao_filtro: Optional[str], simbolo_filtro: Optional[str]) -> str:
    con = _conectar_ro(db_path)
    try:
        saida: list[str] = []
        for versao, tabela_sinais, tabela_dex in VERSOES:
            if versao_filtro is not None and versao != versao_filtro:
                continue
            where = "evento='ENTRADA'"
            params: list[Any] = []
            if simbolo_filtro is not None:
                where += " AND symbol=?"
                params.append(simbolo_filtro)
            sinais = con.execute(f"SELECT * FROM {tabela_sinais} WHERE {where} ORDER BY id", params).fetchall()
            for signal in sinais:
                saida.append(auditar_trade(con, versao, tabela_dex, signal))
        return "\n".join(saida) if saida else "nenhum trade ENTRADA encontrado com esse filtro.\n"
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auditoria SOMENTE LEITURA dos candles de cada trade ENTRADA/TP1/EXIT (pr1_*/pr2_*)."
    )
    parser.add_argument("--db", required=True, help="caminho do estado.sqlite (produção ou cópia)")
    parser.add_argument("--versao", choices=("v1", "v2"), default=None, help="default: v1 e v2")
    parser.add_argument("--simbolo", default=None, help="filtra por symbol exato (ex.: McRib)")
    args = parser.parse_args(argv)
    print(executar(Path(args.db), args.versao, args.simbolo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
