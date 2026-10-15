"""Passo 0 do POS-RUNNER-V0 — calibracao com os 5 exemplos do professor (NAO e avaliacao).

    python -m signals_mvp.pos_runner.passo0 --cache <pasta de cache OHLCV> --out <pasta do relatorio>

Baixa (com cache/retomada) as series dos 5 pools de graduacao nos 3 timeframes, roda o detector com os
parametros do handoff e com a proposta de calibracao, mede o que a secao 2.5 pede, simula as saidas A/B e gera
os graficos. A varredura de parametros (`SWEEP`) e pequena e fica registrada no relatorio: so serve para achar o
minimo que reconhece os exemplos; os 5 exemplos ficam FORA de todas as metricas de resultado.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..http import HttpClient, RateLimiter
from ..util import iso_utc, utc_now
from . import charts
from .candles import Bar, OhlcvStore, tf_seconds
from .costs import CostModel
from .detector import Detector, Event, run
from .examples import EXAMPLES, QUOTE_REFERENCES, Example
from .params import Params, load_params
from .quotes import SOL_MINT
from .series import PoolSeries, build_series, quote_usd
from .simulate import TradeResult, simulate

TFS = ("5m", "1h", "4h")
GT_BASE = "https://api.geckoterminal.com/api/v2"


def make_store(cache: Path, per_min: float = 20.0) -> OhlcvStore:
    http = HttpClient(GT_BASE, RateLimiter(per_min, 2, pause_s=30, pause_max_s=240), 30, name="GeckoTerminal")
    return OhlcvStore(http, cache)


@dataclass
class ExampleData:
    ex: Example
    series: PoolSeries
    sol_usd: Any                      # UsdSeries da SOL (custos do PumpSwap e rede)
    end_ts: int


def load_example(store: OhlcvStore, ex: Example, end_ts: int, cross_check: bool = True) -> ExampleData:
    usd = quote_usd(store, ex.quote_mint, QUOTE_REFERENCES, ex.grad_ts, end_ts)
    if usd is None:
        raise RuntimeError(f"{ex.key}: sem serie de referencia USD para a cotacao {ex.quote_symbol}")
    sol = usd if ex.quote_mint == SOL_MINT else quote_usd(store, SOL_MINT, QUOTE_REFERENCES, ex.grad_ts, end_ts)
    series = build_series(store, ex.pool, ex.grad_ts, end_ts, ex.supply, usd, TFS, cross_check=cross_check)
    return ExampleData(ex, series, sol, end_ts)


# ---------------------------------------------------------------------------
# medidas da secao 2.5
# ---------------------------------------------------------------------------


@dataclass
class Measures:
    tf: str
    event: Event
    trades: dict[str, TradeResult] = field(default_factory=dict)
    row: dict[str, Any] = field(default_factory=dict)


def measure_entry(data: ExampleData, det: Detector, event: Event, params: Params, costs: CostModel) -> Measures:
    bars = det.bars
    tf = det.tf
    step = tf_seconds(tf)
    d = event.data
    i = event.idx
    ex = data.ex
    m = Measures(tf, event)
    for variant in ("A", "B"):
        m.trades[variant] = simulate(bars, event, variant, params, costs, ex.dex, data.series.l_bc, data.sol_usd.at)
    wick_ratios = []
    for w in d["wicks"]:
        b = bars[w]
        body = abs(b.close - b.open)
        lower = min(b.open, b.close) - b.low
        wick_ratios.append(lower / body if body > 0 else 99.0)
    entry_px = bars[i + 1].open if i + 1 < len(bars) else None
    horizon = bars[i + 1:i + 1 + params.time_stop_candles]
    after_max = max((b.high for b in horizon), default=None)
    reached = next((k for k, b in enumerate(bars[i + 1:], start=1) if b.high >= d["tp"]), None)
    m.row = {
        "tf": tf,
        "rompimento": iso_utc(event.ts),
        "idade_d": round(d["idade_dias"], 2) if d["idade_dias"] is not None else None,
        "na_janela": d["na_janela"],
        "P_peak": d["P_peak"],
        "pico_em_h_desde_graduacao": round((bars[d["peak_idx"]].ts + step - ex.grad_ts) / 3600.0, 1),
        "L_bc": data.series.l_bc,
        "queda_pct": round(d["queda_pct"], 1) if d["queda_pct"] is not None else None,
        "caixa_candles": d["box_len"],
        "S": d["S"],
        "R": d["R"],
        "R_S": round(d["R_S"], 2),
        "n_wicks": d["n_wicks"],
        "pavio_sobre_corpo_mediana": round(statistics.median(wick_ratios), 1) if wick_ratios else None,
        "vol_rompimento_x_media": round(d["vol_ratio"], 1),
        "amplitude_rompimento_atr": round(d["amp_atr"], 1) if d["amp_atr"] else None,
        "power_candle": d["power_candle"],
        "cobertura_R_ate_pico": round(d["cobertura"], 2),
        "entrada": entry_px,
        "stop": d["stop"],
        "alvo": d["tp"],
        "subida_max_48c_pct": round(100.0 * (after_max / entry_px - 1.0), 1) if after_max and entry_px else None,
        "chegou_no_alvo": reached is not None,
        "candles_ate_alvo": reached,
        "saida_A": _trade_text(m.trades["A"]),
        "saida_B": _trade_text(m.trades["B"]),
    }
    return m


def _trade_text(t: TradeResult) -> str:
    if t.status != "fechado":
        return t.status + (f" ({t.reason})" if t.reason else "")
    return f"{100 * t.net_ret:+.1f}% liq ({t.reason}, {t.bars_held} candles)"


# ---------------------------------------------------------------------------
# varredura de calibracao
# ---------------------------------------------------------------------------

SWEEP: dict[str, list[Any]] = {
    "measure": ["wick", "body"],
    "drop_max": [0.90, 0.93, 0.95, 0.97],
    "box_max_ratio": [3.0, 4.0],
    "wick_zone": [0.05, 0.10],
    "box_min_candles": [12, 8],
}


def sweep_variants(base: Params) -> list[Params]:
    keys = list(SWEEP)
    out = []
    for combo in itertools.product(*(SWEEP[k] for k in keys)):
        out.append(dataclasses.replace(base, **dict(zip(keys, combo))))
    return out


def entries_by_tf(data: ExampleData, params: Params) -> dict[str, list[Event]]:
    res = {}
    for tf in TFS:
        det = run(data.series.bars[tf], params, tf, data.series.l_bc, data.ex.grad_ts)
        res[tf] = [e for e in det.events if e.kind in ("ENTRADA", "ABSURDO")]
    return res


def run_sweep(datas: list[ExampleData], base: Params, labels: dict[str, list[tuple[str, int, int]]]) -> list[dict[str, Any]]:
    """Para cada variante: quais exemplos tem ENTRADA dentro da janela rotulada (leitura visual a confirmar)."""
    rows = []
    for p in sweep_variants(base):
        hits = {}
        for data in datas:
            found = entries_by_tf(data, p)
            ok = False
            for tf, lo, hi in labels.get(data.ex.key, []):
                if any(e.kind == "ENTRADA" and lo <= e.ts <= hi for e in found[tf]):
                    ok = True
            hits[data.ex.key] = ok
        rows.append({"params": {k: getattr(p, k) for k in SWEEP}, "versao": p.version, "reconhece": hits,
                     "n": sum(hits.values())})
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Passo 0 do POS-RUNNER-V0 (calibracao com os 5 exemplos)")
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fim", default=None, help="fim da janela (ISO UTC); padrao = agora")
    args = ap.parse_args(argv)
    from ..util import parse_iso
    end = int(parse_iso(args.fim) if args.fim else utc_now())
    store = make_store(args.cache)
    datas = [load_example(store, ex, end) for ex in EXAMPLES]
    params = load_params()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for data in datas:
        summary[data.ex.key] = {
            "L_bc": data.series.l_bc,
            "candles": {tf: len(b) for tf, b in data.series.bars.items()},
            "sem_usd": data.series.missing_usd,
            "divergencia_usd_gt": {tf: len(v) for tf, v in data.series.usd_mismatch.items()},
        }
    (args.out / "passo0_dados.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    _ = params
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
