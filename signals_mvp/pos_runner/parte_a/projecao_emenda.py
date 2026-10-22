"""DRY-RUN (proposto; NAO escreve no SQLite; NAO altera stage1/Params real): simula as 3 regras de qualidade
de dado propostas em docs/pos-runner-v0/EMENDA_QUALIDADE_DADOS_PROPOSTA.md (dado_invalido por wick/L_bc,
runner por fechamento, L_bc robusto) sobre os pools JA processados do checkpoint, le so os candles ja
cacheados em disco (zero chamada de rede), e projeta pro discovery/holdout inteiros usando as contagens reais
de `graduations` + a taxa de setups primarios 1h ja medida. Nenhuma linha do banco e alterada.

Uso (Windows, raiz do repo, venv ativo):
    python projecao_emenda.py --repo . --periodo discovery
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _find_repo() -> Path:
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        p = base
        for _ in range(6):
            if (p / "signals_mvp").is_dir():
                return p
            p = p.parent
    raise SystemExit("nao achei a raiz do repo -- rode com --repo <caminho> ou de dentro do repo")


_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--repo", default=None)
_known, _ = _pre.parse_known_args()
REPO = Path(_known.repo) if _known.repo else _find_repo()
sys.path.insert(0, str(REPO))

from signals_mvp.pos_runner.parte_a.cli import DOCS, WORK  # noqa: E402
from signals_mvp.pos_runner.parte_a.pipeline import Context, load_bars  # noqa: E402
from signals_mvp.pos_runner.parte_a.plan import load_plan  # noqa: E402
from signals_mvp.pos_runner.parte_a.quotebook import QuoteBook  # noqa: E402
from signals_mvp.pos_runner.parte_a.store import Store  # noqa: E402
from signals_mvp.pos_runner.candles import OhlcvStore  # noqa: E402
from signals_mvp.pos_runner.params import load_params  # noqa: E402

# EMENDA proposta (NAO aplicada aos Params reais) -- limiares candidatos, so para este dry-run. Ver
# docs/pos-runner-v0/EMENDA_QUALIDADE_DADOS_PROPOSTA.md para a justificativa de cada um.
CANDLE_WICK_RATIO_MAX = 3.0    # 1o candle real: high/close >= isto = dado_invalido (qualidade, nunca economico)
L_BC_FLOOR_USD = 100.0         # L_bc (robusto) < isto = dado_invalido (precisao/pool morto)

# holdout selado (docs/pos-runner-v0/holdout_selado.json, 2026-10-19): fixo, nao depende do checkpoint do
# operador -- so pra projetar o holdout ANTES dele ser processado.
HOLDOUT_GRADUACOES = {"pumpfun": 9075, "meteora_dbc": 17861, "raydium_launchlab": 413}


class HttpStub:
    """So leitura de cache local -- qualquer tentativa de rede e um erro explicito, nunca silencioso."""
    headers: dict = {}

    def get_json(self, *a, **k):
        raise RuntimeError(f"dry-run nao deveria chamar rede: {a!r}")


def avalia(bars) -> dict:
    """Recomputa, a partir dos MESMOS candles MC ja cacheados (nenhuma chamada nova), as 3 regras propostas."""
    first = bars[0]
    wick_ratio_1o = (first.high / first.close) if first.close else float("inf")
    l_bc_antigo = first.open
    l_bc_novo = min(first.open, first.close, bars[1].open if len(bars) > 1 else float("inf"))
    max_mc_high = max(b.high for b in bars)
    max_mc_close = max(b.close for b in bars)
    dado_invalido = wick_ratio_1o >= CANDLE_WICK_RATIO_MAX or l_bc_novo < L_BC_FLOOR_USD
    return {
        "wick_ratio_1o": wick_ratio_1o, "l_bc_antigo": l_bc_antigo, "l_bc_novo": l_bc_novo,
        "max_mc_high": max_mc_high, "max_mc_close": max_mc_close, "dado_invalido": dado_invalido,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--periodo", default="discovery", choices=["discovery", "holdout"])
    ap.add_argument("--tf", default="1h", choices=["5m", "1h", "4h"])
    ap.add_argument("--runner-min-mc", type=float, default=None, help="padrao: o da config real (ctx.params)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--cache", default=None)
    args = ap.parse_args()

    plan = load_plan(DOCS / "plano_parte_a.json")
    params = load_params()
    db_path = Path(args.db) if args.db else WORK / "parte_a.sqlite"
    store = Store(db_path)
    cache_dir = Path(args.cache) if args.cache else WORK / "ohlcv"
    ohlcv = OhlcvStore(HttpStub(), cache_dir)
    quotes = QuoteBook(ohlcv, cache_dir.parent / "referencias_cotacao.json")
    ctx = Context(plan, params, store, ohlcv, quotes, lambda *a: None, lambda m: None, lambda m, s: None)
    runner_min_mc = args.runner_min_mc or ctx.params.runner_min_mc

    store.db.row_factory = sqlite3.Row
    q = ("SELECT g.pool, g.mint, g.quote, g.grad_ts, g.launchpad, s.max_mc, s.l_bc, s.runner "
        "FROM stage1 s JOIN graduations g ON g.pool=s.pool WHERE g.period=? AND s.status='ok'")
    processados = store.db.execute(q, (args.periodo,)).fetchall()
    total_grads = dict(store.db.execute(
        "SELECT launchpad, COUNT(*) FROM graduations WHERE period=? GROUP BY launchpad", (args.periodo,)).fetchall())
    # setups primarios 1h JA medidos (regra antiga) -- usado so como taxa empirica de referencia na projecao.
    setups_1h_por_lp = dict(store.db.execute(
        "SELECT g.launchpad, COUNT(*) FROM setups st JOIN graduations g ON g.pool=st.pool "
        "WHERE g.period=? AND st.tf='1h' AND st.primary_flag=1 GROUP BY g.launchpad", (args.periodo,)).fetchall())
    store.db.row_factory = None

    agregados: dict[str, dict] = {}
    sem_cache = 0
    for row in processados:
        lp = row["launchpad"]
        agg = agregados.setdefault(lp, {"processados": 0, "sem_cache": 0, "dado_invalido": 0,
                                        "runner_antigo": 0, "runner_novo_e_valido": 0, "valido_nao_runner": 0})
        agg["processados"] += 1
        bars_dict = {"pool": row["pool"], "quote": row["quote"], "period": args.periodo, "grad_ts": row["grad_ts"]}
        try:
            bars = load_bars(ctx, bars_dict, args.tf, {})
        except Exception:
            bars = []
        if not bars:
            agg["sem_cache"] += 1
            sem_cache += 1
            continue
        r = avalia(bars)
        if bool(row["runner"]):
            agg["runner_antigo"] += 1
        if r["dado_invalido"]:
            agg["dado_invalido"] += 1
            continue
        if r["max_mc_close"] >= runner_min_mc:
            agg["runner_novo_e_valido"] += 1
        else:
            agg["valido_nao_runner"] += 1

    print(f"Periodo: {args.periodo} | tf avaliado: {args.tf} | runner_min_mc: {runner_min_mc:,.0f}")
    print(f"Limiares propostos (dry-run, NAO aplicados): wick_ratio_max={CANDLE_WICK_RATIO_MAX}, "
         f"l_bc_floor_usd={L_BC_FLOOR_USD}\n")

    header = (f"{'launchpad':18} {'grads_totais':>12} {'processados':>12} {'sem_cache':>9} "
             f"{'dado_invalido':>13} {'runner_ANTIGO':>13} {'runner_NOVO':>11} {'valido_nao_runner':>17}")
    print(header)
    for lp, agg in agregados.items():
        print(f"{lp:18} {total_grads.get(lp, 0):>12} {agg['processados']:>12} {agg['sem_cache']:>9} "
             f"{agg['dado_invalido']:>13} {agg['runner_antigo']:>13} {agg['runner_novo_e_valido']:>11} "
             f"{agg['valido_nao_runner']:>17}")

    print("\nProjecao de RUNNERS pro periodo INTEIRO (taxa medida nos pools JA processados x total de "
         f"graduacoes enumeradas; so vale o quanto ja foi enumerado/baixado -- confira `funil --periodo "
         f"{args.periodo}` pra saber a cobertura real):")
    taxas_runner_novo: dict[str, float] = {}
    for lp, agg in agregados.items():
        proc = agg["processados"] - agg["sem_cache"]
        if proc <= 0:
            continue
        taxa_valido = 1.0 - agg["dado_invalido"] / proc
        taxa_runner_novo = agg["runner_novo_e_valido"] / proc
        taxa_runner_antigo = agg["runner_antigo"] / proc
        taxas_runner_novo[lp] = taxa_runner_novo
        total = total_grads.get(lp, 0)
        print(f" {lp}: {total} graduacoes enumeradas -> ~{total*taxa_runner_antigo:,.0f} runners (regra ANTIGA) "
             f"vs ~{total*taxa_runner_novo:,.0f} runners (regra NOVA, valida+fechamento) "
             f"(~{total*(1-taxa_valido):,.0f} seriam dado_invalido)")

    print("\nProjecao de SETUPS PRIMARIOS 1h (taxa setups/runner_ANTIGO ja medida -- proxy conservador; a taxa "
         "real sob a regra NOVA so se sabe rodando o detector de novo, nao e feito aqui):")
    for lp, agg in agregados.items():
        if agg["runner_antigo"] <= 0:
            print(f" {lp}: sem runner (regra antiga) processado ainda, sem taxa pra projetar")
            continue
        taxa_setup_por_runner = setups_1h_por_lp.get(lp, 0) / agg["runner_antigo"]
        runners_novo_proj = total_grads.get(lp, 0) * taxas_runner_novo.get(lp, 0.0)
        print(f" {lp}: {setups_1h_por_lp.get(lp, 0)} setups primarios 1h medidos / {agg['runner_antigo']} "
             f"runners antigos = {taxa_setup_por_runner:.4f} setup/runner -> ~{runners_novo_proj*taxa_setup_por_runner:,.1f} "
             f"setups 1h projetados no discovery inteiro (regra nova)")

    print(f"\nProjecao de SETUPS PRIMARIOS 1h no HOLDOUT selado ({sum(HOLDOUT_GRADUACOES.values())} graduacoes, "
         "mesma taxa do discovery como proxy -- holdout ainda nao processado):")
    for lp, grads in HOLDOUT_GRADUACOES.items():
        agg = agregados.get(lp)
        if not agg or agg["runner_antigo"] <= 0:
            print(f" {lp}: sem taxa do discovery pra projetar")
            continue
        taxa_setup_por_runner = setups_1h_por_lp.get(lp, 0) / agg["runner_antigo"]
        runners_novo_proj = grads * taxas_runner_novo.get(lp, 0.0)
        print(f" {lp}: {grads} graduacoes seladas -> ~{runners_novo_proj:,.1f} runners (regra nova) -> "
             f"~{runners_novo_proj*taxa_setup_por_runner:,.1f} setups 1h projetados")

    print(f"\n{sem_cache} pool(s) sem candle em cache pra esse tf (precisa baixar-bruto/discovery ter rodado "
         "nesse tf; nao contam na taxa).")
    store.close()


if __name__ == "__main__":
    main()
