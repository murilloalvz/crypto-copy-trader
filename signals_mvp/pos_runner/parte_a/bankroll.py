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

`BankrollLedger` e o estado por ajuste (um por tf x variante): reutilizado pela Parte A (loteado, `simulate_bankroll`
varre todo o periodo de uma vez) e pela Parte B ao vivo (um passo por sinal fechado, estado persistido entre
reinicios -- ver `BankrollState.to_json`/`from_json`).
"""

from __future__ import annotations

import csv
import dataclasses
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ...util import iso_utc
from ..candles import Bar
from ..costs import CostModel
from ..detector import Event
from ..params import Params
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


@dataclass
class BankrollState:
    """Estado completo de UM ajuste (tf x variante); serializavel para persistir entre reinicios (Parte B)."""

    banca: float
    peak_banca: float
    banca_inicio_dia: float
    banca_inicio_semana: float
    open_positions: list[tuple[float, float]] = field(default_factory=list)
    dia_atual: Optional[str] = None
    perdas_seguidas: int = 0
    dia_pausado: bool = False
    semana_atual: Optional[str] = None
    semana_pausada: bool = False
    maior_queda_usd: float = 0.0
    maior_queda_pct: float = 0.0
    n_trades: int = 0
    n_lucro: int = 0
    soma_liq_pct: float = 0.0

    @classmethod
    def novo(cls, banca_inicial: float) -> "BankrollState":
        return cls(banca=banca_inicial, peak_banca=banca_inicial, banca_inicio_dia=banca_inicial, banca_inicio_semana=banca_inicial)

    def resumo(self) -> dict[str, Any]:
        n = self.n_trades
        return {
            "n_trades": n,
            "pct_com_lucro": (100.0 * self.n_lucro / n) if n else None,
            "lucro_liq_medio_pct": (self.soma_liq_pct / n) if n else None,
            "banca_final_usd": self.banca,
            "maior_queda_usd": self.maior_queda_usd,
            "maior_queda_pct": self.maior_queda_pct,
        }

    def to_json(self) -> str:
        d = dataclasses.asdict(self)
        d["open_positions"] = [list(p) for p in self.open_positions]
        return json.dumps(d)

    @classmethod
    def from_json(cls, text: str) -> "BankrollState":
        d = json.loads(text)
        d["open_positions"] = [tuple(p) for p in d.get("open_positions", [])]
        return cls(**d)


class BankrollLedger:
    """Um ajuste (tf x variante): `step` avanca com UMA entrada primaria ja sabida FECHADA pelo custo oficial
    (0,15 SOL), devolve a linha da tabela (sempre, inclusive "pulado") e muda o estado. `base_costs` e so o molde
    (terminal_pct/network_sol/multiplier); o `position_sol` de cada chamada vem da banca atual."""

    def __init__(self, detector_params: Params, base_costs: CostModel, params: BankrollParams = BankrollParams(),
                state: Optional[BankrollState] = None):
        self.detector_params = detector_params
        self.base_costs = base_costs
        self.params = params
        self.state = state or BankrollState.novo(params.banca_inicial_usd)

    def step(self, bars: list[Bar], ev: Event, variant: str, dex: str, l_bc: Optional[float],
             sol_at: Any, meta: dict[str, Any]) -> Optional[dict[str, Any]]:
        s = self.state
        j0 = ev.idx + 1
        if j0 >= len(bars):
            return None   # sem o candle de entrada ainda: o chamador so deve chamar apos o trade oficial fechar
        entry_ts = bars[j0].ts
        dia = _dia_utc(entry_ts)
        if dia != s.dia_atual:
            s.dia_atual, s.banca_inicio_dia, s.perdas_seguidas, s.dia_pausado = dia, s.banca, 0, False
        semana = _semana_utc(entry_ts)
        if semana != s.semana_atual:
            s.semana_atual, s.banca_inicio_semana, s.semana_pausada = semana, s.banca, False
        s.open_positions = [p for p in s.open_positions if p[1] > entry_ts]

        linha: dict[str, Any] = {**meta, "data_entrada": iso_utc(entry_ts), "mc_entrada": None, "mc_saida": None,
                                 "tempo_no_trade_h": None, "lucro_bruto_pct": None, "taxas_pct": None,
                                 "lucro_liquido_pct": None, "tamanho_posicao_usd": None, "resultado_usd": None,
                                 "banca_depois_usd": None}
        if s.semana_pausada:
            return {**linha, "motivo_saida": "pulado: stop semanal"}
        if s.dia_pausado:
            return {**linha, "motivo_saida": "pulado: stop diário"}
        if len(s.open_positions) >= self.params.max_posicoes_abertas:
            return {**linha, "motivo_saida": "pulado: limite"}
        sol_usd_entry = sol_at(entry_ts)
        if not sol_usd_entry:
            return {**linha, "motivo_saida": "sem dado: sol/usd"}

        position_usd = s.banca * self.params.posicao_frac
        position_sol = position_usd / sol_usd_entry
        cost_model = dataclasses.replace(self.base_costs, position_sol=position_sol)
        res = simulate(bars, ev, variant, self.detector_params, cost_model, dex, l_bc, sol_at)
        if res.status != "fechado" or not res.legs:
            return {**linha, "motivo_saida": f"sem dado: {res.status}"}

        resultado_usd = position_usd * (res.net_ret or 0.0)
        banca_depois = s.banca + resultado_usd
        linha.update(mc_entrada=res.entry_price, mc_saida=res.legs[-1].price,
                     motivo_saida=_MOTIVO.get(res.reason, res.reason or "sem dado"),
                     tempo_no_trade_h=(res.bars_held or 0) * TF_HOURS[meta["tf"]],
                     lucro_bruto_pct=(res.gross_ret or 0.0) * 100.0,
                     taxas_pct=((res.gross_ret or 0.0) - (res.net_ret or 0.0)) * 100.0,
                     lucro_liquido_pct=(res.net_ret or 0.0) * 100.0,
                     tamanho_posicao_usd=position_usd, resultado_usd=resultado_usd, banca_depois_usd=banca_depois)
        s.open_positions.append((entry_ts, res.legs[-1].ts))
        s.banca = banca_depois
        s.n_trades += 1
        if resultado_usd > 0:
            s.n_lucro += 1
            s.perdas_seguidas = 0
        else:
            s.perdas_seguidas += 1
        s.soma_liq_pct += linha["lucro_liquido_pct"]
        s.peak_banca = max(s.peak_banca, s.banca)
        queda_usd = s.peak_banca - s.banca
        if queda_usd > s.maior_queda_usd:
            s.maior_queda_usd = queda_usd
            s.maior_queda_pct = 100.0 * queda_usd / s.peak_banca if s.peak_banca else 0.0
        if s.banca - s.banca_inicio_dia <= -self.params.stop_diario_frac * s.banca_inicio_dia or s.perdas_seguidas >= self.params.stop_diario_perdas_seguidas:
            s.dia_pausado = True
        if s.banca - s.banca_inicio_semana <= -self.params.stop_semanal_frac * s.banca_inicio_semana:
            s.semana_pausada = True
        return linha


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
