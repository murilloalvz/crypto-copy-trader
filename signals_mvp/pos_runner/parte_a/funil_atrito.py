"""DIAGNOSTICO (proposto, NAO aplicado ao pipeline): funil de atrito do detector sobre os runners ja no
checkpoint -- SOMENTE LEITURA, sem rede por padrao (os eventos de fase RUNNER/FASE2/WATCHLIST/TESTE/
ONDA_INVALIDA nunca sao persistidos em `setups` -- so ENTRADA e; por isso este funil precisa RE-RODAR
`detector.run` sobre os candles JA CACHEADOS em disco, nunca novo download). Nenhuma regra/limiar e alterado.

Uso (no PC do operador, dentro do venv, na raiz do repo):
    python funil_atrito.py --periodo discovery --tf 1h
    python funil_atrito.py --periodo discovery --tf 1h --launchpad pumpfun
    python funil_atrito.py --periodo discovery --tf 1h --max 50          # amostra rapida
    python funil_atrito.py --periodo discovery --tf 1h --permitir-rede  # so se quiser completar buracos de cache
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

def _find_repo() -> Path:
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        p = base
        for _ in range(6):
            if (p / "signals_mvp").is_dir():
                return p
            p = p.parent
    raise SystemExit("nao achei a raiz do repo (pasta com signals_mvp/) -- rode com --repo <caminho> ou de dentro do repo")


_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--repo", default=None)
_known, _ = _pre.parse_known_args()
REPO = Path(_known.repo) if _known.repo else _find_repo()
sys.path.insert(0, str(REPO))

from signals_mvp.pos_runner.parte_a.cli import DOCS, WORK  # noqa: E402
from signals_mvp.pos_runner.parte_a.pipeline import Context, QUEDA_MEDIDAS, load_bars, params_for_medida  # noqa: E402
from signals_mvp.pos_runner.parte_a.plan import load_plan  # noqa: E402
from signals_mvp.pos_runner.parte_a.quotebook import QuoteBook  # noqa: E402
from signals_mvp.pos_runner.parte_a.store import Store  # noqa: E402
from signals_mvp.pos_runner.candles import OhlcvStore  # noqa: E402
from signals_mvp.pos_runner.detector import run as detector_run  # noqa: E402
from signals_mvp.pos_runner.params import load_params  # noqa: E402


class NetworkDisabled(Exception):
    pass


class HttpStub:
    headers: dict = {}

    def get_json(self, *a, **k):
        raise NetworkDisabled(f"chamada de rede bloqueada (use --permitir-rede se quiser completar buracos): {a!r}")


def quantiles(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {}
    s = sorted(vals)
    return {"min": s[0], "p25": statistics.quantiles(s, n=4)[0] if len(s) >= 4 else s[0],
            "mediana": statistics.median(s), "p90": s[int(0.9 * (len(s) - 1))], "max": s[-1], "n": len(s)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="raiz do repo (pasta com signals_mvp/); auto-detectado se omitido")
    ap.add_argument("--periodo", default="discovery", choices=["discovery", "holdout"])
    ap.add_argument("--tf", default="1h", choices=["5m", "1h", "4h"])
    ap.add_argument("--launchpad", default=None)
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--permitir-rede", action="store_true")
    ap.add_argument("--db", default=None, help="checkpoint sqlite (padrao: o da coleta real)")
    ap.add_argument("--cache", default=None, help="pasta de cache de candles (padrao: a da coleta real)")
    args = ap.parse_args()

    plan = load_plan(DOCS / "plano_parte_a.json")
    params = load_params()
    store = Store(Path(args.db) if args.db else WORK / "parte_a.sqlite")

    if args.permitir_rede:
        from signals_mvp.http import HttpClient, RateLimiter
        http = HttpClient("https://api.geckoterminal.com/api/v2", RateLimiter(26, 2, jitter_s=1.5), 30, name="GeckoTerminal")
    else:
        http = HttpStub()
    cache_dir = Path(args.cache) if args.cache else WORK / "ohlcv"
    ohlcv = OhlcvStore(http, cache_dir)
    quotes = QuoteBook(ohlcv, cache_dir.parent / "referencias_cotacao.json")
    ctx = Context(plan, params, store, ohlcv, quotes, lambda *a: None, lambda m: None, lambda m, s: None)

    q = ("SELECT g.pool, g.launchpad, g.quote, g.grad_ts, g.signature, s.l_bc, s.max_mc, s.created_ts "
        "FROM stage1 s JOIN graduations g ON g.pool=s.pool WHERE g.period=? AND s.runner=1 AND s.status='ok'")
    args_sql = [args.periodo]
    if args.launchpad:
        q += " AND g.launchpad=?"
        args_sql.append(args.launchpad)
    if args.max:
        q += f" LIMIT {int(args.max)}"
    rows = store.db.execute(q, args_sql).fetchall()
    print(f"{len(rows)} runners (periodo={args.periodo}, status=ok) -- tf={args.tf}\n")

    peaks: dict[str, list[float]] = {}
    l_bc_nulo = l_bc_zero = 0
    funil = {"stage2_nao_ok": 0, "sem_bars": 0, "zona_extremos": 0, "zona_fecham": 0, "armado_extremos": 0,
             "armado_fecham": 0, "teste_extremos": 0, "teste_fecham": 0, "entrada_extremos": 0, "entrada_fecham": 0,
             "entrada_na_janela_extremos": 0, "entrada_na_janela_fecham": 0, "primaria_extremos": 0, "primaria_fecham": 0}
    por_lp: dict[str, dict] = {}
    idades_raw: list[float] = []
    erros_rede_bloqueada = 0

    for r in rows:
        pool, lp, quote, grad_ts, sig, l_bc, max_mc, created_ts = r
        peaks.setdefault(lp, []).append(max_mc)
        if l_bc is None:
            l_bc_nulo += 1
        elif l_bc == 0:
            l_bc_zero += 1
        slot = por_lp.setdefault(lp, dict(funil))
        s2 = store.stage2(pool, args.tf)
        if s2 is None or s2[0] != "ok":
            funil["stage2_nao_ok"] += 1
            slot["stage2_nao_ok"] += 1
            continue
        row = {"pool": pool, "quote": quote, "period": args.periodo, "grad_ts": grad_ts}
        try:
            bars = load_bars(ctx, row, args.tf, {})
        except NetworkDisabled:
            erros_rede_bloqueada += 1
            continue
        if not bars:
            funil["sem_bars"] += 1
            slot["sem_bars"] += 1
            continue
        for medida, suf in (("extremos", "extremos"), ("fechamentos", "fecham")):
            p = params_for_medida(ctx.params, medida)
            det = detector_run(bars, p, args.tf, l_bc, grad_ts, created_ts)
            kinds = [e.kind for e in det.events]
            if "FASE2" in kinds:
                funil[f"zona_{suf}"] += 1
                slot[f"zona_{suf}"] += 1
            if "WATCHLIST" in kinds:
                funil[f"armado_{suf}"] += 1
                slot[f"armado_{suf}"] += 1
            if "TESTE" in kinds:
                funil[f"teste_{suf}"] += 1
                slot[f"teste_{suf}"] += 1
            entradas = [e for e in det.events if e.kind == "ENTRADA"]
            if entradas:
                funil[f"entrada_{suf}"] += 1
                slot[f"entrada_{suf}"] += 1
                for e in entradas:
                    if e.data.get("idade_dias") is not None:
                        idades_raw.append(e.data["idade_dias"])
                if any(e.data.get("na_janela") for e in entradas):
                    funil[f"entrada_na_janela_{suf}"] += 1
                    slot[f"entrada_na_janela_{suf}"] += 1
                if any(e.data.get("primario") for e in entradas):
                    funil[f"primaria_{suf}"] += 1
                    slot[f"primaria_{suf}"] += 1

    print("FUNIL TOTAL (runners com stage2 ok neste tf):")
    for k, v in funil.items():
        print(f"  {k:28} {v}")
    if erros_rede_bloqueada:
        print(f"  (AVISO: {erros_rede_bloqueada} pool(s) pulados -- buraco de cache, rede bloqueada por padrao)")

    print("\nPOR LAUNCHPAD:")
    for lp, slot in por_lp.items():
        print(f" {lp}:", {k: v for k, v in slot.items() if v})

    print("\nP_peak (max_mc, runners) por launchpad:")
    for lp, vals in peaks.items():
        print(f" {lp}: {quantiles(vals)}")

    print(f"\nL_bc nulo: {l_bc_nulo} | L_bc == 0: {l_bc_zero} (de {len(rows)} runners)")

    print(f"\nidade_dias das ENTRADAS brutas (qualquer idade, n={len(idades_raw)}):")
    print(" ", quantiles(idades_raw))
    dentro = sum(1 for a in idades_raw if 2.0 <= a <= 7.0)
    print(f"  dentro de [2,7]: {dentro} ({100*dentro/len(idades_raw):.1f}%)" if idades_raw else "  (nenhuma entrada bruta)")

    store.close()


if __name__ == "__main__":
    main()
