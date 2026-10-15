"""Metricas da Parte A por variante (tf x saida) — EV liquido, PF, acerto, R, sequencia de perdas, tempo no trade,
cortes por n de wicks, launchpad e faixa de pico, linha de base pareada e custo 2x. Escolha da variante e criterio.
"""

from __future__ import annotations

import json
import statistics
from typing import Any, Optional

from .baseline import baseline_mean
from .pipeline import Context

PEAK_BANDS = ((300_000, 1_000_000, "300k-1M"), (1_000_000, 5_000_000, "1-5M"), (5_000_000, float("inf"), ">5M"))
TF_HOURS = {"5m": 5 / 60, "1h": 1.0, "4h": 4.0}


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


def band(peak: Optional[float]) -> str:
    for lo, hi, name in PEAK_BANDS:
        if peak is not None and lo <= peak < hi:
            return name
    return "?"


def variant_table(ctx: Context, period: str) -> dict[str, Any]:
    rows = ctx.store.trades(period, "setup")
    rows2 = {(r[0], r[1], r[2], r[3]): r for r in ctx.store.trades(period, "setup_custo2x")}
    prim = {(p, tf, n) for p, tf, n, *_ in ctx.store.setups(period, primary_only=True)}
    out: dict[str, Any] = {}
    for tf in ("5m", "1h", "4h"):
        for variant in ("A", "B"):
            sel = sorted((r for r in rows if r[1] == tf and r[3] == variant and (r[0], r[1], r[2]) in prim and r[4] == "fechado"),
                         key=lambda r: json.loads(r[11]).get("entry_ts") or 0)
            rets = [r[5] for r in sel]
            info = [json.loads(r[11]) for r in sel]
            s = summarize(rets)
            if s["n"]:
                s["taxa_alvo_pct"] = 100 * sum(1 for r in sel if r[8]) / len(sel)
                rs = [r[7] for r in sel if r[7] is not None]
                s["R_medio"] = sum(rs) / len(rs) if rs else None
                s["R_mediano"] = statistics.median(rs) if rs else None
                s["tempo_medio_h"] = sum((r[9] or 0) * TF_HOURS[tf] for r in sel) / len(sel)
                cost2 = [rows2[(r[0], r[1], r[2], r[3])][5] for r in sel if (r[0], r[1], r[2], r[3]) in rows2 and rows2[(r[0], r[1], r[2], r[3])][4] == "fechado"]
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
                for name, key in (("por_wicks", lambda i, r: "3+" if i["n_wicks"] >= 3 else str(i["n_wicks"])),
                                  ("por_launchpad", lambda i, r: r[12]),
                                  ("por_pico", lambda i, r: band(i.get("P_peak_topo")))):
                    groups: dict[str, list[float]] = {}
                    for i, r in zip(info, sel):
                        groups.setdefault(key(i, r), []).append(r[5])
                    s[name] = {g: summarize(v) for g, v in sorted(groups.items())}
            out[f"{tf}/{variant}"] = s
    return out


def choose_variant(table: dict[str, Any]) -> tuple[Optional[str], dict[str, Any]]:
    """Maior EV liquido; empate -> 1h/A (handoff secao 4)."""
    scored = [(v["ev_liq_pct"], k) for k, v in table.items() if v.get("n")]
    if not scored:
        return None, {}
    best = max(s for s, _ in scored)
    ties = [k for s, k in scored if abs(s - best) < 1e-9]
    pick = "1h/A" if "1h/A" in ties else sorted(ties)[0]
    return pick, table[pick]


def candidate(stats: dict[str, Any], min_trades: int = 30) -> dict[str, Any]:
    checks = {
        "ev_liquido_maior_que_0": (stats.get("ev_liq_pct") or 0) > 0,
        "pf_maior_que_1": (stats.get("pf") or 0) > 1,
        "edge_sobre_base_maior_que_0": (stats.get("edge_sobre_base_pct") or 0) > 0,
        f"pelo_menos_{min_trades}_trades": (stats.get("n") or 0) >= min_trades,
    }
    return {"criterios": checks, "candidato": all(checks.values())}


def holdout_verdict(stats: dict[str, Any], min_trades: int = 20) -> str:
    if (stats.get("n") or 0) < min_trades:
        return "INCONCLUSIVE"
    return "PASS" if (stats.get("ev_liq_pct") or 0) > 0 and (stats.get("pf") or 0) > 1 else "FAIL"
