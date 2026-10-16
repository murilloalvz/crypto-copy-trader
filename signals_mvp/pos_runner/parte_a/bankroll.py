"""Addendum de RELATORIO (pre-registrado em 2026-10-16, decisao do operador): tabela de trades + gestao de banca
por ajuste da grade (tf x saida), em ordem cronologica real. NAO muda nenhuma regra do detector/simulador nem a
escolha da variante (isso continua vindo so de `metrics.variant_table`/`choose_variant`, no custo FIXO de
0,15 SOL por posicao, calibrado no handoff). Aqui o tamanho da posicao e REAL (5% da banca atual, US$100
iniciais) so para esta tabela ilustrativa; por isso o trade e re-simulado com um `CostModel` do tamanho real
(taxas e slippage mudam com o tamanho) -- mesmo detector, mesmo evento, mesmo caminho de preco, custo
recalculado.

Gestao de banca (separada por ajuste, nunca preco medio):
- banca inicial US$100; posicao = 5% da banca NO MOMENTO da entrada;
- no maximo 3 posicoes abertas ao mesmo tempo (a 4a entrada que o detector daria fica "pulado: limite");
- stop diario: banca cai >= 10% desde o inicio do dia (UTC) OU 3 perdas seguidas -> pausa o resto do dia
  ("pulado: stop diario");
- stop semanal (ISO, UTC): banca cai >= 20% desde o inicio da semana -> pausa o resto da semana
  ("pulado: stop semanal");
- so trades FECHADOS (status "fechado") entram na tabela e na contagem de posicoes abertas; cancelado (abriu
  fora do plano) nunca vira posicao e em_aberto (sem dado ate o fim da janela) fica fora desta tabela
  ilustrativa (limitacao documentada no pre-registro, nao afeta a metrica oficial).
"""

from __future__ import annotations

import csv
import dataclasses
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ...util import iso_utc
from ..detector import Event
from ..quotes import SOL_MINT
from ..simulate import simulate
from .metrics import TF_HOURS
from .pipeline import DEX_OF_LAUNCHPAD, Context, load_bars

log = logging.getLogger("signals_mvp.pos_runner.parte_a.bankroll")

AJUSTES: tuple[tuple[str, str], ...] = tuple((tf, v) for tf in ("5m", "1h", "4h") for v in ("A", "B"))

# motivo de saida do simulador -> rotulo do operador (TP/stop/exaustao/tempo); "trailing"/"stop_na_entrada" sao
# o stop (parcial ja vendido no alvo) do resto da posicao na saida B -- continuam sendo um STOP, nao um 2o TP
_MOTIVO = {"alvo": "TP", "stop": "stop", "stop_na_entrada": "stop", "trailing": "stop", "exaustao": "exaustão", "tempo": "tempo"}

COLUMNS: tuple[str, ...] = (
    "data_entrada", "token", "contrato", "launchpad", "tf", "saida", "mc_entrada", "mc_saida", "motivo_saida",
    "tempo_no_trade_h", "lucro_bruto_pct", "taxas_pct", "lucro_liquido_pct", "tamanho_posicao_usd",
    "resultado_usd", "banca_depois_usd",
)
HEADER_LABELS = {"lucro_bruto_pct": "lucro_bruto_%", "taxas_pct": "taxas_%", "lucro_liquido_pct": "lucro_liquido_%"}


@dataclass(frozen=True)
class BankrollParams:
    banca_inicial_usd: float = 100.0
    posicao_frac: float = 0.05
    max_posicoes_abertas: int = 3
    stop_diario_frac: float = 0.10
    stop_diario_perdas_seguidas: int = 3
    stop_semanal_frac: float = 0.20


