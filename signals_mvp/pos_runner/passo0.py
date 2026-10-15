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
        "topo_maxima": d.get("P_peak_topo"),
        "topo_em_h_desde_graduacao": round((bars[d["topo_idx"]].ts + step - ex.grad_ts) / 3600.0, 1)
        if d.get("topo_idx") is not None else None,
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



# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------

# leitura VISUAL (minha, a confirmar pelo operador) da janela do rompimento de cada exemplo: so serve para a
# varredura dizer se uma variante "reconhece" o exemplo. Nao entra em nenhuma metrica.
def _ts(iso: str) -> int:
    from ..util import parse_iso
    return int(parse_iso(iso) or 0)


LABELS: dict[str, list[tuple[str, int, int]]] = {
    "BIKE": [("4h", _ts("2026-09-12T00:00:00Z"), _ts("2026-09-13T00:00:00Z"))],
    "ALLINU": [("1h", _ts("2026-09-13T12:00:00Z"), _ts("2026-09-14T00:00:00Z"))],
    "FLAME": [("5m", _ts("2026-09-12T03:00:00Z"), _ts("2026-09-12T16:00:00Z"))],
    "SOLCAT": [("1h", _ts("2026-09-24T00:00:00Z"), _ts("2026-09-26T00:00:00Z"))],
    "ZILL": [("5m", _ts("2026-09-18T00:00:00Z"), _ts("2026-09-19T12:00:00Z")),
             ("1h", _ts("2026-09-18T00:00:00Z"), _ts("2026-09-19T12:00:00Z"))],
}

# grafico principal de cada exemplo: timeframe do professor (ALLINU/ZILLIONS sem tf informado: o que mostra o padrao)
CHART_PLAN: dict[str, tuple[str, str, str]] = {
    "BIKE": ("4h", "2026-09-03T16:00:00Z", "2026-09-16T00:00:00Z"),
    "SOLCAT": ("1h", "2026-09-17T19:00:00Z", "2026-09-28T00:00:00Z"),
    "ALLINU": ("1h", "2026-09-11T20:00:00Z", "2026-09-16T12:00:00Z"),
    "FLAME": ("5m", "2026-09-11T10:30:00Z", "2026-09-12T20:00:00Z"),
    "ZILL": ("5m", "2026-09-17T20:15:00Z", "2026-09-20T00:00:00Z"),
}

REPORT_SWEEP: dict[str, list[Any]] = {
    "measure": ["wick", "body"],
    "drop_max": [0.90, 0.95, 0.97],
    "wick_body_mult": [2.0, 1.5, 1.0],
    "box_max_ratio": [3.0, 4.0],
}


def _window(bars: list[Bar], a_iso: str, b_iso: str) -> tuple[int, int]:
    a, b = _ts(a_iso), _ts(b_iso)
    lo = next((i for i, x in enumerate(bars) if x.ts >= a), 0)
    hi = max((i for i, x in enumerate(bars) if x.ts <= b), default=len(bars) - 1)
    return lo, hi


def geometry(data: ExampleData, tf: str, a_iso: str, b_iso: str) -> dict[str, Any]:
    """Medidas de um trecho que o detector NAO reconhece (pico, queda, fundo vs L_bc, quanto subiu depois)."""
    bars = data.series.bars[tf]
    lo, hi = _window(bars, a_iso, b_iso)
    seg = bars[lo:hi + 1]
    top_i = max(range(len(seg)), key=lambda k: seg[k].high)
    top = seg[top_i]
    after = seg[top_i:]
    bot_k = min(range(len(after)), key=lambda k: after[k].low)
    bottom = after[bot_k]
    body_bottom = min(min(b.open, b.close) for b in after[: bot_k + 1])
    rebound = after[bot_k:]
    reb_top = max((b.high for b in rebound), default=None)
    step = tf_seconds(tf)
    return {
        "tf": tf,
        "topo": top.high,
        "topo_em_h_desde_graduacao": round((top.ts + step - data.ex.grad_ts) / 3600.0, 1),
        "fundo_pavio": bottom.low,
        "fundo_corpo": body_bottom,
        "queda_pavio_pct": round(100 * (1 - bottom.low / top.high), 1),
        "L_bc": data.series.l_bc,
        "fundo_abaixo_de_L_bc_pct": round(100 * (1 - body_bottom / data.series.l_bc), 1) if data.series.l_bc else None,
        "fundo_em": iso_utc(bottom.ts),
        "subiu_depois_ate": reb_top,
        "chegou_a_95pct_do_topo": bool(reb_top and reb_top >= 0.95 * top.high),
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, float):
        if abs(v) >= 1e6:
            return f"{v / 1e6:.2f}M"
        if abs(v) >= 1e4:
            return f"{v / 1e3:.0f}k"
        return f"{v:.2f}"
    return str(v)


