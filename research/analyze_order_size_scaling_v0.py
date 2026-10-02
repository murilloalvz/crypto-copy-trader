"""Descriptive order-size scaling analysis on the consumed V1+V2 rows (read-only; no provider calls).

PAPER / RESEARCH / READ-ONLY. NOT a verdict and NOT a rule. It does NOT test other order sizes (all rows were
collected at USD 25); it only (1) projects, outcome-blind, how the KEPT share would change if price impact scales
linearly with order size, and (2) shows the catastrophic-loss dose-response against the USD 25 price impact.
Any alternative cap or size discovered here would need its own preregistration on fresh data.

Linear-scaling assumption: for a constant-product pool, impact ~ size / depth for small trades, so a cap of
`CAP` pp at size S corresponds to a cap of `CAP * 25 / S` pp measured at USD 25. This is an approximation and is
exactly what the order-size experiment is meant to check.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

import rejection_filter_holdout_v0_analyze as v0
import rejection_filter_holdout_v2_analyze as an2
from research import discover_kept_group_v0 as dk

CAP_PP = 2.0
BASE_NOTIONAL = 25.0
SIZES_USD = (5.0, 10.0, 20.0, 25.0, 30.0, 50.0, 100.0)
BINS = ((0.0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 25.0), (25.0, float("inf")))
ALT_CAPS_AT_25 = (1.0, 2.0, 3.0, 5.0, 10.0)
OUT_DEFAULT = Path("artifacts/order_size_scaling_v0")


def equivalent_cap_at_base(size_usd: float, cap_pp: float = CAP_PP) -> float:
    return cap_pp * BASE_NOTIONAL / size_usd


def projected_kept_share(abs_impacts: list[float], size_usd: float) -> float | None:
    """Outcome-blind share of episodes with projected |impact| <= cap at `size_usd` (linear scaling)."""
    if not abs_impacts:
        return None
    thr = equivalent_cap_at_base(size_usd)
    return 100.0 * sum(1 for x in abs_impacts if x <= thr) / len(abs_impacts)


def quantiles(vals: list[float], qs=(0.1, 0.25, 0.5, 0.75, 0.9)) -> dict[str, float]:
    s = sorted(vals)
    return {f"p{int(q * 100)}": s[min(len(s) - 1, int(q * len(s)))] for q in qs} if s else {}


def dose_response(pairs: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """pairs = (abs_impact_at_25, ret900). Half-open bins (lo, hi]; the first bin includes 0."""
    out = []
    for lo, hi in BINS:
        sel = [r for a, r in pairs if (a > lo or (lo == 0.0 and a >= 0.0)) and a <= hi]
        cat = sum(1 for r in sel if v0.is_catastrophic(r))
        out.append({"bin_pp": f"({lo:g}, {hi:g}]" if hi != float("inf") else f"> {lo:g}", "n": len(sel),
                    "catastrophic": cat, "cat_rate_pct": (100.0 * cat / len(sel)) if sel else None,
                    "median_ret900": median(sel) if sel else None})
    return out


def cap_table(pairs: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """Descriptive only: KEPT-group tail risk if the cap measured at USD 25 were X (NOT a recommendation)."""
    out = []
    for cap in ALT_CAPS_AT_25:
        kept = [r for a, r in pairs if a <= cap]
        rej = [r for a, r in pairs if a > cap]
        ck = sum(1 for r in kept if v0.is_catastrophic(r))
        cr = sum(1 for r in rej if v0.is_catastrophic(r))
        out.append({"cap_at_25_pp": cap, "kept_n": len(kept), "kept_cat_rate_pct": (100.0 * ck / len(kept)) if kept else None,
                    "rejected_n": len(rej), "rejected_cat_rate_pct": (100.0 * cr / len(rej)) if rej else None,
                    "kept_share_of_paired_pct": 100.0 * len(kept) / len(pairs) if pairs else None})
    return out


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: prepare_rows_v2 output with token_status already applied (dedup across V1+V2)."""
    ok = [r for r in rows if r["token_status"] == "OK" and not r["excluded_authority"]]
    with_impact = [(abs(float(r["impact"])), r) for r in ok if isinstance(r.get("impact"), (int, float))]
    all_abs = [a for a, _ in with_impact]
    pairs = [(a, r["ret900"]) for a, r in with_impact if r["ret900"] is not None]
    return {
        "episodes_deduped_with_impact": len(all_abs),
        "paired_with_900s_return": len(pairs),
        "abs_impact_at_25_quantiles": quantiles(all_abs),
        "projected_kept_share_by_size_outcome_blind": {
            f"${int(s)}": {"equivalent_cap_at_25_pp": equivalent_cap_at_base(s), "kept_share_pct": projected_kept_share(all_abs, s)}
            for s in SIZES_USD},
        "dose_response_vs_impact_at_25": dose_response(pairs),
        "cap_table_descriptive_only": cap_table(pairs),
    }


