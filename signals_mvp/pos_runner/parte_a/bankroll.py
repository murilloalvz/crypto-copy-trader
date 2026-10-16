"""Parte A do addendum de relatorio (2026-10-16): tabela de trades + gestao de banca por ajuste da grade (tf x
saida), loteada sobre todo um periodo (discovery/holdout). A gestao de banca em si (`BankrollLedger`/
`BankrollState`) vive em `..bankroll` (sem dependencia de `Context`/`Store`) e e compartilhada com a Parte B ao
vivo (`live.py`), que chama o MESMO ledger um sinal por vez, com o estado persistido entre reinicios.

NAO muda nenhuma regra do detector/simulador nem a escolha da variante (isso continua vindo so de
`metrics.variant_table`/`choose_variant`, no custo FIXO de 0,15 SOL do handoff). So trades FECHADOS entram nesta
tabela e na contagem de posicoes abertas; cancelado/em_aberto ficam fora (limitacao documentada no pre-registro,
nao afeta a metrica oficial).
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Optional

from ..bankroll import COLUMNS, HEADER_LABELS, BankrollLedger, BankrollParams
from ..detector import Event
from ..quotes import SOL_MINT
from .pipeline import DEX_OF_LAUNCHPAD, Context, load_bars

log = logging.getLogger("signals_mvp.pos_runner.parte_a.bankroll")

AJUSTES: tuple[tuple[str, str], ...] = tuple((tf, v) for tf in ("5m", "1h", "4h") for v in ("A", "B"))


def _fetch_token_name(ctx: Context, pool: str) -> Optional[str]:
    """Nome/simbolo do token via GeckoTerminal (so para exibicao na tabela; nunca filtro, nunca trava o relatorio)."""
    try:
        data = ctx.ohlcv.http.get_json(f"networks/{ctx.ohlcv.network}/pools/{pool}", {"include": "base_token"})
    except Exception:
        return None
    try:
        base_id = data["data"]["relationships"]["base_token"]["data"]["id"]
        for inc in data.get("included") or []:
            if inc.get("id") == base_id:
                sym = (inc.get("attributes") or {}).get("symbol")
                if sym:
                    return str(sym)
        name = ((data.get("data") or {}).get("attributes") or {}).get("name")
        return name.split(" / ")[0].strip() if name else None
    except Exception:
        return None


def _token_name(ctx: Context, pool: str) -> Optional[str]:
    if pool not in ctx._token_names:
        ctx._token_names[pool] = _fetch_token_name(ctx, pool)
    return ctx._token_names[pool]


def simulate_bankroll(ctx: Context, period: str, tf: str, variant: str,
                      params: BankrollParams = BankrollParams()) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Uma linha por entrada primaria FECHADA (ou "pulada") do ajuste `tf`/`variant`, em ordem cronologica real."""
    prim_rows = [r for r in ctx.store.setups(period, tf, primary_only=True)]
    closed = {(r[0], r[1], r[2]) for r in ctx.store.trades(period, "setup") if r[3] == variant and r[4] == "fechado"}
    grads = {g["pool"]: g for g in ctx.store.graduations(period)}
    sol_series = ctx.usd(SOL_MINT, period)
    sol_at = sol_series.at if sol_series else (lambda t: None)
    bars_cache: dict[str, list] = {}
    ledger = BankrollLedger(ctx.params, ctx.costs, params)

    rows: list[dict[str, Any]] = []
    for r in sorted((r for r in prim_rows if (r[0], r[1], r[2]) in closed), key=lambda r: r[4]):
        pool = r[0]
        g = grads.get(pool)
        if g is None:
            continue
        bars = bars_cache.setdefault(pool, load_bars(ctx, g, tf))
        if not bars:
            continue
        d = json.loads(r[5])
        ev = Event(kind=d["kind"], idx=d["idx"], ts=d["ts"], decision_ts=d["decision_ts"], data=d["data"])
        st1 = ctx.store.stage1(pool)
        l_bc = st1[3] if st1 else None
        dex = DEX_OF_LAUNCHPAD.get(g["launchpad"], "desconhecido")
        meta = {"token": _token_name(ctx, pool), "contrato": g["mint"], "launchpad": g["launchpad"], "tf": tf, "saida": variant}
        linha = ledger.step(bars, ev, variant, dex, l_bc, sol_at, meta)
        if linha is not None:
            rows.append(linha)
    return rows, ledger.state.resumo()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([HEADER_LABELS.get(c, c) for c in COLUMNS])
        for row in rows:
            w.writerow(["" if row.get(c) is None else row.get(c) for c in COLUMNS])


def xlsx_available() -> bool:
    try:
        import openpyxl  # noqa: F401
    except Exception:
        return False
    return True


def _write_sheet(wb: Any, name: str, rows: list[dict[str, Any]]) -> None:
    ws = wb.create_sheet(title=name[:31])
    ws.append([HEADER_LABELS.get(c, c) for c in COLUMNS])
    for row in rows:
        ws.append([row.get(c) for c in COLUMNS])


def write_bankroll_reports(ctx: Context, docs: Path, periods: tuple[str, ...] = ("discovery", "holdout")) -> dict[str, Any]:
    """CSV por ajuste x periodo (sempre) + um XLSX com todas as abas (se `openpyxl` estiver instalado)."""
    docs = Path(docs)
    out_dir = docs / "trades"
    resultado: dict[str, Any] = {"arquivos_csv": [], "resumo": {}}
    wb = None
    if xlsx_available():
        import openpyxl
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
    for period in periods:
        if not ctx.store.graduations(period):
            continue       # periodo ainda nao rodou: nenhuma tabela (nunca uma tabela vazia enganosa)
        for tf, variant in AJUSTES:
            rows, resumo = simulate_bankroll(ctx, period, tf, variant)
            name = f"{period}_{tf}_{variant}"
            path = out_dir / f"{name}.csv"
            _write_csv(path, rows)
            resultado["arquivos_csv"].append(str(path))
            resultado["resumo"][f"{period}/{tf}/{variant}"] = resumo
            if wb is not None:
                _write_sheet(wb, name, rows)
    if wb is not None:
        ws = wb.create_sheet(title="resumo", index=0)
        ws.append(["ajuste", "n_trades", "%_com_lucro", "lucro_liq_medio_%", "banca_final_usd", "maior_queda_usd", "maior_queda_%"])
        for k, s in resultado["resumo"].items():
            ws.append([k, s["n_trades"], s["pct_com_lucro"], s["lucro_liq_medio_pct"], s["banca_final_usd"], s["maior_queda_usd"], s["maior_queda_pct"]])
        xlsx_path = docs / "trades_parte_a.xlsx"
        wb.save(xlsx_path)
        resultado["arquivo_xlsx"] = str(xlsx_path)
    else:
        resultado["arquivo_xlsx"] = None
        log.warning("openpyxl indisponivel: so o CSV foi gerado (pip install openpyxl para o XLSX)")
    return resultado
