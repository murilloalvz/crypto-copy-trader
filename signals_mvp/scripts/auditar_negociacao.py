"""PEDIDO 2026-11-03 (continuacao -- rotacao/capacidade). SOMENTE LEITURA, zero chamada de rede
(abre o banco em `mode=ro`, mesmo padrao de `sensibilidade_parametros.py`/`diagnostico_vagas.py`).

Contexto: a rotacao hoje (`live.py: _rotacionar_vagas`) aposenta por MC atual < piso OU queda do pico
> 96%, com sem_fase > 24h/72h (conforme idade), NUNCA runner/pullback/posicao aberta -- volume e
holders NAO entram no criterio. Caso relatado: ANT e CHICO ficaram dias em sem_fase com MC>=100k (ou
seja, passariam no criterio de MC, mas continuam sem negociacao real).

Este script SO MEDE (nenhum criterio novo decide nada aqui): para TODO pool 'ativo' ou 'dormente',
volume em USD das ultimas 24h/72h (`pr_bars.v`, ja convertido pra USD em `to_mc_bars` -- soma direta,
nenhum numero novo), numero de candles 1h com volume exatamente 0 nas ultimas 24h, liquidez (reservas)
SE houver (`pr_pools.info.liq_usd` -- snapshot da descoberta, pode faltar: "s/d" explicito, nunca 0),
MC atual (ultimo candle) e horas em sem_fase (`pr_pools.sem_fase_desde`). Destaca ANT/CHICO (pedido
explicito) e os pools 'dormente' (aposentados pela rotacao atual).

NENHUM limiar e escolhido aqui -- so a medicao, pra decidir o criterio DEPOIS com dado real.

Uso (na VM):
    python -m signals_mvp.scripts.auditar_negociacao --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Optional

from .sensibilidade_parametros import _bars_do_pool, _conectar_ro, _created_ts

DESTAQUE_SYMBOLS = ("ANT", "CHICO")


def _info(info_json: Optional[str]) -> dict[str, Any]:
    try:
        data = json.loads(info_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def medir_pool(con, row: Any, now: float) -> dict[str, Any]:
    bars = _bars_do_pool(con, row["pool"], "1h")
    vol_24h = sum(b.volume for b in bars if b.ts >= now - 24 * 3600.0)
    vol_72h = sum(b.volume for b in bars if b.ts >= now - 72 * 3600.0)
    bars_24h = [b for b in bars if b.ts >= now - 24 * 3600.0]
    n_vol_zero_24h = sum(1 for b in bars_24h if b.volume == 0.0)
    info = _info(row["info"])
    liq_usd = info.get("liq_usd")
    mc_atual = bars[-1].close if bars else None
    sem_fase_desde = row["sem_fase_desde"]
    horas_sem_fase = (now - sem_fase_desde) / 3600.0 if sem_fase_desde is not None else None
    created_ts = _created_ts(row["info"])
    idade_dias = (now - created_ts) / 86400.0 if created_ts is not None else None
    return {
        "pool": row["pool"], "symbol": row["symbol"] or row["pool"][:8], "status": row["status"],
        "vol_24h_usd": vol_24h, "vol_72h_usd": vol_72h, "n_candles_24h": len(bars_24h),
        "n_vol_zero_24h": n_vol_zero_24h, "liq_usd": liq_usd, "mc_atual": mc_atual,
        "horas_sem_fase": horas_sem_fase, "idade_dias": idade_dias,
        "destaque": bool(row["symbol"] and row["symbol"].upper() in DESTAQUE_SYMBOLS) or row["status"] == "dormente",
    }


def medir(db_path: Path, now: Optional[float] = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    con = _conectar_ro(db_path)
    try:
        rows = con.execute("SELECT * FROM pr_pools WHERE status IN ('ativo', 'dormente')").fetchall()
        return [medir_pool(con, row, now) for row in rows]
    finally:
        con.close()


def _fmt_usd(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "s/d"


def formatar(linhas: list[dict[str, Any]]) -> str:
    out = ["# auditar_negociacao -- volume/liquidez/MC/sem_fase, ativos e dormentes (SOMENTE LEITURA)", "",
          "Rotacao atual: MC<piso OU queda>96%, sem_fase>24-72h, nunca runner/pullback/posicao -- "
          "volume e holders NAO entram. Nenhum limiar novo escolhido aqui, so medicao.", ""]
    destaque = [l for l in linhas if l["destaque"]]
    if destaque:
        out.append(f"## Destaque (ANT/CHICO/dormentes, {len(destaque)})")
        out.append("")
        out.append("| token | status | vol 24h | vol 72h | candles vol=0 (24h) | liquidez | MC | sem_fase (h) | idade (d) |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for l in destaque:
            out.append(_linha_md(l))
        out.append("")
    out.append(f"## Todos os pools ativos/dormentes ({len(linhas)})")
    out.append("")
    out.append("| token | status | vol 24h | vol 72h | candles vol=0 (24h) | liquidez | MC | sem_fase (h) | idade (d) |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for l in sorted(linhas, key=lambda x: (x["status"], x["symbol"])):
        out.append(_linha_md(l))
    return "\n".join(out)


def _linha_md(l: dict[str, Any]) -> str:
    sem_fase = f"{l['horas_sem_fase']:.0f}" if l["horas_sem_fase"] is not None else "s/d (runner/pullback)"
    idade = f"{l['idade_dias']:.1f}" if l["idade_dias"] is not None else "s/d"
    mc = _fmt_usd(l["mc_atual"])
    liq = _fmt_usd(l["liq_usd"]) if l["liq_usd"] is not None else "s/d"
    return (f"| {l['symbol']} | {l['status']} | {_fmt_usd(l['vol_24h_usd'])} | {_fmt_usd(l['vol_72h_usd'])} | "
           f"{l['n_vol_zero_24h']}/{l['n_candles_24h']} | {liq} | {mc} | {sem_fase} | {idade} |")


def executar(db_path: Path) -> str:
    return formatar(medir(db_path))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="auditar_negociacao: volume/liquidez/MC/sem_fase (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
