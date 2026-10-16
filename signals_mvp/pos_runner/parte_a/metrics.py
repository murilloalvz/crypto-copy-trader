"""Metricas da Parte A por variante (tf x saida) — EV liquido, PF, acerto, R, sequencia de perdas, tempo no trade,
maxima atingida em % do caminho ate o P_peak, linha de base pareada e custo 2x — e os CORTES de analise
pre-registrados (todos sao atributos, nenhum e filtro): faixa de pico (resultado completo por faixa), n de testes de
suporte, launchpad, tipo de cotacao, S >= 100k, R/S, volume do rompimento e power candle no rompimento. Escolha da
variante e criterio.
"""

from __future__ import annotations

import json
import statistics
from typing import Any, Callable, Optional

from ..quotes import SOL_MINT, STABLES
from .baseline import baseline_mean
from .pipeline import IDADE_FAIXAS, PRIMARY_COMBO, QUEDA_MEDIDAS, Context, combo_key, primary_under_window, real_tf, tf_variant

TF_HOURS = {"5m": 5 / 60, "1h": 1.0, "4h": 4.0}
BAND_ORDER = ("300-500k", "500k-1M", "1-5M", ">5M", "?")
# limiares dos cortes = os numeros do handoff original, que as regras do operador transformaram em atributo
RS_CUT = 3.0           # "caixa contida com R/S <= 3"
VOL_CUT = 2.0          # "volume do rompimento >= 2x a media da caixa"
MIN_TRADES_DISCOVERY = 30
MIN_TRADES_HOLDOUT = 30


def summarize(rets: list[float]) -> dict[str, Any]:
    if not rets:
        return {"n": 0}
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gain, loss = sum(wins), -sum(losses)
    streak = worst = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        worst = max(worst, streak)
    return {
        "n": len(rets),
        "ev_liq_pct": 100 * sum(rets) / len(rets),
        "mediana_liq_pct": 100 * statistics.median(rets),
        "pf": (gain / loss) if loss > 0 else float("inf"),
        "acerto_pct": 100 * len(wins) / len(rets),
        "pior_sequencia_perdas": worst,
    }


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def path_stats(info: list[dict[str, Any]]) -> dict[str, Any]:
    """Maxima atingida antes da saida, em % do caminho entrada -> P_peak (100 = chegou no topo)."""
    vals = [float(i["max_caminho_pct"]) for i in info if i.get("max_caminho_pct") is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "p25_pct": _quantile(vals, 0.25), "mediana_pct": _quantile(vals, 0.5),
            "p75_pct": _quantile(vals, 0.75), "chegou_a_metade_pct": 100 * sum(v >= 50 for v in vals) / len(vals),
            "chegou_ao_topo_pct": 100 * sum(v >= 100 for v in vals) / len(vals)}


def _yes_no(v: Any) -> str:
    return "sem dado" if v is None else ("sim" if v else "nao")


def _testes(i: dict[str, Any]) -> str:
    n = i.get("n_testes")
    return "?" if n is None else ("3+" if n >= 3 else str(n))


def _rs(i: dict[str, Any]) -> str:
    v = i.get("R_S")
    return "sem dado" if v is None else (f"<= {RS_CUT:g}" if v <= RS_CUT else f"> {RS_CUT:g}")


def _quote(mint: Any) -> str:
    """Cotacao do pool: com SOL/estavel a conversao para USD anda pouco dentro do candle; com moeda exotica a maxima/minima
    do 1h/4h pode distorcer (medido no Passo 0 v2: FLAME/EMBER)."""
    return "SOL/estavel" if mint == SOL_MINT or mint in STABLES else "outra"


def _vol(i: dict[str, Any]) -> str:
    v = i.get("vol_ratio")
    return "sem dado" if v is None else (f">= {VOL_CUT:g}x" if v >= VOL_CUT else f"< {VOL_CUT:g}x")


