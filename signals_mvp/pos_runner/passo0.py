"""Passo 0 do POS-RUNNER-V0 — o que o detector ve nos 5 exemplos do professor (CALIBRACAO DA DETECCAO, nunca avaliacao).

    python -m signals_mvp.pos_runner.passo0 --cache <pasta de cache OHLCV> --out <pasta do relatorio> [--fim ISO]

Versao 2 (2026-10-16): roda o detector com as REGRAS DO OPERADOR (config candidata a congelamento) nos 3 timeframes
de cada exemplo e mostra as FASES que ele detecta (runner, fase 2, zona, testes de suporte, zona madura, entrada,
invalidacoes), com os graficos. Por decisao do operador os exemplos so calibram a deteccao das fases: nenhum numero
de entrada/saida sai daqui, nao ha varredura de parametros e NAO ha resultado de trade (os exemplos ficam fora de
todas as metricas). A versao 1 (proposta de calibracao com varredura, 2026-10-15) esta em `passo0_relatorio/` e no
historico do git (commit f1f9a6d).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..http import HttpClient, RateLimiter
from ..util import iso_utc, parse_iso, utc_now
from . import charts
from .candles import Bar, OhlcvStore, tf_seconds
from .detector import Detector, Event, run
from .examples import EXAMPLES, QUOTE_REFERENCES, Example
from .params import Params, load_params
from .quotes import SOL_MINT, STABLES
from .series import PoolSeries, build_series, quote_usd

TFS = ("5m", "1h", "4h")
GT_BASE = "https://api.geckoterminal.com/api/v2"


def make_store(cache: Path, per_min: float = 20.0) -> OhlcvStore:
    http = HttpClient(GT_BASE, RateLimiter(per_min, 2, pause_s=30, pause_max_s=240), 30, name="GeckoTerminal")
    return OhlcvStore(http, cache)


@dataclass
class ExampleData:
    ex: Example
    series: PoolSeries
    sol_usd: Any                      # UsdSeries da SOL (nao usada na v2; mantida para a carga ser a mesma da v1)
    end_ts: int
    usd: Any = None                   # UsdSeries da cotacao do pool (conversao token de cotacao -> USD)


def load_example(store: OhlcvStore, ex: Example, end_ts: int, cross_check: bool = True) -> ExampleData:
    usd = quote_usd(store, ex.quote_mint, QUOTE_REFERENCES, ex.grad_ts, end_ts)
    if usd is None:
        raise RuntimeError(f"{ex.key}: sem serie de referencia USD para a cotacao {ex.quote_symbol}")
    sol = usd if ex.quote_mint == SOL_MINT else quote_usd(store, SOL_MINT, QUOTE_REFERENCES, ex.grad_ts, end_ts)
    series = build_series(store, ex.pool, ex.grad_ts, end_ts, ex.supply, usd, TFS, cross_check=cross_check)
    return ExampleData(ex, series, sol, end_ts, usd)


def _ts(iso: str) -> int:
    return int(parse_iso(iso) or 0)


# grafico principal de cada exemplo: timeframe do professor (ALLINU/ZILLIONS sem tf informado: o mesmo da v1)
CHART_PLAN: dict[str, tuple[str, str, str]] = {
    "BIKE": ("4h", "2026-09-03T16:00:00Z", "2026-09-16T00:00:00Z"),
    "SOLCAT": ("1h", "2026-09-17T19:00:00Z", "2026-09-29T12:00:00Z"),
    "ALLINU": ("1h", "2026-09-11T20:00:00Z", "2026-09-16T12:00:00Z"),
    "FLAME": ("5m", "2026-09-11T10:30:00Z", "2026-09-12T20:00:00Z"),
    "ZILL": ("5m", "2026-09-17T20:15:00Z", "2026-09-20T00:00:00Z"),
}


def _window(bars: list[Bar], a_iso: str, b_iso: str) -> tuple[int, int]:
    a, b = _ts(a_iso), _ts(b_iso)
    lo = next((i for i, x in enumerate(bars) if x.ts >= a), 0)
    hi = max((i for i, x in enumerate(bars) if x.ts <= b), default=len(bars) - 1)
    return lo, hi


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


def _when(det: Detector, i: int) -> str:
    return iso_utc(det.bars[i].ts)[:16].replace("T", " ")


# ---------------------------------------------------------------------------
# fases detectadas
# ---------------------------------------------------------------------------


def waves(det: Detector, l_bc: Optional[float]) -> list[dict[str, Any]]:
    """Uma linha por onda que chegou a fase 2: pico, fase 2, zona madura, testes, entradas, como a onda acabou e a
    queda maxima da onda medida de dois jeitos (extremos = regra em uso; corpos = alternativa da v1)."""
    out: dict[int, dict[str, Any]] = {}
    runner_idx: dict[int, int] = {}
    for ev in det.events:
        w = ev.data.get("onda")
        if ev.kind == "RUNNER":
            runner_idx[w] = ev.idx
        if ev.kind == "FASE2":
            out[w] = {"onda": w, "pico": ev.data["P_peak"], "faixa": det.p.peak_band(ev.data["P_peak"]),
                      "fase2": _when(det, ev.idx), "fase2_idx": ev.idx, "queda_fase2": ev.data["queda_pct"],
                      "inicio_idx": runner_idx.get(w, 0), "fim_idx": len(det.bars) - 1,
                      "maduras": [], "testes": 0, "entradas": [], "absurdos": [], "invalidados": 0, "fim": "—"}
        row = out.get(w)
        if row is None:
            continue
        if ev.kind == "TESTE":
            row["testes"] += 1
        elif ev.kind == "WATCHLIST":
            row["maduras"].append({"quando": _when(det, ev.idx), "S": ev.data["S"], "R": ev.data["R"], "testes": ev.data["n_testes"],
                                   "candles": ev.data["box_len"], "idade": ev.data["idade_dias"], "idx": ev.idx})
        elif ev.kind == "ENTRADA":
            d = ev.data
            row["entradas"].append({"quando": _when(det, ev.idx), "primario": d["primario"], "idade": d["idade_dias"],
                                    "fora_da_janela": not d["na_janela"], "queda": d["queda_pct"], "S": d["S"], "R": d["R"],
                                    "testes": d["n_testes"], "S_sobre_Lbc": d["S_sobre_Lbc"], "idx": ev.idx})
        elif ev.kind == "ABSURDO":
            row["absurdos"].append(_when(det, ev.idx))
        elif ev.kind == "INVALIDADO":
            row["invalidados"] += 1
        elif ev.kind == "ONDA_INVALIDA":
            row["fim"] = f"{_when(det, ev.idx)}: {ev.data['motivo']} (queda {ev.data['queda_pct']:.1f}%)"
            row["fim_idx"] = ev.idx
            row["morta"] = True
    for w, row in out.items():
        if row["fim"] == "—":
            nxt = next((e for e in det.events if e.kind == "RUNNER" and e.data.get("onda", 0) > w), None)
            row["fim"] = f"{_when(det, nxt.idx)}: nova máxima acima do pico (nova onda)" if nxt else "ainda aberta no fim dos dados"
            if nxt:
                row["fim_idx"] = nxt.idx - 1
        row.update(wave_drop(det.bars, row["inicio_idx"], row["fase2_idx"], row["fim_idx"], l_bc))
    return [out[k] for k in sorted(out)]


def wave_drop(bars: list[Bar], start: int, f2: int, end: int, l_bc: Optional[float]) -> dict[str, Any]:
    """Queda maxima da onda (do pico ate o fim da onda) pelos EXTREMOS e pelos CORPOS, e o fundo sobre L_bc."""
    top = max(range(start, f2 + 1), key=lambda k: bars[k].high)
    low = min((bars[k].low for k in range(top + 1, end + 1)), default=bars[top].low)
    top_b = max(range(start, f2 + 1), key=lambda k: max(bars[k].open, bars[k].close))
    peak_b = max(bars[top_b].open, bars[top_b].close)
    low_b = min((min(bars[k].open, bars[k].close) for k in range(top_b + 1, end + 1)), default=peak_b)
    return {"queda_max_extremos": 100 * (1 - low / bars[top].high), "queda_max_corpos": 100 * (1 - low_b / peak_b),
            "fundo_Lbc_extremos": low / l_bc if l_bc else None, "fundo_Lbc_corpos": low_b / l_bc if l_bc else None}


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _first_entry(det: Detector, lo: int, hi: int) -> Optional[Event]:
    return next((e for e in det.events if e.kind == "ENTRADA" and lo <= e.idx <= hi), None)


def _wave_peak(det: Detector, lo: int, hi: int) -> Optional[float]:
    ev = next((e for e in det.events if e.kind == "FASE2" and lo <= e.idx <= hi), None)
    return ev.data["P_peak"] if ev else None


def build_report(datas: list[ExampleData], out: Path, params: Params) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    found: dict[str, dict[str, Any]] = {}
    for data in datas:
        ex = data.ex
        dets = {tf: run(data.series.bars[tf], params, tf, data.series.l_bc, ex.grad_ts, ex.created_ts) for tf in TFS}
        tf, a_iso, b_iso = CHART_PLAN[ex.key]
        det = dets[tf]
        lo, hi = _window(det.bars, a_iso, b_iso)
        peak = _wave_peak(det, lo, hi)
        levels = [(params.support_min_lbc * data.series.l_bc, f"{params.support_min_lbc:.2f}xL_bc", "#999999")] if data.series.l_bc else []
        if peak:
            levels += [((1 - params.drop_min) * peak, f"queda {100 * params.drop_min:.0f}%", "#6d4c41"),
                       ((1 - params.drop_max) * peak, f"queda {100 * params.drop_max:.0f}% (morta)", "#c62828")]
        chart = charts.plot_setup(
            out / f"{ex.key}_{tf}.png", det.bars, tf, f"{ex.name} — {tf} — config {params.version} (regras do operador)",
            "▼ fase 2 · ▲ teste de suporte · ● zona madura · #n entrada · x invalidado · X onda morta; azul = zona da 1ª entrada",
            data.series.l_bc, _first_entry(det, lo, hi), det.events, (), (lo, hi), params.atr_period, params.power_atr_mult,
            levels=levels)
        overview = charts.plot_setup(
            out / f"{ex.key}_1h_visao_geral.png", dets["1h"].bars, "1h", f"{ex.name} — 1h — histórico inteiro",
            "mesmas marcas do gráfico principal", data.series.l_bc, None, dets["1h"].events, (), None)
        found[ex.key] = {
            "tf": tf, "chart": chart.name if chart else None, "overview": overview.name if overview else None,
            "ondas": {t: waves(d, data.series.l_bc) for t, d in dets.items()},
            "cotacao": ex.quote_symbol, "cotacao_estavel_ou_sol": ex.quote_mint in STABLES or ex.quote_mint == SOL_MINT,
            "pico_inicial": first_peak_by_tf(data, dets),
        }
    text = render(datas, found, params)
    path = out / "relatorio_passo0_v2.md"
    path.write_text(text, encoding="utf-8")
    (out / "fases.json").write_text(json.dumps(found, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    return path


def first_peak_by_tf(data: ExampleData, dets: dict[str, Detector], hours: int = 24) -> dict[str, dict[str, Any]]:
    """Candle com o maior PRECO NA MOEDA DE COTACAO nas primeiras `hours` horas depois da graduacao, em cada tf: esse
    preco (o mesmo nos 3 tfs), a cotacao/USD usada na conversao (a do FECHAMENTO do candle) e o MC em USD resultante."""
    out = {}
    if data.usd is None:
        return out
    for tf, det in dets.items():
        step = tf_seconds(tf)
        rows = []
        for b in det.bars:
            f = data.usd.at(b.ts + step)
            if b.ts < data.ex.grad_ts + hours * 3600 and not b.filled and f:
                rows.append((b.high / (f * data.ex.supply), f, b))
        if not rows:
            continue
        px, f, b = max(rows, key=lambda r: r[0])
        out[tf] = {"mc": b.high, "em": iso_utc(b.ts), "cotacao_usd": f, "preco_em_cotacao": px}
    return out


def _entries_txt(entries: list[dict[str, Any]], limit: int = 3) -> str:
    if not entries:
        return "nenhuma"
    parts = []
    for e in entries[:limit]:
        tag = "primária" if e["primario"] else ("fora de 2–7 d" if e["fora_da_janela"] else "não primária")
        parts.append(f"{e['quando']} ({tag}, idade {_fmt(e['idade'])} d, {e['testes']} teste(s))")
    more = f" +{len(entries) - limit}" if len(entries) > limit else ""
    return "; ".join(parts) + more


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _sig(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.6g}"


def render(datas: list[ExampleData], found: dict[str, dict[str, Any]], params: Params) -> str:
    L: list[str] = []
    a = L.append
    lo_age, hi_age = params.age_window_days
    a("# POS-RUNNER-V0 — Passo 0, versão 2: o que o detector vê nos 5 exemplos (regras do operador)")
    a("")
    a(f"Gerado em {iso_utc(utc_now())}. Config candidata a congelamento: `{params.version}` "
      "(`signals_mvp/pos_runner/pos_runner_v0.yaml`). **Calibração da detecção, não avaliação**: os 5 exemplos ficam fora "
      "de todas as métricas; aqui não há varredura de parâmetros nem resultado de trade (por decisão do operador, os "
      "parâmetros de entrada vêm das regras dele, não de \"acertar\" os exemplos). Mesmos candles da versão 1 (instantâneo "
      "de 2026-10-15 em `passo0_relatorio/dados/`, sem rede).")
    a("")
    a("Regras aplicadas (todas do operador; o que ele não respondeu seguiu a opção mais conservadora — lista no pré-registro):")
    a("")
    a(f"- **Fase 1**: pico (máxima) da onda ≥ {params.runner_min_mc:,.0f}; a faixa do pico é atributo (300–500k, 500k–1M, 1–5M, >5M).")
    a(f"- **Fase 2**: queda (mínima desde o pico) ≥ {100 * params.drop_min:.0f}% abre a zona; queda > {100 * params.drop_max:.0f}% = "
      f"moeda morta; fundo < {params.support_min_lbc} × L_bc = onda inválida. R = máxima das tentativas de subida depois do fundo, "
      "**incluindo o 1º repique** (que nunca é comprado).")
    a(f"- **Teste de suporte**: de dentro da zona, a mínima desce a ≤ S × {1 + params.test_zone:.2f} e depois o preço fecha de "
      f"volta ≥ min((S+R)/2, S × {params.recover_mult}); 1 ou muitos candles. Fechamento < mínima do último teste − "
      f"{100 * params.test_break:.0f}% = setup morto; stop = mínima do último teste − {100 * params.stop_below_test:.0f}%.")
    a(f"- **Entrada**: zona madura (≥ {params.zone_min_candles} candles desde o fundo e ≥ {params.tests_min} teste) e fechamento "
      f"acima de R; sem exigência de volume; veto se um candle cobre ≥ {100 * params.absurd_frac:.0f}% do caminho R → pico. "
      f"Primária só a 1ª entrada por token/timeframe com idade {lo_age:.0f}–{hi_age:.0f} dias desde a CRIAÇÃO do token.")
    a("")
    # ---------- resumo (tudo calculado) ----------
    a("## Resumo")
    a("")
    all_waves = [(d.ex.key, tf, w) for d in datas for tf in TFS for w in found[d.ex.key]["ondas"][tf]]
    n_dead = sum(1 for _, _, w in all_waves if w.get("morta"))
    seen_all = 0
    prim_all: list[tuple[str, str, dict[str, Any]]] = []
    for data in datas:
        k = data.ex.key
        f = found[k]
        seen = [(tf, w) for tf in TFS for w in f["ondas"][tf]]
        mature = [(tf, w) for tf, w in seen if w["maduras"]]
        entries = [(tf, e) for tf, w in seen for e in w["entradas"]]
        prim = [(tf, e) for tf, e in entries if e["primario"]]
        prim_all += [(data.ex.name, tf, e) for tf, e in prim]
        seen_all += bool(seen)
        tfs_f2 = sorted({tf for tf, _ in seen}, key=TFS.index)
        tfs_m = sorted({tf for tf, _ in mature}, key=TFS.index)
        line = (f"- **{data.ex.name}**: fase 2 detectada em {', '.join(tfs_f2) or 'nenhum timeframe'}; zona madura (👀) em "
                f"{', '.join(tfs_m) or 'nenhum'}; {len(entries)} entrada(s) nos 3 timeframes, {len(prim)} primária(s)")
        if prim:
            line += " — " + "; ".join(f"{tf} {e['quando']} (idade {_fmt(e['idade'])} d)" for tf, e in prim)
        ages = sorted(e["idade"] for _, e in entries if e["idade"] is not None)
        if entries and ages:
            line += f". Idade nas entradas: {_fmt(ages[0])}–{_fmt(ages[-1])} dias desde a criação."
        else:
            line += "."
        a(line)
    a("")
    a(f"Leitura: o detector vê a fase 2 de {seen_all} dos {len(datas)} exemplos em pelo menos um timeframe (o SOLCAT, que o "
      f"operador descreveu como fase 2 em formação, aparece com zona madura antes de morrer). Das {len(all_waves)} ondas que "
      f"chegaram à fase 2 nos 3 timeframes, {n_dead} terminaram como **moeda morta** (queda passou de "
      f"{100 * params.drop_max:.0f}%) depois de a zona se formar. Entradas primárias (idade {lo_age:.0f}–{hi_age:.0f} dias): "
      + (", ".join(f"{n} {tf} {e['quando']}" for n, tf, e in prim_all) or "nenhuma")
      + ". Nada foi ajustado para os exemplos: é a regra do operador aplicada como está.")
    a("")
    # ---------- por exemplo ----------
    a("## 1. Fases detectadas, exemplo por exemplo")
    a("")
    for data in datas:
        k = data.ex.key
        f = found[k]
        ex = data.ex
        a(f"### {ex.name} — {ex.launchpad}, cotado em {ex.quote_symbol} — criado {ex.created_iso}, graduado {ex.grad_iso}, "
          f"L_bc {_fmt(data.series.l_bc)}")
        a("")
        if f["chart"]:
            a(f"![{k}]({f['chart']})")
            a("")
        a(f"Gráfico principal no {f['tf']}" + (" (timeframe do professor)." if ex.tf_prof == f["tf"] else " (o professor não informou o timeframe).")
          + f" Histórico inteiro no 1h: `{f['overview']}`.")
        a("")
        a("| tf | onda | pico (faixa) | fase 2 em (queda) | testes | zona madura 👀 (S – R, testes, candles, idade) | entradas | invalidações | fim da onda |")
        a("|---|---|---|---|---|---|---|---|---|")
        for tf in TFS:
            for w in f["ondas"][tf]:
                m = w["maduras"][0] if w["maduras"] else None
                mtxt = (f"{m['quando']} ({_fmt(m['S'])} – {_fmt(m['R'])}, {m['testes']}, {m['candles']}, {_fmt(m['idade'])} d)"
                        + (f" +{len(w['maduras']) - 1}" if len(w["maduras"]) > 1 else "")) if m else "não amadureceu"
                a(f"| {tf} | {w['onda']} | {_fmt(w['pico'])} ({w['faixa']}) | {w['fase2']} ({w['queda_fase2']:.1f}%) | {w['testes']} | "
                  f"{mtxt} | {_entries_txt(w['entradas'])} | {w['invalidados']} | {w['fim']} |")
        a("")
    # ---------- medida ----------
    a("## 2. A medida da queda: extremos (em uso) × corpos")
    a("")
    a("O operador fixou a queda em [80%, 90%] e não respondeu se ela se mede pelos pavios ou pelos corpos. A config usa "
      "os **extremos** (máxima e mínima: o preço negociou ali) — a opção conservadora (mais ondas morrem). Queda máxima de "
      "cada onda do timeframe principal, do pico até o fim da onda, medida dos dois jeitos:")
    a("")
    a("| exemplo | tf | onda | queda máx. extremos | queda máx. corpos | fundo/L_bc extremos | fundo/L_bc corpos | pelos corpos a onda morreria? |")
    a("|---|---|---|---|---|---|---|---|")
    flips = 0
    for data in datas:
        f = found[data.ex.key]
        for w in f["ondas"][f["tf"]]:
            dies_b = w["queda_max_corpos"] > 100 * params.drop_max or (w["fundo_Lbc_corpos"] is not None and w["fundo_Lbc_corpos"] < params.support_min_lbc)
            flips += bool(w.get("morta")) and not dies_b
            a(f"| {data.ex.name} | {f['tf']} | {w['onda']} | {_pct(w['queda_max_extremos'])} | {_pct(w['queda_max_corpos'])} | "
              f"{_fmt(w['fundo_Lbc_extremos'])} | {_fmt(w['fundo_Lbc_corpos'])} | {'sim' if dies_b else 'não'} |")
    a("")
    a(f"Ondas do timeframe principal que morrem pelos extremos mas sobreviveriam pelos corpos: {flips}. A medida muda "
      "**quais ondas morrem**; a zona é detectada antes, enquanto a queda ainda está entre 80% e 90% (seção 1).")
    a("")
    # ---------- cotacao ----------
    a("## 3. Limitação medida: cotação exótica em candle grande")
    a("")
    a("O MC em USD de cada candle = preço na moeda de cotação × cotação/USD **no fechamento do candle**. Com SOL ou estável a "
      "cotação anda pouco dentro de 1 h; com cotação exótica que se move junto com o token, a máxima do 1h/4h distorce. Topo "
      "das primeiras 24 h depois da graduação (maior preço na moeda de cotação), em cada timeframe:")
    a("")
    a("| exemplo (cotação) | tf | candle | preço no topo (moeda de cotação) | cotação/USD usada (fechamento) | MC do topo (USD) |")
    a("|---|---|---|---|---|---|")
    for data in datas:
        f = found[data.ex.key]
        for tf, r in f["pico_inicial"].items():
            a(f"| {data.ex.name} ({data.ex.quote_symbol}) | {tf} | {r['em'][:16]} | {_sig(r['preco_em_cotacao'])} | "
              f"{_sig(r['cotacao_usd'])} | {_fmt(r['mc'])} |")
    a("")
    a("O preço no topo é o mesmo nos 3 timeframes; quando o MC em USD não é, a diferença vem só da conversão (FLAME: o EMBER "
      "subiu junto com o token dentro da mesma hora). Na Parte A o relatório separa os resultados por tipo de cotação "
      "(SOL/estável × outra).")
    a("")
    # ---------- idade ----------
    a(f"## 4. Idade ({lo_age:.0f}–{hi_age:.0f} dias desde a criação) nas entradas dos exemplos")
    a("")
    a("| exemplo | tf | entrada | idade (dias desde a criação) | primária? |")
    a("|---|---|---|---|---|")
    for data in datas:
        f = found[data.ex.key]
        rows = [(tf, e) for tf in TFS for w in f["ondas"][tf] for e in w["entradas"]]
        for tf, e in rows[:6]:
            a(f"| {data.ex.name} | {tf} | {e['quando']} | {_fmt(e['idade'])} | {'sim' if e['primario'] else 'não'} |")
        if len(rows) > 6:
            a(f"| {data.ex.name} | … | +{len(rows) - 6} entradas (todas em `fases.json`) | | |")
        if not rows:
            a(f"| {data.ex.name} | — | nenhuma entrada antes de a onda morrer | — | — |")
    a("")
    a("## 5. O que confirmar antes de congelar")
    a("")
    a("1. O detector \"vê\" as fases que o professor mostrou? (gráficos acima).")
    a("2. Medida da queda pelos **extremos** (em uso, conservadora) — ou pelos corpos? (seção 2)")
    a("3. As escolhas conservadoras dos pontos sem resposta (lista no pré-registro, seção 5).")
    a("")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Passo 0 do POS-RUNNER-V0, v2: fases detectadas nos 5 exemplos")
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fim", default=None, help="fim da janela (ISO UTC); padrao = agora")
    args = ap.parse_args(argv)
    end = int(parse_iso(args.fim) if args.fim else utc_now())
    store = make_store(args.cache)
    datas = [load_example(store, ex, end) for ex in EXAMPLES]
    print(build_report(datas, args.out, load_params()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
