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
from .bankroll import write_bankroll_reports
from .metrics import CUTS, variant_table
from .pipeline import IDADE_FAIXAS, Context, load_bars, primary_under_window, real_tf

PRIMARY_TF = "1h"   # tf real da combinacao primaria original (1h/A/extremos/2-7)


def _pct(v: Any) -> str:
    return "—" if v is None else (f"{v:+.1f}%" if isinstance(v, (int, float)) else str(v))


def _num(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return "∞" if v == float("inf") else f"{v:.2f}"
    return str(v)


def _path(s: dict[str, Any]) -> str:
    c = s.get("caminho_max") or {}
    if not c.get("n"):
        return "—"
    return f"{c['mediana_pct']:.0f}% ({c['chegou_ao_topo_pct']:.0f}% no topo)"


def _variant_lines(table: dict[str, Any], label: str = "variante") -> list[str]:
    out = [f"| {label} | n | acerto | alvo antes do stop | EV líquido | mediana | PF | R médio | R mediano | pior seq. perdas | tempo médio | máx. no caminho até o pico (mediana) | base (EV) | edge sobre base | custo 2× (EV / PF) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in table.items():
        if not s.get("n"):
            out.append(f"| {k} | 0 | — | — | — | — | — | — | — | — | — | — | — | — | — |")
            continue
        c2 = s.get("custo_2x") or {}
        out.append(f"| {k} | {s['n']} | {s['acerto_pct']:.0f}% | {s['taxa_alvo_pct']:.0f}% | {_pct(s['ev_liq_pct'])} | {_pct(s['mediana_liq_pct'])} | "
                   f"{_num(s['pf'])} | {_num(s.get('R_medio'))} | {_num(s.get('R_mediano'))} | {s['pior_sequencia_perdas']} | "
                   f"{s['tempo_medio_h']:.1f} h | {_path(s)} | {_pct(s.get('base_ev_liq_pct'))} ({s.get('base_cobertura')}) | {_pct(s.get('edge_sobre_base_pct'))} | "
                   f"{_pct(c2.get('ev_liq_pct'))} / {_num(c2.get('pf'))} |")
    return out


def _cut_lines(st: dict[str, Any]) -> list[str]:
    """Resultado completo por faixa de pico + os cortes de atributo (nenhum deles e filtro)."""
    out: list[str] = []
    if st.get("por_pico"):
        out.append("Por faixa de pico do runner (resultado completo):")
        out.append("")
        out.extend(_variant_lines(st["por_pico"], "faixa"))
        out.append("")
    for name, _key in CUTS:
        if st.get(name):
            out.append(f"- {name}: " + "; ".join(f"{g}: n={v['n']}, EV {_pct(v.get('ev_liq_pct'))}, PF {_num(v.get('pf'))}"
                                               for g, v in st[name].items()))
    out.append("")
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
                 f"{ctx.params.runner_min_mc:,.0f}): {c['runners']} (sem data de criação on-chain: {c['runners_sem_criacao']} — "
                 f"sem idade, nenhum setup deles é primário); setups primários por tf: {c['setups_primarios']}; parada: {stop}")
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
        L.extend(_cut_lines(st))
    L.append("Cortes das 6 variantes (atributos; nenhum é filtro e nenhum muda a escolha):")
    L.append("")
    for k, st in table.items():
        if st.get("n"):
            L.append(f"**{k}**")
            L.append("")
            L.extend(_cut_lines(st))
    hold_path = out / "resultado_holdout.json"
    if hold_path.exists():
        h = json.loads(hold_path.read_text(encoding="utf-8"))
        L.append("## 3. Holdout selado")
        L.append("")
        s = h["estatisticas"]
        L.append(f"Variante {h['variante']}: **{h['veredito']}** — n={s.get('n')}, EV líquido {_pct(s.get('ev_liq_pct'))}, PF {_num(s.get('pf'))}, "
                 f"custo 2×: EV {_pct((s.get('custo_2x') or {}).get('ev_liq_pct'))}, PF {_num((s.get('custo_2x') or {}).get('pf'))}")
        L.append("")
        L.extend(_variant_lines({h["variante"]: s}))
        L.append("")
        L.extend(_cut_lines(s))
    # 5 trades sorteados do discovery (ganhos e perdas) com as fases marcadas -- da combinacao PRIMARIA original
    # (1h/A/extremos/2-7); as outras 23 da grade (emenda 2026-10-16) nao entram nesta amostra
    rows = [r for r in ctx.store.trades("discovery", "setup") if r[1] == PRIMARY_TF and r[3] == "A" and r[4] == "fechado"]
    prim = primary_under_window(ctx, "discovery", PRIMARY_TF, *IDADE_FAIXAS["2-7"])
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
        bars = load_bars(ctx, g, real_tf(r[1]))
        st1 = ctx.store.stage1(r[0])
        det = run(bars, ctx.params, real_tf(r[1]), st1[3], g["grad_ts"], st1[6])
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        ev = entries[r[2] - 1] if len(entries) >= r[2] else None
        if ev is None:
            continue
        lo = max(0, ev.data["peak_idx"] - 10)
        hi = min(len(bars) - 1, ev.idx + ctx.params.time_stop_candles + 5)
        name = f"trade_{k}_{r[0][:8]}_{r[1]}.png"
        chart = charts.plot_setup(out / name, bars, r[1], f"Trade {k}: {r[0][:8]}… {r[1]} — líquido A {_pct(100 * (r[5] or 0))}",
                                  f"{g['launchpad']} · saída: {r[10]}", st1[3], ev, det.events, (), (lo, hi))
        info = json.loads(r[11])
        L.append(f"### Trade {k} — `{r[0]}` ({g['launchpad']}, {r[1]}) — {_pct(100 * (r[5] or 0))} ({r[10]})")
        L.append("")
        L.append(f"Pico {ev.data['P_peak']:,.0f} ({ev.data['faixa_pico']}), queda {ev.data['queda_pct']:.0f}%, S {ev.data['S']:,.0f}, "
                 f"R {ev.data['R']:,.0f}, {ev.data['n_testes']} teste(s) de suporte, zona de {ev.data['box_len']} candles, "
                 f"idade {_num(ev.data['idade_dias'])} d; máxima antes da saída: {_pct(info.get('max_caminho_pct'))} do caminho até o pico.")
        L.append("")
        L.append(f"![trade {k}]({name})" if chart else "(gráfico indisponível: matplotlib não instalado)")
        L.append("")
    # addendum de relatorio (operador, 2026-10-16): tabela de trades + gestao de banca por ajuste, banca US$100,
    # posicao 5%, max 3 abertas, stop diario -10%/3 perdas, stop semanal -20% -- NAO muda regra nem escolha
    bankroll = write_bankroll_reports(ctx, out)
    L.append("## 5. Tabela de trades e gestão de banca (US$100, posição 5%, até 3 abertas, stop diário/semanal)")
    L.append("")
    L.append("Uma linha por entrada que o bot faria pelas regras congeladas, em ordem cronológica real; sinais "
              "bloqueados pela gestão de banca aparecem marcados (\"pulado: limite/stop diário/stop semanal\"). "
              "Taxas e slippage pelo tamanho real da posição (recalculadas; a escolha da variante usa o custo fixo "
              "de 0,15 SOL do handoff, inalterado). Só trades fechados; cancelado/em aberto ficam fora desta tabela "
              "ilustrativa (limitação documentada).")
    L.append("")
    L.append("| ajuste | nº trades | % com lucro | lucro líquido médio | banca final | maior queda |")
    L.append("|---|---|---|---|---|---|")
    for k, s in bankroll["resumo"].items():
        if not s["n_trades"]:
            L.append(f"| {k} | 0 | — | — | US$ {s['banca_final_usd']:.2f} | — |")
            continue
        L.append(f"| {k} | {s['n_trades']} | {s['pct_com_lucro']:.0f}% | {_pct(s['lucro_liq_medio_pct'])} | "
                 f"US$ {s['banca_final_usd']:.2f} | US$ {s['maior_queda_usd']:.2f} ({s['maior_queda_pct']:.0f}%) |")
    L.append("")
    L.append(f"CSV por ajuste em `trades/`; XLSX com todas as abas: `{Path(bankroll['arquivo_xlsx']).name}`"
              if bankroll.get("arquivo_xlsx") else "CSV por ajuste em `trades/` (XLSX não gerado: `openpyxl` não instalado).")
    L.append("")
    path = out / "relatorio_parte_a.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
