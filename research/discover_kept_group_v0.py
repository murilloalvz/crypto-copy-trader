"""Descriptive HYPOTHESIS-GENERATION over the KEPT group of the V1+V2 rejection-filter cohorts.

PAPER / RESEARCH / READ-ONLY. Plan: docs/kept-group-selection-discovery-v0-plan-2026-10-02.md (written before
any run). Not validation, not a verdict, not a trading rule; the rows are consumed. Route-only return != realized
P&L. Reads the owner's database (no provider calls).
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from statistics import NormalDist
from typing import Any

import rejection_filter_holdout_v0_analyze as v0
import rejection_filter_holdout_v1_collect as v1c
import rejection_filter_holdout_v2_analyze as an2

PERMUTATIONS = 20000
SEED = 20261002
MIN_COVERAGE_PCT = 80.0
ALPHA = 0.05
POWER_Z = 0.84  # 80% power
V1_KEYS = {f"G{i}": f"rejection-filter-v1-20260929-01-G{i}" for i in range(1, 5)}
V2_KEYS = {f"H{i}": f"rejection-filter-v2-20260930-01-H{i}" for i in range(1, 6)}
OUT_DEFAULT = Path("artifacts/kept_group_discovery_v0")


# ------------------------------------------------------------------ pure statistics
def ranks(xs: list[float]) -> list[float]:
    """Average ranks (ties share the mean rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return out


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(ranks(x), ranks(y))


def perm_p_two_sided(x: list[float], y: list[float], rng: random.Random, perms: int = PERMUTATIONS) -> tuple[float, float]:
    rx, ry = ranks(x), ranks(y)
    rho = pearson(rx, ry)
    hits = 0
    work = list(ry)
    for _ in range(perms):
        rng.shuffle(work)
        if abs(pearson(rx, work)) >= abs(rho) - 1e-12:
            hits += 1
    return rho, (hits + 1) / (perms + 1)


def min_detectable_rho(n: int, tests: int) -> float | None:
    """Approx. |rho| detectable with 80% power at the Bonferroni-adjusted two-sided alpha (Fisher z)."""
    if n <= 4 or tests <= 0:
        return None
    z_alpha = NormalDist().inv_cdf(1 - ALPHA / tests / 2)
    return math.tanh((z_alpha + POWER_Z) / math.sqrt(n - 3))


def _num(v: Any) -> float | str | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    return "cat"


# ------------------------------------------------------------------ discovery on prepared rows
def kept_sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """rows: prepare_rows_v2 output + 'features', 'study'. Token-dedup across pooled rows, then KEPT + on-time label."""
    an2.apply_token_exclusions(rows, set())
    return [r for r in rows if r["token_status"] == "OK" and r["group"] == "KEPT"
            and not r["excluded_authority"] and r["ret900"] is not None]


def feature_matrix(sample: list[dict[str, Any]]) -> tuple[dict[str, list[float | None]], list[tuple[str, str]]]:
    names: set[str] = set()
    for r in sample:
        names.update(r["features"])
    names.discard("entry_price_impact_pct_points")
    cols: dict[str, list[float | None]] = {}
    skipped: list[tuple[str, str]] = []
    for name in sorted(names | {"abs_entry_price_impact_pp"}):
        vals: list[Any] = []
        for r in sample:
            if name == "abs_entry_price_impact_pp":
                raw = _num(r["features"].get("entry_price_impact_pct_points"))
                vals.append(abs(raw) if isinstance(raw, float) else None)
            else:
                vals.append(_num(r["features"].get(name)))
        if any(v == "cat" for v in vals):
            skipped.append((name, "categorical/text"))
            continue
        known = [v for v in vals if v is not None]
        cov = 100.0 * len(known) / len(vals) if vals else 0.0
        if cov < MIN_COVERAGE_PCT:
            skipped.append((name, f"coverage {cov:.0f}% < {MIN_COVERAGE_PCT:.0f}%"))
            continue
        if len(set(known)) < 2:
            skipped.append((name, "no variation"))
            continue
        cols[name] = vals
    return cols, skipped


def _rho_subset(vals, y, idx):
    pairs = [(vals[i], y[i]) for i in idx if vals[i] is not None and y[i] is not None]
    if len(pairs) < 8 or len({p[0] for p in pairs}) < 2 or len({p[1] for p in pairs}) < 2:
        return None
    return spearman([p[0] for p in pairs], [p[1] for p in pairs])


def discover(sample: list[dict[str, Any]]) -> dict[str, Any]:
    cols, skipped = feature_matrix(sample)
    y900 = [r["ret900"] for r in sample]
    y300 = [r["labels"].get(300) for r in sample]
    study = [r["study"] for r in sample]
    rng = random.Random(SEED)
    out = []
    for name, vals in cols.items():
        idx = [i for i, v in enumerate(vals) if v is not None]
        x = [vals[i] for i in idx]
        rho, p = perm_p_two_sided(x, [y900[i] for i in idx], rng)
        out.append({
            "feature": name, "n": len(idx), "rho_900": rho, "p_perm": p,
            "rho_300": _rho_subset(vals, y300, range(len(sample))),
            "rho_v1": _rho_subset(vals, y900, [i for i, s in enumerate(study) if s == "V1"]),
            "rho_v2": _rho_subset(vals, y900, [i for i, s in enumerate(study) if s == "V2"]),
        })
    m = len(out)
    for r in out:
        r["p_bonferroni"] = min(1.0, r["p_perm"] * m)
        signs = [r["rho_900"], r["rho_v1"], r["rho_v2"], r["rho_300"]]
        r["sign_agreement"] = all(s is not None and s != 0 for s in signs) and len({s > 0 for s in signs}) == 1
        r["robust_candidate"] = bool(r["p_bonferroni"] < ALPHA and r["sign_agreement"])
    out.sort(key=lambda r: r["feature"])  # alphabetical: nothing is ranked by effect size
    rets = [r for r in y900 if r is not None]
    return {
        "n_kept_paired": len(sample), "tests": m, "features": out, "skipped": skipped,
        "min_detectable_abs_rho_80pct_power": min_detectable_rho(len(sample), m),
        "baseline_900s": v0.dist_metrics(rets),
        "baseline_winners_ge_100": sum(1 for v in rets if v >= 100.0),
        "baseline_catastrophic": sum(1 for v in rets if v0.is_catastrophic(v)),
        "by_study": dict(Counter(study)),
        "robust_candidates": [r["feature"] for r in out if r["robust_candidate"]],
    }


# ------------------------------------------------------------------ loading
def load_rows() -> tuple[list[dict[str, Any]], dict[str, int]]:
    from src.opportunity_route_research_store import load_route_research_outcomes
    from src.route_research_early_opportunity_v55 import build_early_opportunity_dataset_v55

    keys = {**{l: (k, "V1") for l, k in V1_KEYS.items()}, **{l: (k, "V2") for l, k in V2_KEYS.items()}}
    run_keys = tuple(k for k, _ in keys.values())
    ds = build_early_opportunity_dataset_v55(acquisition_run_keys=run_keys)
    by_key = {k: (label, study) for label, (k, study) in keys.items()}
    o900: dict[tuple[str, str], str] = {}
    for rk in run_keys:
        for o in load_route_research_outcomes(acquisition_run_key=rk):
            if o.horizon_seconds == 900:
                o900[(rk, o.episode_key)] = v1c.classify_outcome(o.status, o.error_type, o.error_message,
                                                                 o.target_at, o.observed_at)
    raw = []
    for r in ds.rows:
        label, study = by_key[r.acquisition_run_key]
        raw.append({"cohort": label, "episode_key": r.episode_key, "token": r.token_mint,
                    "as_of": r.research_decision_as_of, "impact": r.features.get("entry_price_impact_pct_points"),
                    "mint_auth": r.features.get("hazard_mint_authority_present"),
                    "freeze_auth": r.features.get("hazard_freeze_authority_present"),
                    "labels": r.labels, "statuses": r.outcome_statuses,
                    "o900": o900.get((r.acquisition_run_key, r.episode_key), "TECHNICAL"),
                    "features": dict(r.features), "study": study})
    base = ds.base
    integrity = {"lineage_violations": base.lineage_violations, "missing_decisions": base.missing_decisions,
                 "missing_episodes": base.missing_episodes, "missing_hazard_attempts": base.missing_hazard_attempts,
                 "missing_entry_quotes": base.missing_entry_quotes,
                 "official_decision_mutations": base.official_decision_mutations,
                 "augmentation_failures": ds.augmentation_failures,
                 "feature_clock_violations": ds.feature_clock_violations}
    return raw, integrity


def prepare(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = an2.prepare_rows_v2(raw)
    for row, r in zip(rows, raw):
        row["features"], row["study"], row["impact"] = r["features"], r["study"], r["impact"]
    return rows


def render(result: dict[str, Any]) -> str:
    f = lambda v: "NA" if v is None else f"{v:+.2f}"  # noqa: E731
    base = result["baseline_900s"]
    L = [
        "# KEPT-group descriptive discovery V0 (HYPOTHESIS GENERATION ONLY)", "",
        "**Hipótese-geração em amostra consumida; route-only != P&L; PAPER/RESEARCH/READ-ONLY. Não é validação, veredito nem regra.**", "",
        f"- Amostra: {result['n_kept_paired']} episódios KEPT com retorno de 900s no prazo (por estudo: {result['by_study']}); um por token.",
        f"- Linha de base 900s: mediana {base.get('median')}, mean-without-best {base.get('mean_without_best')}, "
        f"PF {base.get('profit_factor')}; vencedores >= +100%: {result['baseline_winners_ge_100']}; catastróficos: {result['baseline_catastrophic']}.",
        f"- {result['tests']} features testadas (todas listadas em ordem alfabética); Bonferroni sobre esse número; {PERMUTATIONS} permutações, seed {SEED}.",
        f"- |rho| mínimo detectável (80% de poder, nível Bonferroni): {result['min_detectable_abs_rho_80pct_power']:.2f}"
        if result["min_detectable_abs_rho_80pct_power"] else "- |rho| mínimo detectável: NA", "",
        "| Feature | n | rho 900s | p perm | p Bonferroni | rho V1 | rho V2 | rho 300s | sinais concordam |", "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in result["features"]:
        L.append(f"| {r['feature']} | {r['n']} | {f(r['rho_900'])} | {r['p_perm']:.3f} | {r['p_bonferroni']:.3f} | "
                 f"{f(r['rho_v1'])} | {f(r['rho_v2'])} | {f(r['rho_300'])} | {'sim' if r['sign_agreement'] else 'não'} |")
    cands = result["robust_candidates"]
    L += ["", f"**Candidatas robustas (p Bonferroni < 0,05 e sinais concordando entre V1, V2 e 300s): {', '.join(cands) if cands else 'nenhuma'}**", "",
          "Ignoradas: " + ("; ".join(f"{n} ({w})" for n, w in result["skipped"]) or "nenhuma"), "",
          "Candidata = 'vale preregistrar', nada além. Nenhuma saída daqui pode confirmar a própria hipótese."]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    raw, integrity = load_rows()
    if any(integrity.values()):
        raise SystemExit(f"Fail-closed, dataset integrity problems: {integrity}")
    sample = kept_sample(prepare(raw))
    result = discover(sample)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")
    text = render(result)
    (args.out_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