# EMENDA 2026-10-16: 3 atributos secundarios (nunca filtro, so estratificacao descritiva no relatorio -- igual aos
# cortes acima, registrados ANTES de calcular o discovery). (1) hora da entrada em BRT (UTC-3, sem horario de verao);
# (2) origem/launchpad -- ja existia como `por_launchpad` (r[12] = g.launchpad: pumpfun/raydium_launchlab/
# meteora_dbc); (3) volume do candle do ultimo teste de suporte / media de volume da zona madura (`teste_vol_ratio`,
# mesmo corte de 2x do `vol_ratio` do rompimento, para comparar com a mesma régua).
BRT_OFFSET_S = 3 * 3600
BRT_JANELA = (8, 14)   # 8h-14h inclusive vs resto


def _hora_brt(i: dict[str, Any]) -> str:
    ts = i.get("entry_ts")
    if ts is None:
        return "sem dado"
    hour = int((ts - BRT_OFFSET_S) // 3600) % 24
    lo, hi = BRT_JANELA
    return f"{lo}-{hi}h" if lo <= hour <= hi else "resto"


def _teste_vol(i: dict[str, Any]) -> str:
    v = i.get("teste_vol_ratio")
    return "sem dado" if v is None else (f">= {VOL_CUT:g}x" if v >= VOL_CUT else f"< {VOL_CUT:g}x")


# (nome, chave do grupo a partir de (info do trade, linha do trade))
CUTS: tuple[tuple[str, Callable[[dict[str, Any], tuple], str]], ...] = (
    ("por_testes", lambda i, r: _testes(i)),
    ("por_launchpad", lambda i, r: r[12]),
    ("por_cotacao", lambda i, r: _quote(r[13])),
    ("por_S_100k", lambda i, r: _yes_no(i.get("S_acima_100k"))),
    ("por_R_S", lambda i, r: _rs(i)),
    ("por_volume", lambda i, r: _vol(i)),
    ("por_power_candle", lambda i, r: _yes_no(i.get("power_candle"))),
    ("por_hora_brt", lambda i, r: _hora_brt(i)),
    ("por_vol_teste", lambda i, r: _teste_vol(i)),
)


def _stats(ctx: Context, tf: str, variant: str, sel: list[tuple], rows2: dict[tuple, tuple]) -> dict[str, Any]:
    """Estatisticas completas de um conjunto de trades fechados (ordenados pela entrada)."""
    s = summarize([r[5] for r in sel])
    if not s["n"]:
        return s
    info = [json.loads(r[11]) for r in sel]
    s["taxa_alvo_pct"] = 100 * sum(1 for r in sel if r[8]) / len(sel)
    rs = [r[7] for r in sel if r[7] is not None]
    s["R_medio"] = sum(rs) / len(rs) if rs else None
    s["R_mediano"] = statistics.median(rs) if rs else None
    s["tempo_medio_h"] = sum((r[9] or 0) * TF_HOURS[real_tf(tf)] for r in sel) / len(sel)
    s["caminho_max"] = path_stats(info)
    cost2 = [rows2[k][5] for k in ((r[0], r[1], r[2], r[3]) for r in sel) if k in rows2 and rows2[k][4] == "fechado"]
    s["custo_2x"] = summarize(cost2)
    bases, edges = [], []
    for r in sel:
        b = baseline_mean(ctx, r[0], r[1], r[2], variant)
        if b is not None:
            bases.append(b)
            edges.append(r[5] - b)
    s["base_ev_liq_pct"] = 100 * sum(bases) / len(bases) if bases else None
    s["edge_sobre_base_pct"] = 100 * sum(edges) / len(edges) if edges else None
    s["base_cobertura"] = f"{len(bases)}/{len(sel)}"
    return s


def variant_table(ctx: Context, period: str) -> dict[str, Any]:
    """Grade de 24 combinacoes (EMENDA 2026-10-16, ANTES de qualquer calculo do discovery, hash novo): tf x saida
    x medida da queda (extremos/fechamentos, detector diferente) x faixa de idade (2-7/1-10, reclassificada dos
    atributos ja gravados, sem detector novo). Chave: `combo_key(tf, saida, medida, faixa)`, ex. "1h/A/extremos/2-7"
    (a combinacao primaria original, `PRIMARY_COMBO`)."""
    rows = ctx.store.trades(period, "setup")
    rows2 = {(r[0], r[1], r[2], r[3]): r for r in ctx.store.trades(period, "setup_custo2x")}
    out: dict[str, Any] = {}
    for tf in ("5m", "1h", "4h"):
        for medida in QUEDA_MEDIDAS:
            label = tf_variant(tf, medida)
            for idade_label, (lo, hi) in IDADE_FAIXAS.items():
                prim = primary_under_window(ctx, period, label, lo, hi)
                for variant in ("A", "B"):
                    key = combo_key(tf, variant, medida, idade_label)
                    mine = [r for r in rows if r[1] == label and r[3] == variant and (r[0], r[1], r[2]) in prim]
                    sel = sorted((r for r in mine if r[4] == "fechado"), key=lambda r: json.loads(r[11]).get("entry_ts") or 0)
                    s = _stats(ctx, label, variant, sel, rows2)
                    s["status_dos_trades"] = {st: sum(1 for r in mine if r[4] == st) for st in sorted({r[4] for r in mine})}
                    if s["n"]:
                        info = [json.loads(r[11]) for r in sel]
                        # faixa de pico: o resultado COMPLETO por faixa (regra do operador)
                        bands: dict[str, list[tuple]] = {}
                        for i, r in zip(info, sel):
                            bands.setdefault(i.get("faixa_pico") or "?", []).append(r)
                        s["por_pico"] = {b: _stats(ctx, label, variant, bands[b], rows2) for b in BAND_ORDER if b in bands}
                        for name, ckey in CUTS:
                            groups: dict[str, list[float]] = {}
                            for i, r in zip(info, sel):
                                groups.setdefault(ckey(i, r), []).append(r[5])
                            s[name] = {g: summarize(v) for g, v in sorted(groups.items())}
                    out[key] = s
    return out


def choose_variant(table: dict[str, Any], min_trades: int = MIN_TRADES_DISCOVERY) -> tuple[Optional[str], dict[str, Any]]:
    """EMENDA 2026-10-16: maior EV liquido ENTRE as combinacoes com >= `min_trades` trades (o filtro de elegibilidade
    agora entra na escolha, nao so depois); empate -> combinacao primaria original (1h/A/extremos/2-7)."""
    scored = [(v["ev_liq_pct"], k) for k, v in table.items() if v.get("n", 0) >= min_trades]
    if not scored:
        return None, {}
    best = max(s for s, _ in scored)
    ties = [k for s, k in scored if abs(s - best) < 1e-9]
    pick = PRIMARY_COMBO if PRIMARY_COMBO in ties else sorted(ties)[0]
    return pick, table[pick]


def candidate(stats: dict[str, Any], min_trades: int = MIN_TRADES_DISCOVERY) -> dict[str, Any]:
    checks = {
        "ev_liquido_maior_que_0": (stats.get("ev_liq_pct") or 0) > 0,
        "pf_maior_que_1": (stats.get("pf") or 0) > 1,
        "edge_sobre_base_maior_que_0": (stats.get("edge_sobre_base_pct") or 0) > 0,
        f"pelo_menos_{min_trades}_trades": (stats.get("n") or 0) >= min_trades,
    }
    return {"criterios": checks, "candidato": all(checks.values())}


def holdout_verdict(stats: dict[str, Any], min_trades: int = MIN_TRADES_HOLDOUT) -> str:
    if (stats.get("n") or 0) < min_trades:
        return "INCONCLUSIVE"
    return "PASS" if (stats.get("ev_liq_pct") or 0) > 0 and (stats.get("pf") or 0) > 1 else "FAIL"