def _entries(det: Detector) -> list[Event]:
    return [e for e in det.events if e.kind == "ENTRADA"]


def build_report(datas: list[ExampleData], out: Path, handoff: Params, proposal: Params, sweep_rows: list[dict[str, Any]]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    costs = CostModel()
    lines: list[str] = []
    rows_measures: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    seen: dict[str, dict[str, Any]] = {}
    for data in datas:
        key = data.ex.key
        tf, a_iso, b_iso = CHART_PLAN[key]
        bars = data.series.bars[tf]
        lo, hi = _window(bars, a_iso, b_iso)
        det_h = run(bars, handoff, tf, data.series.l_bc, data.ex.grad_ts)
        det_p = run(bars, proposal, tf, data.series.l_bc, data.ex.grad_ts)
        ent_p = [e for e in _entries(det_p) if lo <= e.idx <= hi]
        ent_h = [e for e in _entries(det_h) if lo <= e.idx <= hi]
        inval_p = [e for e in det_p.events if e.kind == "ONDA_INVALIDA" and lo <= e.idx <= hi]
        measured = [measure_entry(data, det_p, e, proposal, costs) for e in ent_p[:3]]
        rows_measures[key] = [(f"#{k + 1}", m.row) for k, m in enumerate(measured)]
        main_ev = ent_p[0] if ent_p else None
        trades = list(measured[0].trades.values()) if measured else []
        chart = charts.plot_setup(
            out / f"{key}_{tf}.png", bars, tf,
            f"{data.ex.name} — {tf} — proposta {proposal.version}",
            "entradas numeradas (#1 = a primeira); caixa azul = S/R da #1; laranja = power candle",
            data.series.l_bc, main_ev, det_p.events, trades, (lo, hi),
            proposal.atr_period, proposal.power_atr_mult,
        )
        overview = charts.plot_setup(
            out / f"{key}_1h_visao_geral.png", data.series.bars["1h"], "1h",
            f"{data.ex.name} — 1h — histórico inteiro (proposta)", "", data.series.l_bc, None,
            run(data.series.bars["1h"], proposal, "1h", data.series.l_bc, data.ex.grad_ts).events, (), None,
        )
        stop_i = ent_p[0].idx if ent_p else hi
        top_i = max(range(lo, stop_i + 1), key=lambda k: bars[k].high)
        bot_i = min(range(min(top_i + 1, stop_i), stop_i + 1), key=lambda k: bars[k].low)   # depois do candle do topo
        seen[key] = {
            "queda_pavio_pct": round(100 * (1 - bars[bot_i].low / bars[top_i].high), 1),
            "tf": tf, "chart": chart.name if chart else None, "overview": overview.name if overview else None,
            "handoff": [iso_utc(e.ts) for e in ent_h], "proposta": [iso_utc(e.ts) for e in ent_p],
            "invalida": [(iso_utc(e.ts), e.data["motivo"]) for e in inval_p],
        }
    solcat = next(d for d in datas if d.ex.key == "SOLCAT")
    geo = geometry(solcat, "1h", "2026-09-17T19:00:00Z", "2026-09-27T00:00:00Z")

    # ---------- texto ----------
    L = lines.append
    L("# POS-RUNNER-V0 — Passo 0: calibração com os 5 exemplos do professor")
    L("")
    L(f"Gerado em {iso_utc(utc_now())}. **Isto é calibração, não avaliação**: os 5 exemplos são vencedores escolhidos "
      "depois e ficam fora de todas as métricas de resultado. Nada foi congelado; nenhum backtest foi rodado.")
    L("")
    L(f"- Config do handoff (valores da seção 2): `{handoff.version}`")
    L(f"- Config proposta (este relatório): `{proposal.version}` — arquivo `signals_mvp/pos_runner/pos_runner_v0.yaml`")
    L("")
    L("## Resumo")
    L("")
    L("1. **Contratos**: os 5 mints e pools existem e a linhagem foi conferida on-chain. Duas correções na tabela do "
      "handoff: ALLINU **não é Meteora** — é Raydium LaunchLab cotado em DKNG (o pool do handoff, Meteora DLMM, foi "
      "criado 54 min depois por outra carteira; o preço é o mesmo); e o **SOLCAT está em ~30k de MC hoje, não ~575k** "
      "(o resto bate com o que o handoff descreve). Os 3 launchpads aparecem: pump.fun (BIKE, SOLCAT), Raydium "
      "LaunchLab (ALLINU, ZILLIONS) e Meteora DBC (FLAME).")
    with_entry = [k for k, v in seen.items() if v["handoff"]]
    without = [k for k, v in seen.items() if not v["handoff"]]
    drops_txt = ", ".join(f"{k} {seen[k]['queda_pavio_pct']:.0f}%" for k in without)
    entry_txt = ", ".join(f"{k} ({', '.join(seen[k]['handoff'])})" for k in with_entry) or "nenhum"
    L("2. **Com os números do handoff ao pé da letra** o detector só acha entrada em: " + entry_txt + ". Nos outros a "
      "onda é invalidada antes, porque a queda medida de pavio a pavio (topo do runner até o fundo) passa do teto de "
      f"90%: {drops_txt}.")
    L("3. **Proposta (4 mudanças)**: medir pico, queda e caixa pelos **corpos** dos candles; teto de queda **95%**; "
      "martelo com pavio **≥ 1,5× o corpo**; alvo no **topo real** (máxima). Com isso o detector reconhece **4 de 5** "
      "(BIKE, ALLINU, FLAME e uma entrada no ZILLIONS que provavelmente não é a do professor). Os números de caixa "
      "(12 candles, R/S ≤ 3, zona de 5%) não mudaram nada nos exemplos e ficam como no handoff.")
    L("4. **SOLCAT não é reconhecido com nenhuma variante**: a base de 23–24/09 ficou ~25% **abaixo** do nível da "
      "bonding curve (L_bc ≈ 43k) e a queda total foi de 98%. Pela regra do próprio operador (\"fundo acima da "
      "bonding curve\") esse trecho é inválido — preciso saber se o setup do professor é esse.")
    L("5. **Filtro de idade**: o BIKE rompeu com 9 dias e o ALLINU com 1,9 dia; a janela de 2–7 dias do handoff "
      "tiraria os dois do resultado primário. Proposta: idade só como atributo (com resultado por faixa de idade).")
    L("")
    L("## 1. Os 5 exemplos, conferidos on-chain")
    L("")
    L("| Exemplo | Launchpad (on-chain) | Pool de graduação | Cotação | Graduação (UTC) | L_bc (MC na graduação) | Observação |")
    L("|---|---|---|---|---|---|---|")
    for data in datas:
        ex = data.ex
        L(f"| {ex.name} | {ex.launchpad} — `{ex.migration_ix}` | `{ex.pool}` | {ex.quote_symbol} | {ex.grad_iso} | "
          f"{_fmt(data.series.l_bc)} | {ex.note or '—'} |")
    L("")
    L("Dados: OHLCV do GeckoTerminal do pool de graduação, pedido **em token de cotação** e convertido com a cotação/USD "
      "de referência. No ZILLIONS o USD do próprio GeckoTerminal ficou travado em ~1,0M por 24 h (erro de até 364% "
      "contra o pool ZILLIONS/SOL); a série convertida bate com os pools independentes cotados em SOL (diferença "
      "mediana de 1–2% no FLAME e no ALLINU). Todas as séries de 5m conferidas contra o 1h: zero buracos.")
    L("")
    L("## 2. O que o detector vê (gráficos)")
    L("")
    for data in datas:
        k = data.ex.key
        info = seen[k]
        L(f"### {data.ex.name} — {info['tf']}" + (" (timeframe do professor)" if data.ex.tf_prof == info["tf"] else " (o professor não informou o timeframe)"))
        L("")
        if info["chart"]:
            L(f"![{k}]({info['chart']})")
        L("")
        L(f"- Com os parâmetros do handoff: {', '.join(info['handoff']) or 'nenhuma entrada nesta janela'}.")
        L(f"- Com a proposta: {', '.join(f'#{n + 1} {t}' for n, t in enumerate(info['proposta'])) or 'nenhuma entrada nesta janela'}.")
        for t, motivo in info["invalida"]:
            L(f"- Onda invalidada em {t}: {motivo}.")
        L(f"- Visão geral do histórico no 1h: `{info['overview']}`")
        L("")
    L("## 3. Medidas reais de cada exemplo (proposta)")
    L("")
    keys = ["tf", "rompimento", "idade_d", "P_peak", "topo_maxima", "topo_em_h_desde_graduacao", "L_bc", "queda_pct", "caixa_candles",
            "S", "R", "R_S", "n_wicks", "pavio_sobre_corpo_mediana", "vol_rompimento_x_media", "amplitude_rompimento_atr",
            "power_candle", "cobertura_R_ate_pico", "entrada", "stop", "alvo", "subida_max_48c_pct", "chegou_no_alvo",
            "candles_ate_alvo", "saida_A", "saida_B"]
    cols = [(k, tag, row) for k, rows in rows_measures.items() for tag, row in rows[:2]]
    L("| medida | " + " | ".join(f"{k} {tag}" for k, tag, _ in cols) + " |")
    L("|---|" + "---|" * len(cols))
    for name in keys:
        L(f"| {name} | " + " | ".join(_fmt(row.get(name)) for _, _, row in cols) + " |")
    L("")
    L("SOLCAT não tem entrada (a onda é invalidada antes). Geometria medida no trecho 17/09–27/09 (1h):")
    L("")
    L("| medida | valor |")
    L("|---|---|")
    for name, val in geo.items():
        L(f"| {name} | {_fmt(val)} |")
    L("")
    L("## 4. Varredura (só para achar o mínimo que reconhece os exemplos)")
    L("")
    total = len(sweep_rows)
    L(f"{total} variantes = " + " × ".join(f"{k} {v}" for k, v in REPORT_SWEEP.items()) +
      " (alvo no topo real e sem filtro de idade em todas). \"Reconhece\" = alguma ENTRADA dentro da janela que eu "
      "li no gráfico como o rompimento do professor (a confirmar).")
    L("")
    for k in LABELS:
        L(f"- {k}: reconhecido em {sum(1 for r in sweep_rows if r['reconhece'][k])} de {total} variantes")
    best = max(r["n"] for r in sweep_rows)
    L(f"- Máximo reconhecido por uma variante: {best} de 5.")
    L("")
    p_body = [r for r in sweep_rows if r["params"]["measure"] == "body" and r["n"] == best]
    if p_body:
        L("Variantes que chegam no máximo: " + "; ".join(json.dumps(r["params"]) for r in p_body[:8]))
    L("")
    L("## 5. Proposta de parâmetros e o motivo de cada número")
    L("")
    L("| parâmetro | handoff | proposta | motivo |")
    L("|---|---|---|---|")
    motives = {
        "measure": "Suporte/resistência horizontais se traçam nos corpos; os pavios são os \"testes\" (wicks). Com pavios, "
                   "um único print (sniper, falso rompimento) estica R e quebra a regra R/S (ALLINU 1h) e a queda passa "
                   "de 90% em quase todos. Medido pelos corpos no timeframe do professor, o BIKE caiu 85% — dentro dos 80–90%.",
        "drop_max": "Pelos corpos, as quedas dos exemplos reconhecidos foram de 84% a 95% (ALLINU 1h: 94,7% até a base). 90% tira o ALLINU. "
                    "A invalidação do operador é furar L_bc, que continua valendo; 95% é o menor valor da grade que "
                    "reconhece o ALLINU (97% dá o mesmo resultado).",
        "wick_body_mult": "Com 2×, o candle de capitulação do FLAME (pavio 1,3–1,4× o corpo) não conta como wick e o "
                          "rompimento verdadeiro de 12/09 08:05 não arma. 1,5× é o maior valor da grade que reconhece o FLAME "
                          "(1,0× dá o mesmo resultado).",
        "tp_reference": "\"Saída no último topo\": o topo é onde o preço negociou (a máxima), não o topo do corpo. Só muda o alvo "
                        "e o teste do candle absurdo.",
        "age_window_days": "BIKE rompeu com 9,0 dias e ALLINU com 1,9 dia: a janela de 2–7 dias tiraria 2 dos 4 exemplos "
                           "reconhecidos do resultado primário. Proposta: só atributo (resultado reportado por faixa de idade). "
                           "Pergunta abaixo.",
    }
    hd, pd = handoff.as_dict(), proposal.as_dict()
    for k in ("measure", "drop_max", "wick_body_mult", "tp_reference", "age_window_days"):
        L(f"| `{k}` | {json.dumps(hd[k])} | {json.dumps(pd[k])} | {motives[k]} |")
    for k in ("runner_min_mc", "drop_min", "bounce_fractal", "box_min_candles", "box_max_ratio", "wick_zone", "wick_min",
              "wick_break", "breakout_vol_mult", "atr_period", "power_atr_mult", "absurd_frac", "stop_below_wick",
              "tp_frac_of_peak", "exhaustion_gain", "time_stop_candles", "partial_frac", "trail_frac"):
        L(f"| `{k}` | {json.dumps(hd[k])} | {json.dumps(pd[k])} | igual ao handoff |")
    L("")
    L("Mudanças de desenho (não são números, valem para todas as variantes):")
    L("")
    L("- **Caixa** = o maior trecho **recente** depois do 1º repique que cabe em R/S ≤ 3. Ao pé da letra (caixa = tudo "
      "desde o 1º repique), o pico do meio da lateral do BIKE (09/07–09/08, ~1M) faz R/S passar de 6 e mata o setup.")
    L("- **Uma decisão por caixa**: depois de uma entrada, a caixa recomeça; setups seguintes no mesmo token viram "
      "diagnóstico (o handoff manda registrá-los). No 5m isso gera muitas caixas pequenas (faixa de 2–10%): só a "
      "primeira entrada por token e timeframe conta no resultado primário.")
    L("- **Preço** em token de cotação × cotação/USD (por causa do erro do USD do GeckoTerminal no ZILLIONS).")
    L("")
    L("## 6. O que o detector ainda não vê (e por quê)")
    L("")
    L("- **SOLCAT**: queda de 98% e base ~25% abaixo de L_bc. Se o setup do professor for a base de 23–24/09, a regra "
      "\"fundo acima da bonding curve\" precisaria de tolerância — mas aí ela deixa de ser a regra do operador.")
    L("- **FLAME**: a 1ª entrada (12/09 02:35) foi um falso rompimento e bateu o stop (−63% líquido: o stop fica abaixo "
      "da wick, longe da entrada). O movimento verdadeiro (08:05 em diante, que chegou ao topo às 16:00) aparece como "
      "entrada #2 — diagnóstico, não primária. É o comportamento correto da regra \"só o 1º setup conta\".")
    L("- **ZILLIONS**: não sei qual trecho é o do professor. As entradas que o detector acha (19/09) deram prejuízo. "
      "O handoff cita MC ~135k, que é o preço de hoje (15/10), quando o token acabou de subir de ~6k para ~300k — "
      "um runner novo, ainda sem fase 2.")
    allinu = rows_measures.get("ALLINU", [])
    if allinu:
        r0 = allinu[0][1]
        L(f"- **Saída por exaustão**: a regra do handoff (power candle verde com +50% desde a entrada) sai cedo em "
          f"movimentos grandes — no ALLINU #1 a saída A foi {r0['saida_A']}, e a máxima nas 48 horas seguintes ficou "
          f"{r0['subida_max_48c_pct']:.0f}% acima da entrada. O operador escreveu \"power candle perto do topo = "
          "exaustão\"; uma leitura alternativa seria \"preço já perto do último topo\". Mantive a do handoff.")
    L("- **Candles** aproximam wicks e rompimentos (não sabemos a ordem dos preços dentro do candle; tocar stop e alvo "
      "no mesmo candle conta como stop).")
    L("")
    L("## 7. Perguntas ao operador (respostas destravam o congelamento)")
    L("")
    L("1. Os gráficos acima são os tokens que o professor mostrou? Em especial o **SOLCAT** (MC ~30k hoje, não ~575k) "
      "e o **ZILLIONS** (qual trecho/data?).")
    L("2. Em cada gráfico, qual é o setup do professor? Basta o número da entrada (#1, #2…) ou a data do rompimento.")
    L("3. **SOLCAT**: a base de 23–24/09 ficou abaixo do nível da bonding curve. A regra \"fundo acima da bonding "
      "curve\" continua valendo (SOLCAT fica de fora) ou tem tolerância?")
    L("4. \"Tokens de 2–7 dias em fase 2\": é a **idade do token** desde a graduação, ou o **tempo na fase 2**? "
      "Pode ficar só como atributo (proposta)?")
    L("5. Saída por exaustão: \"+50% desde a entrada\" (handoff) ou \"perto do último topo\"?")
    L("6. Aprova a proposta (corpos, queda até 95%, martelo ≥ 1,5× corpo, alvo no topo real)?")
    L("7. Parte A: horizonte de observação de 14 dias depois da graduação e mínimo de 20 trades no holdout — ok?")
    L("8. O POS-RUNNER ocupa o \"caminho 2\" da regra de parada do programa?")
    L("")
    L("## 8. Próximo passo")
    L("")
    L("Com as respostas: congelar a config (hash) no pré-registro `docs/pos-runner-v0-preregistration-DRAFT-2026-10-15.md`, "
      "commitar, e só então rodar a Parte A (universo sem viés: a enumeração já acha a graduação dos 5 exemplos nos 3 "
      "launchpads). A Parte B (sinal ao vivo no bot) usa a mesma config congelada.")
    L("")
    (out / "relatorio_passo0.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "medidas.json").write_text(json.dumps({"medidas": rows_measures, "solcat_geometria": geo, "visto": seen},
                                                 indent=1, default=str), encoding="utf-8")
    (out / "varredura.json").write_text(json.dumps(sweep_rows, indent=1), encoding="utf-8")
    return out / "relatorio_passo0.md"


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
    proposal = load_params()
    handoff = Params()
    global SWEEP
    SWEEP = REPORT_SWEEP
    base = dataclasses.replace(proposal)
    rows = run_sweep(datas, base, LABELS)
    path = build_report(datas, args.out, handoff, proposal, rows)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
