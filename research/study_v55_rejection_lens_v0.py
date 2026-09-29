"""Descriptive HYPOTHESIS-GENERATION study on the burned V55 discovery rows.

PAPER / RESEARCH / READ-ONLY. NOT validation, NOT a verdict, NOT a selector, and it does not
re-open V48/V55/V68/Participant Quality. Consumed data can only suggest a future, separately
preregistered hypothesis that needs fresh independent evidence.

Question: which persisted causal features separate CATASTROPHIC route-only outcomes
(<= -80% at 900s, the repo's tail definition) from the rest? Every feature with enough coverage is
reported, sorted alphabetically (no cherry-picking), with permutation p-values and a Bonferroni
correction over the number of features tested. Expect little or nothing to survive at n~62.

Input: research/v55_cohort_export.csv from `export_v55_cohort_v0` (full mode).
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

CATASTROPHIC_PCT = -80.0
MIN_COVERAGE_PCT = 80.0
PERMUTATIONS = 20000
SEED = 20260929
BASE_COLS = {
    "episode_key", "cohort", "decision_as_of",
    *(f"return_pct_{h}s" for h in (300, 900, 3600)),
    *(f"status_{h}s" for h in (300, 900, 3600)),
}
LABEL = "hipótese-geração descritiva em amostra burned; route-only != P&L; PAPER/RESEARCH/READ-ONLY"


def _num(v):
    if v == "":
        return None
    if v in ("True", "true"):
        return 1.0
    if v in ("False", "false"):
        return 0.0
    try:
        return float(v)
    except ValueError:
        return "cat"


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x, y):
    rx, ry = _rank(x), _rank(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def perm_p(x, y, rho, rng):
    hits = 0
    yy = list(y)
    for _ in range(PERMUTATIONS):
        rng.shuffle(yy)
        if abs(spearman(x, yy)) >= abs(rho) - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def tertile_cat_rates(x, cat):
    order = sorted(range(len(x)), key=lambda i: x[i])
    k = len(order) // 3
    low, high = order[:k], order[-k:]
    rate = lambda idx: 100.0 * sum(cat[i] for i in idx) / len(idx) if idx else None
    return rate(low), rate(high), len(low)


def study(rows):
    usable = [r for r in rows if r.get("return_pct_900s", "") != ""]
    y = [float(r["return_pct_900s"]) for r in usable]
    cat = [1 if v <= CATASTROPHIC_PCT else 0 for v in y]
    feats = sorted(k for k in (rows[0].keys() if rows else []) if k not in BASE_COLS)
    rng = random.Random(SEED)
    out, skipped = [], []
    for f in feats:
        vals = [_num(r[f]) for r in usable]
        if any(v == "cat" for v in vals):
            skipped.append((f, "categórica/texto"))
            continue
        known = [i for i, v in enumerate(vals) if v is not None]
        cov = 100.0 * len(known) / len(usable) if usable else 0.0
        if cov < MIN_COVERAGE_PCT:
            skipped.append((f, f"cobertura {cov:.0f}% < {MIN_COVERAGE_PCT:.0f}%"))
            continue
        x = [vals[i] for i in known]
        if len(set(x)) < 2:
            skipped.append((f, "sem variação"))
            continue
        yk = [y[i] for i in known]
        ck = [cat[i] for i in known]
        rho = spearman(x, yk)
        p = perm_p(x, yk, rho, rng)
        lo, hi, k = tertile_cat_rates(x, ck)
        out.append({"feature": f, "n": len(known), "cov": cov, "rho": rho, "p": p,
                    "cat_low": lo, "cat_high": hi, "k": k})
    m = len(out)
    for r in out:
        r["p_adj"] = min(1.0, r["p"] * m)
    return usable, sum(cat), out, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", type=Path, default=Path(__file__).with_name("v55_cohort_export.csv"))
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("v55_rejection_lens.md"))
    a = ap.parse_args(argv)
    with a.csv.open(encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    usable, ncat, res, skipped = study(rows)
    L = [
        "# Estudo descritivo — o que separa perda catastrófica no V55 (burned)", "",
        f"**{LABEL}**", "",
        f"- Amostra: {len(usable)} episódios com retorno em 900s; catastróficos (≤ {CATASTROPHIC_PCT:.0f}%): {ncat} ({100*ncat/max(1,len(usable)):.0f}%).",
        f"- {len(res)} features testadas (todas listadas, ordem alfabética); Bonferroni sobre esse número; {PERMUTATIONS} permutações, seed {SEED}.",
        "- Não é regra de entrada nem veredito; V55 é burned p/ validação. Achados só sugerem hipótese p/ coleta fresca preregistrada.", "",
        "| Feature | n | rho (feat×ret900) | p perm | p ajust. | % catastrófico tercil baixo | tercil alto |", "|---|---|---|---|---|---|---|",
    ]
    for r in res:
        L.append(f"| {r['feature']} | {r['n']} | {r['rho']:+.2f} | {r['p']:.3f} | {r['p_adj']:.3f} | "
                 f"{r['cat_low']:.0f}% | {r['cat_high']:.0f}% |")
    surv = [r["feature"] for r in res if r["p_adj"] < 0.05]
    L += ["", f"**Sobrevivem à correção (p ajust. < 0,05): {', '.join(surv) if surv else 'nenhuma'}**", "",
          "Ignoradas: " + ("; ".join(f"{f} ({why})" for f, why in skipped) or "nenhuma")]
    text = "\n".join(L)
    a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
