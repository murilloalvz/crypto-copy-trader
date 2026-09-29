"""Descriptive bankroll simulation of human-style exit rules on the V55 cohort path export.

PAPER / RESEARCH / READ-ONLY. Route/market-path return != realized P&L. Not an edge claim, not a
verdict, not an armed exit policy. V55 discovery is burned for V68 validation; this only re-reads
persisted data under different exit rules. Offline: reads the JSON from export_v55_price_path_v0.

Model (all declared, none tuned on the data):
- Entry at decision_as_of at `ref_trade_price_usd` (last trade seen at/before it).
- Path = 5s buckets [end_offset, low, high, last] from market trades (no impact/fees).
  `--cost-pct` subtracts a flat round-trip cost from every trade (default 0).
- Inside a bucket the order of events is unknown: if SL and TP are both touched, SL wins.
  TP fills at the TP level; SL fills at min(SL level, bucket last) (gap-aware).
- Time exit uses the last bucket price <= hold; not evaluable if it is older than `--stale-seconds`.
- Sequential, non-overlapping positions: an episode whose decision_as_of is before the previous
  exit is skipped. Sizing/reinvestment reuses src.wave_bankroll.simulate_bankroll.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.wave_bankroll import WaveTradeReturn, simulate_bankroll

LABEL = "route-only/market-path, descritivo, PAPER/RESEARCH/READ-ONLY — não é P&L realizado nem edge validado"
LOW_CUTOFF = 57.1429  # frozen V55 LOW cutpoint (LOW <= 57.1429); used only if --features-csv given

# (name, tp_pct, sl_pct, hold_s). Fixed a priori.
CORE = {
    "curta": ("Curta: saída fixa 300s", None, None, 300),
    "longa": ("Longa: saída fixa 3600s", None, None, 3600),
    "inteligente": ("Inteligente: TP+100% / SL-30% / máx 3600s", 100.0, -30.0, 3600),
}
GRID_TP = (None, 50.0, 100.0, 200.0)
GRID_SL = (None, -20.0, -30.0, -50.0)
GRID_HOLD = (900, 3600)


def simulate_exit(ep, tp, sl, hold, stale):
    """Return (return_pct, exit_offset_s) or None if not evaluable."""
    p0 = ep.get("ref_trade_price_usd")
    buckets = ep.get("buckets") or []
    if not p0 or p0 <= 0 or not buckets:
        return None
    last_seen = None
    for end, low, high, last in buckets:
        if end > hold:
            break
        last_seen = (end, last)
        if sl is not None and low <= p0 * (1 + sl / 100.0):
            fill = min(p0 * (1 + sl / 100.0), last)
            return 100.0 * (fill / p0 - 1.0), end
        if tp is not None and high >= p0 * (1 + tp / 100.0):
            return tp, end
    if last_seen is None or hold - last_seen[0] > stale:
        return None
    return 100.0 * (last_seen[1] / p0 - 1.0), last_seen[0]


def run_rule(episodes, tp, sl, hold, *, stale, cost_pct, balance, allocation):
    trades, skipped_eval, skipped_overlap, busy_until = [], 0, 0, -1
    for ep in sorted(episodes, key=lambda e: (e["decision_as_of"], e["episode_key"])):
        if ep["decision_as_of"] < busy_until:
            skipped_overlap += 1
            continue
        res = simulate_exit(ep, tp, sl, hold, stale)
        if res is None:
            skipped_eval += 1
            continue
        ret, exit_offset = res
        busy_until = ep["decision_as_of"] + exit_offset
        trades.append(WaveTradeReturn(ep["decision_as_of"], ep["episode_key"][-8:], ret - cost_pct))
    if not trades:
        return None, skipped_eval, skipped_overlap
    sim = simulate_bankroll(trades, starting_balance_usd=balance, allocation_pct=allocation)
    return sim, skipped_eval, skipped_overlap


def row(name, sim, se, so):
    if sim is None:
        return {"hip": name, "final": None, "n": 0, "skip_eval": se, "skip_overlap": so}
    wins = sum(1 for p in sim.points if p.return_pct > 0)
    return {
        "hip": name, "final": sim.final_balance_usd, "pnl": sim.total_profit_usd,
        "ret": sim.total_return_pct, "dd": sim.max_drawdown_pct, "n": len(sim.points),
        "hit": 100.0 * wins / len(sim.points), "wins": wins, "skip_eval": se, "skip_overlap": so,
    }


def fmt(r):
    if r["final"] is None:
        return f"| {r['hip']} | — | — | — | — | — | 0 | {r['skip_eval']} | {r['skip_overlap']} |"
    return (f"| {r['hip']} | {r['final']:.2f} | {r['pnl']:+.2f} | {r['ret']:+.2f}% | "
            f"{r['dd']:.2f}% | {r['hit']:.1f}% | {r['n']} | {r['skip_eval']} | {r['skip_overlap']} |")


HEADER = ("| Hipótese | Banca final US$ | P&L US$ | Retorno | Max DD | Acerto | Trades | "
          "Não avaliáveis | Pulados (overlap) |\n|---|---|---|---|---|---|---|---|---|")


def aggregate(rows):
    live = [r for r in rows if r["final"] is not None]
    if not live:
        return None
    start = sum(r["final"] - r["pnl"] for r in live)
    n = sum(r["n"] for r in live)
    return {
        "hip": "AGREGADO (curta+longa+inteligente, 3 bancas paralelas somadas)",
        "final": sum(r["final"] for r in live), "pnl": sum(r["pnl"] for r in live),
        "ret": 100.0 * sum(r["pnl"] for r in live) / start,
        "dd": max(r["dd"] for r in live),  # worst individual DD; bancas não são combinadas
        "n": n, "hit": 100.0 * sum(r["wins"] for r in live) / n,
        "skip_eval": sum(r["skip_eval"] for r in live),
        "skip_overlap": sum(r["skip_overlap"] for r in live),
    }


def load_episodes(path: Path, features_csv: Path | None):
    data = json.loads(path.read_text(encoding="utf-8"))
    episodes = data["episodes"]
    dropped = 0
    if features_csv is not None:
        with features_csv.open(encoding="utf-8") as h:
            share = {r["episode_key"]: r["flow60_buy_share_pct"] for r in csv.DictReader(h)}
        kept = []
        for ep in episodes:
            v = share.get(ep["episode_key"], "")
            if v != "" and float(v) <= LOW_CUTOFF:
                kept.append(ep)
        dropped = len(episodes) - len(kept)
        episodes = kept
    return episodes, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path-json", type=Path, default=Path(__file__).with_name("v55_price_path.json"))
    ap.add_argument("--features-csv", type=Path, help="v55_cohort_export.csv (full mode) to apply the LOW proxy filter")
    ap.add_argument("--balance", type=float, default=100.0)
    ap.add_argument("--allocation-pct", type=float, default=30.0)
    ap.add_argument("--cost-pct", type=float, default=0.0)
    ap.add_argument("--stale-seconds", type=int, default=120)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("v55_exit_sim_table.md"))
    a = ap.parse_args(argv)

    episodes, dropped = load_episodes(a.path_json, a.features_csv)
    common = dict(stale=a.stale_seconds, cost_pct=a.cost_pct, balance=a.balance, allocation=a.allocation_pct)
    core_rows = []
    for key, (name, tp, sl, hold) in CORE.items():
        core_rows.append(row(name, *run_rule(episodes, tp, sl, hold, **common)))
    grid_rows = []
    for hold in GRID_HOLD:
        for tp in GRID_TP:
            for sl in GRID_SL:
                if tp is None and sl is None:
                    continue
                name = f"TP {'—' if tp is None else f'+{tp:.0f}%'} / SL {'—' if sl is None else f'{sl:.0f}%'} / máx {hold}s"
                grid_rows.append(row(name, *run_rule(episodes, tp, sl, hold, **common)))

    filt = "proxy LOW (flow60_buy_share_pct ≤ 57.1429; proxy, NÃO o TAKE/SKIP humano real)" if a.features_csv else "cohort inteiro (sem filtro de entrada)"
    lines = [
        f"# Simulação de saídas — cohort V55 discovery (burned p/ V68)", "",
        f"**{LABEL}**", "",
        f"- Cohort: V55 discovery A+B, `COMPLETE / CLEAN`, discovery-only; V68 = NOT_EVALUATED. Nada aqui é veredito.",
        f"- Entrada: {filt}; episódios usados: {len(episodes)} (excluídos pelo filtro: {dropped}).",
        f"- Banca US$ {a.balance:.0f}, alocação {a.allocation_pct:.0f}% por entrada, reinvestimento sequencial, sem sobrepor posições; custo round-trip {a.cost_pct}%.",
        "- Base de preço: trades de mercado persistidos (sem impacto/fees), não cotações de rota. Ordem dentro do bucket de 5s desconhecida: SL vence TP.",
        "", "## Hipóteses principais", "", HEADER, *[fmt(r) for r in core_rows],
    ]
    agg = aggregate(core_rows)
    if agg:
        lines.append(fmt(agg))
    lines += ["", "## Grade TP/SL (descritiva; não escolher 'melhor' — n pequeno, mesma amostra)", "", HEADER, *[fmt(r) for r in grid_rows], ""]
    text = "\n".join(lines)
    a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
