"""Linha de comando da Parte A (somente leitura de dados publicos).

    python -m signals_mvp.pos_runner.parte_a.cli plano --congelamento 2026-10-17
    python -m signals_mvp.pos_runner.parte_a.cli selar-holdout --janelas 400
    python -m signals_mvp.pos_runner.parte_a.cli discovery [--alvo 60] [--max-janelas N]
    python -m signals_mvp.pos_runner.parte_a.cli escolher
    python -m signals_mvp.pos_runner.parte_a.cli holdout [--alvo 40]
    python -m signals_mvp.pos_runner.parte_a.cli relatorio

Travas (falham ANTES de qualquer download de preco):
- o pre-registro precisa estar `PRE-REGISTRADO` (nao RASCUNHO) e citar o hash da config em uso;
- a selagem do holdout precisa existir, bater o hash e estar commitada;
- o checkpoint guarda o hash da config e do plano: mudar qualquer um no meio da coleta e recusado.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from ...http import HttpClient, RateLimiter
from ..candles import OhlcvStore
from ..lineage import creation_time
from ..params import is_preregistered, load_params
from ..solana_rpc import SolanaRpc, endpoints_from_env
from .metrics import candidate, choose_variant, holdout_verdict, variant_table
from .pipeline import Context, load_seal, make_rpc_enumerator, run_period, seal_holdout
from .plan import PeriodPlan, load_plan, write_plan
from .quotebook import QuoteBook
from .store import Store

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs" / "pos-runner-v0"
PREREG = REPO / "docs" / "pos-runner-v0-preregistration-DRAFT-2026-10-15.md"
WORK = REPO / "signals_mvp" / "dados" / "pos_runner_parte_a"
GT_BASE = "https://api.geckoterminal.com/api/v2"
DISCOVERY_TARGET = 60      # setups primarios minimos por timeframe (parada por contagem)
HOLDOUT_TARGET = 40        # no tf escolhido; folga para chegar aos 30 trades FECHADOS do veredito
CREATION_MAX_PAGES = 100   # ate 100 mil assinaturas da curva por token (o SOLCAT teve ~10 mil)


def check_preregistration(path: Path, params_version: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not is_preregistered(text, ""):
        raise SystemExit(f"TRAVA: {path.name} ainda nao esta PRE-REGISTRADO (falta o OK do operador no Passo 0)")
    if not is_preregistered(text, params_version):
        raise SystemExit(f"TRAVA: o pre-registro nao cita o hash da config em uso ({params_version})")


def build_context(work: Path, plan: PeriodPlan) -> Context:
    params = load_params()
    store = Store(work / "parte_a.sqlite")
    store.require("versao_config", params.version)
    store.require("versao_plano", plan.version)
    http = HttpClient(GT_BASE, RateLimiter(20, 2, pause_s=30, pause_max_s=240), 30, name="GeckoTerminal")
    ohlcv = OhlcvStore(http, work / "ohlcv")
    rpc = SolanaRpc(endpoints_from_env(), per_min=100)
    supply_cache: dict[str, Optional[float]] = {}

    def supply(mint: str) -> Optional[float]:
        if mint not in supply_cache:
            try:
                supply_cache[mint] = rpc.token_supply(mint)
            except Exception:  # falha de rede: sem supply = token fica de fora com motivo
                supply_cache[mint] = None
        return supply_cache[mint]

    created_cache: dict[str, Optional[float]] = {}

    def created(mint: str, migration_sig: str) -> Optional[float]:
        # falha de RPC sobe (a coleta para e retoma do checkpoint): so "teto de paginas" vira falta de dado
        if mint not in created_cache:
            ts, _seen, _complete = creation_time(rpc, mint, migration_sig, max_pages=CREATION_MAX_PAGES)
            created_cache[mint] = None if ts is None else float(ts)
        return created_cache[mint]

    quotes = QuoteBook(ohlcv, work / "referencias_cotacao.json")
    return Context(plan, params, store, ohlcv, quotes, make_rpc_enumerator(rpc), supply, created)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Parte A do POS-RUNNER-V0 (backtest sem vies)")
    ap.add_argument("comando", choices=["plano", "selar-holdout", "discovery", "escolher", "holdout", "relatorio"])
    ap.add_argument("--congelamento", help="data do congelamento (AAAA-MM-DD), so para `plano`")
    ap.add_argument("--janelas", type=int, default=400, help="janelas do holdout seladas")
    ap.add_argument("--alvo", type=int, default=None,
                    help=f"setups primarios minimos por timeframe (padrao: {DISCOVERY_TARGET} no discovery, {HOLDOUT_TARGET} no holdout)")
    ap.add_argument("--max-janelas", type=int, default=None)
    ap.add_argument("--dir", type=Path, default=WORK)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    plan_path = DOCS / "plano_parte_a.json"
    seal_path = DOCS / "holdout_selado.json"
    params = load_params()

    if args.comando == "plano":
        if not args.congelamento:
            raise SystemExit("--congelamento AAAA-MM-DD e obrigatorio")
        doc = write_plan(PeriodPlan(args.congelamento), plan_path, params.version)
        print(json.dumps(doc, indent=1, ensure_ascii=False))
        print(f"\nCommite {plan_path} junto do pre-registro.")
        return 0

    plan = load_plan(plan_path)
    check_preregistration(PREREG, params.version)
    ctx = build_context(args.dir, plan)

    if args.comando == "selar-holdout":
        doc = seal_holdout(ctx, args.janelas, seal_path)
        print(f"{len(doc['graduacoes'])} graduacoes seladas em {args.janelas} janelas; hash {doc['hash_pools']}")
        print(f"Commite {seal_path} ANTES de rodar o discovery.")
        return 0

    ctx.sealed_holdout = load_seal(seal_path, ctx)
    if args.comando == "discovery":
        counts = run_period(ctx, "discovery", args.alvo or DISCOVERY_TARGET, args.max_janelas, progress=lambda c: logging.info("%s", c))
        from .baseline import run_baselines
        run_baselines(ctx, "discovery")
        print(json.dumps(counts, indent=1))
        return 0
    if args.comando == "escolher":
        table = variant_table(ctx, "discovery")
        pick, stats = choose_variant(table)
        verdict = candidate(stats)
        doc = {"variante": pick, "estatisticas": stats, **verdict, "tabela": table}
        (DOCS / "escolha_discovery.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
        print(json.dumps({"variante": pick, **verdict}, indent=1))
        print(f"Commite {DOCS / 'escolha_discovery.json'} ANTES de abrir o holdout.")
        return 0
    if args.comando == "holdout":
        choice = json.loads((DOCS / "escolha_discovery.json").read_text(encoding="utf-8"))
        if not choice.get("candidato"):
            raise SystemExit("discovery nao produziu candidato: holdout nao e aberto (hipotese fecha no discovery)")
        sealed_windows = json.loads(seal_path.read_text(encoding="utf-8"))["janelas"]
        limit = min(sealed_windows, args.max_janelas or sealed_windows)   # nunca passa das janelas seladas
        tf = choice["variante"].split("/")[0]
        counts = run_period(ctx, "holdout", args.alvo or HOLDOUT_TARGET, limit, progress=lambda c: logging.info("%s", c), stop_tfs=(tf,))
        from .baseline import run_baselines
        run_baselines(ctx, "holdout")
        stats = variant_table(ctx, "holdout").get(choice["variante"], {})
        doc = {"variante": choice["variante"], "veredito": holdout_verdict(stats), "estatisticas": stats, "contagens": counts}
        (DOCS / "resultado_holdout.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: doc[k] for k in ("variante", "veredito")}, indent=1))
        return 0
    if args.comando == "relatorio":
        from .report import write_report
        print(write_report(ctx, DOCS))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