def render(res: dict[str, Any]) -> str:
    L = ["# Order-size scaling (V1+V2, consumed data; DESCRIPTIVE ONLY)", "",
         "**Todas as ordens foram a US$25; isto NÃO testa outros tamanhos. Projeção assume impacto linear no tamanho. "
         "Não é veredito nem regra; route-only != P&L; PAPER/RESEARCH/READ-ONLY.**", "",
         f"- Episódios (um por token) com impacto: {res['episodes_deduped_with_impact']}; com retorno de 900s no prazo: {res['paired_with_900s_return']}.",
         f"- |impacto| a US$25, quantis: {res['abs_impact_at_25_quantiles']}", "",
         "## 1. Fração MANTIDA projetada por tamanho (sem olhar retornos)", "",
         "| Tamanho | Corte equivalente a US$25 (pp) | % MANTIDO projetado |", "|---|---|---|"]
    for k, v in res["projected_kept_share_by_size_outcome_blind"].items():
        L.append(f"| {k} | {v['equivalent_cap_at_25_pp']:.2f} | {v['kept_share_pct']:.1f}% |" if v["kept_share_pct"] is not None
                 else f"| {k} | {v['equivalent_cap_at_25_pp']:.2f} | NA |")
    L += ["", "## 2. Perda catastrófica (<= -80% em 900s) por faixa de |impacto| a US$25 (descritivo)", "",
          "| Faixa (pp) | n | catastróficas | taxa | mediana 900s |", "|---|---|---|---|---|"]
    for b in res["dose_response_vs_impact_at_25"]:
        rate = "NA" if b["cat_rate_pct"] is None else f"{b['cat_rate_pct']:.1f}%"
        med = "NA" if b["median_ret900"] is None else f"{b['median_ret900']:+.1f}%"
        L.append(f"| {b['bin_pp']} | {b['n']} | {b['catastrophic']} | {rate} | {med} |")
    L += ["", "## 3. Se o corte (medido a US$25) fosse outro — SÓ descritivo, não é recomendação", "",
          "| Corte a US$25 (pp) | MANTIDO n | taxa MANTIDO | REJEITADO n | taxa REJEITADO | % MANTIDO |", "|---|---|---|---|---|---|"]
    f = lambda v: "NA" if v is None else f"{v:.1f}%"  # noqa: E731
    for c in res["cap_table_descriptive_only"]:
        L.append(f"| {c['cap_at_25_pp']:g} | {c['kept_n']} | {f(c['kept_cat_rate_pct'])} | {c['rejected_n']} | "
                 f"{f(c['rejected_cat_rate_pct'])} | {f(c['kept_share_of_paired_pct'])} |")
    L += ["", "Qualquer corte ou tamanho alternativo exige preregistro próprio em dados novos."]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    raw, integrity = dk.load_rows()
    if any(integrity.values()):
        raise SystemExit(f"Fail-closed, dataset integrity problems: {integrity}")
    rows = dk.prepare(raw)
    an2.apply_token_exclusions(rows, set())
    res = analyze(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "report.json").write_text(json.dumps(res, indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")
    text = render(res)
    (args.out_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