def _dia_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _semana_utc(ts: float) -> str:
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


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

    rows: list[dict[str, Any]] = []
    banca = params.banca_inicial_usd
    open_positions: list[tuple[float, float]] = []
    dia_atual: Optional[str] = None
    banca_inicio_dia = banca
    perdas_seguidas = 0
    dia_pausado = False
    semana_atual: Optional[str] = None
    banca_inicio_semana = banca
    semana_pausada = False
    peak_banca = banca
    maior_queda_usd = 0.0
    maior_queda_pct = 0.0
    n_real = 0
    n_lucro = 0
    soma_liq_pct = 0.0

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
        j0 = ev.idx + 1
        if j0 >= len(bars):
            continue
        entry_ts = bars[j0].ts
        dia = _dia_utc(entry_ts)
        if dia != dia_atual:
            dia_atual, banca_inicio_dia, perdas_seguidas, dia_pausado = dia, banca, 0, False
        semana = _semana_utc(entry_ts)
        if semana != semana_atual:
            semana_atual, banca_inicio_semana, semana_pausada = semana, banca, False
        open_positions = [p for p in open_positions if p[1] > entry_ts]

        linha = {"data_entrada": iso_utc(entry_ts), "token": _token_name(ctx, pool), "contrato": g["mint"],
                 "launchpad": g["launchpad"], "tf": tf, "saida": variant, "mc_entrada": None, "mc_saida": None,
                 "tempo_no_trade_h": None, "lucro_bruto_pct": None, "taxas_pct": None, "lucro_liquido_pct": None,
                 "tamanho_posicao_usd": None, "resultado_usd": None, "banca_depois_usd": None}
        if semana_pausada:
            rows.append({**linha, "motivo_saida": "pulado: stop semanal"})
            continue
        if dia_pausado:
            rows.append({**linha, "motivo_saida": "pulado: stop diário"})
            continue
        if len(open_positions) >= params.max_posicoes_abertas:
            rows.append({**linha, "motivo_saida": "pulado: limite"})
            continue
        sol_usd_entry = sol_at(entry_ts)
        if not sol_usd_entry:
            rows.append({**linha, "motivo_saida": "sem dado: sol/usd"})
            continue

        st1 = ctx.store.stage1(pool)
        l_bc = st1[3] if st1 else None
        dex = DEX_OF_LAUNCHPAD.get(g["launchpad"], "desconhecido")
        position_usd = banca * params.posicao_frac
        position_sol = position_usd / sol_usd_entry
        cost_model = dataclasses.replace(ctx.costs, position_sol=position_sol)
        res = simulate(bars, ev, variant, ctx.params, cost_model, dex, l_bc, sol_at)
        if res.status != "fechado" or not res.legs:
            rows.append({**linha, "motivo_saida": f"sem dado: {res.status}"})
            continue

        resultado_usd = position_usd * (res.net_ret or 0.0)
        banca_depois = banca + resultado_usd
        row = {**linha,
               "mc_entrada": res.entry_price, "mc_saida": res.legs[-1].price,
               "motivo_saida": _MOTIVO.get(res.reason, res.reason or "sem dado"),
               "tempo_no_trade_h": (res.bars_held or 0) * TF_HOURS[tf],
               "lucro_bruto_pct": (res.gross_ret or 0.0) * 100.0,
               "taxas_pct": ((res.gross_ret or 0.0) - (res.net_ret or 0.0)) * 100.0,
               "lucro_liquido_pct": (res.net_ret or 0.0) * 100.0,
               "tamanho_posicao_usd": position_usd, "resultado_usd": resultado_usd, "banca_depois_usd": banca_depois}
        rows.append(row)
        open_positions.append((entry_ts, res.legs[-1].ts))
        banca = banca_depois
        n_real += 1
        if resultado_usd > 0:
            n_lucro += 1
            perdas_seguidas = 0
        else:
            perdas_seguidas += 1
        soma_liq_pct += row["lucro_liquido_pct"]
        peak_banca = max(peak_banca, banca)
        queda_usd = peak_banca - banca
        if queda_usd > maior_queda_usd:
            maior_queda_usd = queda_usd
            maior_queda_pct = 100.0 * queda_usd / peak_banca if peak_banca else 0.0
        if banca - banca_inicio_dia <= -params.stop_diario_frac * banca_inicio_dia or perdas_seguidas >= params.stop_diario_perdas_seguidas:
            dia_pausado = True
        if banca - banca_inicio_semana <= -params.stop_semanal_frac * banca_inicio_semana:
            semana_pausada = True

    resumo = {
        "n_trades": n_real,
        "pct_com_lucro": (100.0 * n_lucro / n_real) if n_real else None,
        "lucro_liq_medio_pct": (soma_liq_pct / n_real) if n_real else None,
        "banca_final_usd": banca,
        "maior_queda_usd": maior_queda_usd,
        "maior_queda_pct": maior_queda_pct,
    }
    return rows, resumo


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
