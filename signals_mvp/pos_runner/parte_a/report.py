"""Relatorio da Parte A em portugues simples: cobertura -> discovery (6 variantes + base pareada) -> escolha ->
holdout, com graficos de 5 trades sorteados (ganhos e perdas) para o operador conferir se o detector "ve" o padrao.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from ...util import iso_utc, utc_now
from .. import charts
from ..detector import run
from .metrics import variant_table
from .pipeline import Context, load_bars


def _pct(v: Any) -> str:
    return "—" if v is None else (f"{v:+.1f}%" if isinstance(v, (int, float)) else str(v))


def _num(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return "∞" if v == float("inf") else f"{v:.2f}"
    return str(v)


def _variant_lines(table: dict[str, Any]) -> list[str]:
    out = ["| variante | n | acerto | alvo antes do stop | EV líquido | mediana | PF | R médio | R mediano | pior seq. perdas | tempo médio | base (EV) | edge sobre base | custo 2× (EV / PF) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in table.items():
        if not s.get("n"):
            out.append(f"| {k} | 0 | — | — | — | — | — | — | — | — | — | — | — | — |")
            continue
        c2 = s.get("custo_2x") or {}
        out.append(f"| {k} | {s['n']} | {s['acerto_pct']:.0f}% | {s['taxa_alvo_pct']:.0f}% | {_pct(s['ev_liq_pct'])} | {_pct(s['mediana_liq_pct'])} | "
                   f"{_num(s['pf'])} | {_num(s.get('R_medio'))} | {_num(s.get('R_mediano'))} | {s['pior_sequencia_perdas']} | "
                   f"{s['tempo_medio_h']:.1f} h | {_pct(s.get('base_ev_liq_pct'))} ({s.get('base_cobertura')}) | {_pct(s.get('edge_sobre_base_pct'))} | "
                   f"{_pct(c2.get('ev_liq_pct'))} / {_num(c2.get('pf'))} |")
    return out


def write_report(ctx: Context, docs: Path) -> Path:
    out = Path(docs)
    out.mkdir(parents=True, exist_ok=True)
    L: list[str] = []
    periods = ctx.plan.periods()
    L.append("# POS-RUNNER-V0 — Parte A: backtest histórico sem viés")
    L.append("")
    L.append(f"Gerado em {iso_utc(utc_now())}. Config `{ctx.params.version}`, plano `{ctx.plan.version}`. Os 5 exemplos do "
             "professor estão fora de tudo. Candle é aproximação: a ordem dos preços dentro do candle é desconhecida "
             "(stop e alvo no mesmo candle contam como stop).")
    L.append("")
    L.append("## 1. Períodos e cobertura")
    L.append("")
    for k, (a, b) in periods.items():
        L.append(f"- {k}: graduações de {iso_utc(a)} a {iso_utc(b)}")
    for period in ("discovery", "holdout"):
        c = ctx.store.counts(period)
        stop = ctx.store.get(f"{period}:parada")
        L.append("")
        L.append(f"**{period}** — graduações enumeradas: {c['graduacoes']}; estágio 1: {c['estagio1']}; runners (MC ≥ "
                 f"{ctx.params.runner_min_mc:,.0f}): {c['runners']}; setups primários por tf: {c['setups_primarios']}; parada: {stop}")
        per_lp = ctx.store.db.execute("SELECT launchpad, COUNT(*) FROM graduations WHERE period=? GROUP BY launchpad", (period,)).fetchall()
        L.append(f"Graduações por launchpad: {dict(per_lp)}")
    L.append("")
    L.append("## 2. Discovery — as 6 variantes")
    L.append("")
    table = variant_table(ctx, "discovery")
    L.extend(_variant_lines(table))
    L.append("")
    choice_path = out / "escolha_discovery.json"
    if choice_path.exists():
        ch = json.loads(choice_path.read_text(encoding="utf-8"))
        L.append(f"Variante escolhida (maior EV líquido; empate → 1h/A): **{ch['variante']}** — critérios: {ch['criterios']} → "
                 f"candidato: **{'sim' if ch['candidato'] else 'não'}**")
        L.append("")
        st = table.get(ch["variante"] or "", {})
        for name in ("por_wicks", "por_launchpad", "por_pico"):
            if st.get(name):
                L.append(f"- {name}: " + "; ".join(f"{g}: n={v['n']}, EV {_pct(v.get('ev_liq_pct'))}, PF {_num(v.get('pf'))}" for g, v in st[name].items()))
        L.append("")
    hold_path = out / "resultado_holdout.json"
    if hold_path.exists():
        h = json.loads(hold_path.read_text(encoding="utf-8"))
        L.append("## 3. Holdout selado")
        L.append("")
        s = h["estatisticas"]
        L.append(f"Variante {h['variante']}: **{h['veredito']}** — n={s.get('n')}, EV líquido {_pct(s.get('ev_liq_pct'))}, PF {_num(s.get('pf'))}, "
                 f"custo 2×: EV {_pct((s.get('custo_2x') or {}).get('ev_liq_pct'))}, PF {_num((s.get('custo_2x') or {}).get('pf'))}")
        L.append("")
    # 5 trades sorteados do discovery (ganhos e perdas) com as fases marcadas
    rows = [r for r in ctx.store.trades("discovery", "setup") if r[3] == "A" and r[4] == "fechado"]
    prim = {(p, tf, n) for p, tf, n, *_ in ctx.store.setups("discovery", primary_only=True)}
    rows = [r for r in rows if (r[0], r[1], r[2]) in prim]
    rng = random.Random(f"{ctx.plan.seed}:relatorio")
    wins = [r for r in rows if (r[5] or 0) > 0]
    losses = [r for r in rows if (r[5] or 0) <= 0]
    rng.shuffle(wins)
    rng.shuffle(losses)
    picks = (wins[:2] + losses[:3]) if len(wins) >= 2 else (wins + losses)[:5]
    if len(picks) < 5:
        picks += [r for r in wins[2:] + losses[3:] if r not in picks][: 5 - len(picks)]
    if picks:
        L.append("## 4. Cinco trades sorteados (o detector vê o que o operador vê?)")
        L.append("")
    grads = {r["pool"]: r for r in ctx.store.graduations("discovery")}
    for k, r in enumerate(picks, start=1):
        g = grads.get(r[0])
        if g is None:
            continue
        bars = load_bars(ctx, g, r[1])
        det = run(bars, ctx.params, r[1], ctx.store.stage1(r[0])[3], g["grad_ts"])
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        ev = entries[r[2] - 1] if len(entries) >= r[2] else None
        if ev is None:
            continue
        lo = max(0, (ev.data.get("topo_idx") or ev.data["peak_idx"]) - 10)
        hi = min(len(bars) - 1, ev.idx + ctx.params.time_stop_candles + 5)
        name = f"trade_{k}_{r[0][:8]}_{r[1]}.png"
        charts.plot_setup(out / name, bars, r[1], f"Trade {k}: {r[0][:8]}… {r[1]} — líquido A {_pct(100 * (r[5] or 0))}",
                          f"{g['launchpad']} · saída: {r[10]}", ctx.store.stage1(r[0])[3], ev, det.events, (), (lo, hi))
        L.append(f"### Trade {k} — `{r[0]}` ({g['launchpad']}, {r[1]}) — {_pct(100 * (r[5] or 0))} ({r[10]})")
        L.append("")
        L.append(f"![trade {k}]({name})")
        L.append("")
    path = out / "relatorio_parte_a.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
