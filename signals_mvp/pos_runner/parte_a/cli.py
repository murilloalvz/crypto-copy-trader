"""Linha de comando da Parte A (somente leitura de dados publicos).

    python -m signals_mvp.pos_runner.parte_a.cli plano --congelamento 2026-10-17
    python -m signals_mvp.pos_runner.parte_a.cli selar-holdout --janelas 400
    python -m signals_mvp.pos_runner.parte_a.cli baixar-bruto --periodo discovery [--max-janelas N]
    python -m signals_mvp.pos_runner.parte_a.cli discovery --rodada 1 [--alvo 60] [--max-janelas N]
    python -m signals_mvp.pos_runner.parte_a.cli discovery --rodada 2
    python -m signals_mvp.pos_runner.parte_a.cli escolher
    python -m signals_mvp.pos_runner.parte_a.cli holdout [--alvo 40]
    python -m signals_mvp.pos_runner.parte_a.cli relatorio
    python -m signals_mvp.pos_runner.parte_a.cli funil --periodo discovery

Travas (falham ANTES de qualquer download de preco):
- o pre-registro precisa estar `PRE-REGISTRADO` (nao RASCUNHO) e citar o hash da config em uso;
- a selagem do holdout precisa existir, bater o hash e estar commitada;
- o checkpoint guarda o hash da config e do plano: mudar qualquer um no meio da coleta e recusado.

`discovery --rodada` (EMENDA 2026-10-19, secao 14 -- cega a resultado, primeiro resultado concreto mais cedo,
SEM cortar nenhuma das 24 combinacoes): rodada 1 = so 1h (8 combinacoes: saida A/B x medida x idade), parada ao
chegar a 60 setups no 1h; rodada 2 = 5m e 4h JUNTOS (16 combinacoes), OBRIGATORIA e PRE-REGISTRADA (nao
condicional ao resultado da rodada 1), executada em seguida, parada ao os DOIS chegarem a 60. `escolher` escolhe
1 candidato POR RODADA (no maximo 2 no total); `holdout` testa cada um UMA vez, reportados como testes
separados. `funil --periodo {discovery,holdout}` imprime SO contagens (pools, estagio 1, runners, estagio 2 por
tf/status, setups primarios por tf/launchpad/hora BRT) -- nunca EV/PF/trade -- e funciona com download parcial,
em qualquer momento, sem chamada de rede.

`baixar-bruto` (decisao operacional de 2026-10-16): baixa enumeracao + candles de estagio 1/2 com a janela mais
ANTIGA do calendario primeiro (nunca pela ordem sorteada), para o download nunca perder dado por causa do limite
movel de ~180 dias do GeckoTerminal. So grava dado bruto; nao roda o detector nem decide a parada por contagem —
isso continua em `discovery`/`holdout`, na ordem sorteada pre-registrada, que depois de um `baixar-bruto` completo
nao faz NENHUMA chamada de rede nova. RPC: `POS_RUNNER_RPC_URLS` (lista separada por virgula); ritmo-teto em
`POS_RUNNER_RPC_PER_MIN` (padrao 100; o limitador e adaptativo — cai pela metade a cada 429 e sobe aos poucos —
entao o teto so importa com um RPC dedicado, como o QuickNode do operador, onde subir o teto nao pesa num recurso
publico compartilhado).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import os

from ...http import HttpClient, RateLimiter
from ...util import iso_utc, utc_now
from ..candles import OhlcvStore
from ..lineage import creation_time
from ..params import is_preregistered, load_params
from ..solana_rpc import SolanaRpc, endpoints_from_env
from .metrics import candidate, choose_variant_for_tfs, funil, holdout_verdict, variant_table
from .pipeline import Context, load_seal, make_rpc_enumerator, prefetch_period, run_period, seal_holdout
from .plan import PeriodPlan, load_plan, write_plan
from .quotebook import QuoteBook
from .store import Store

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs" / "pos-runner-v0"
PREREG = REPO / "docs" / "pos-runner-v0-preregistration-DRAFT-2026-10-15.md"
WORK = REPO / "signals_mvp" / "dados" / "pos_runner_parte_a"
GT_BASE = "https://api.geckoterminal.com/api/v2"
ENV_RPC_PER_MIN = "POS_RUNNER_RPC_PER_MIN"
DISCOVERY_TARGET = 60      # setups primarios minimos por timeframe (parada por contagem)
HOLDOUT_TARGET = 40        # no tf escolhido; folga para chegar aos 30 trades FECHADOS do veredito
CREATION_MAX_PAGES = 100   # ate 100 mil assinaturas da curva por token (o SOLCAT teve ~10 mil)
# EMENDA 2026-10-19 (secao 14, rodadas por tf -- cega a resultado, primeiro resultado concreto mais cedo, sem
# cortar nenhuma das 24 combinacoes): rodada 1 = 1h isolado (8 combinacoes: saida A/B x medida x idade); rodada
# 2 = 5m e 4h juntos (16 combinacoes), OBRIGATORIA e pre-registrada (nunca condicional ao resultado da rodada 1).
ROUND_TFS = {1: ("1h",), 2: ("5m", "4h")}


def check_preregistration(path: Path, params_version: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not is_preregistered(text, ""):
        raise SystemExit(f"TRAVA: {path.name} ainda nao esta PRE-REGISTRADO (falta o OK do operador no Passo 0)")
    if not is_preregistered(text, params_version):
        raise SystemExit(f"TRAVA: o pre-registro nao cita o hash da config em uso ({params_version})")


def build_context(work: Path, plan: PeriodPlan) -> tuple[Context, SolanaRpc, HttpClient]:
    params = load_params()
    store = Store(work / "parte_a.sqlite")
    store.require("versao_config", params.version)
    store.require("versao_plano", plan.version)
    # EMENDA 2026-10-17 (cega a resultado, operacional): teto 20->26/min + jitter de 1.5s -- so desincroniza o
    # ritmo das chamadas (menos 429/pausa de 30s), nunca muda QUAL candle e baixado.
    http = HttpClient(GT_BASE, RateLimiter(26, 2, pause_s=30, pause_max_s=240, jitter_s=1.5), 30, name="GeckoTerminal")
    ohlcv = OhlcvStore(http, work / "ohlcv")
    rpc_per_min = float(os.environ.get(ENV_RPC_PER_MIN, "100"))   # teto do limitador adaptativo; so infra, nao regra
    rpc = SolanaRpc(endpoints_from_env(), per_min=rpc_per_min)
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
    ctx = Context(plan, params, store, ohlcv, quotes, make_rpc_enumerator(rpc), supply, created)
    return ctx, rpc, http


def _track_usage(ctx: Context, rpc: SolanaRpc, http: HttpClient) -> None:
    """Consumo acumulado (RPC pago + GeckoTerminal) desta Store, por chamada de comando E por dia UTC -- nao e o %
    real do plano gratis da QuickNode (o operador ve isso no painel dela); so ajuda a decidir quando checar o
    painel e a medir o gasto diario real (decisao operacional de 2026-10-16)."""
    total_rpc = int(ctx.store.get("rpc_calls_total") or 0) + rpc.calls
    total_gt = int(ctx.store.get("gt_calls_total") or 0) + http.calls
    ctx.store.set("rpc_calls_total", str(total_rpc))
    ctx.store.set("gt_calls_total", str(total_gt))
    dia = iso_utc(utc_now())[:10]
    dia_rpc = int(ctx.store.get(f"rpc_calls_dia:{dia}") or 0) + rpc.calls
    dia_gt = int(ctx.store.get(f"gt_calls_dia:{dia}") or 0) + http.calls
    ctx.store.set(f"rpc_calls_dia:{dia}", str(dia_rpc))
    ctx.store.set(f"gt_calls_dia:{dia}", str(dia_gt))
    logging.info("creditos: RPC %d nesta execucao (%d hoje %s, %d acumulado) | GeckoTerminal %d nesta execucao (%d hoje, %d acumulado)",
                rpc.calls, dia_rpc, dia, total_rpc, http.calls, dia_gt, total_gt)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Parte A do POS-RUNNER-V0 (backtest sem vies)")
    ap.add_argument("comando", choices=["plano", "selar-holdout", "baixar-bruto", "discovery", "escolher", "holdout", "relatorio", "funil"])
    ap.add_argument("--periodo", choices=["discovery", "holdout"], default="discovery", help="para `baixar-bruto` e `funil`")
    ap.add_argument("--rodada", type=int, choices=[1, 2], default=None,
                    help="obrigatorio em `discovery` (EMENDA secao 14): 1 = so 1h (8 combinacoes); "
                         "2 = 5m+4h juntos (16 combinacoes), OBRIGATORIA e pre-registrada em seguida a rodada 1")
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
    ctx, rpc, http = build_context(args.dir, plan)
    try:
        if args.comando == "selar-holdout":
            doc = seal_holdout(ctx, args.janelas, seal_path)
            print(f"{len(doc['graduacoes'])} graduacoes seladas em {args.janelas} janelas; hash {doc['hash_pools']}")
            print(f"Commite {seal_path} ANTES de rodar o discovery.")
            return 0

        ctx.sealed_holdout = load_seal(seal_path, ctx)
        if args.comando == "baixar-bruto":
            total_janelas = len(ctx.plan.windows(args.periodo))
            t0 = utc_now()
            resumo = prefetch_period(ctx, args.periodo, args.max_janelas, progress=lambda c: logging.info("%s", c))
            elapsed_min = max((utc_now() - t0) / 60.0, 1e-9)
            ritmo = resumo["janelas"] / elapsed_min            # janelas/min NESTA execucao (ja inclui RPC + GT)
            faltam = max(total_janelas - resumo["janelas"], 0)
            resumo["ritmo_janelas_por_min"] = round(ritmo, 2)
            resumo["janelas_restantes_no_periodo"] = faltam
            resumo["eta_dias_no_ritmo_atual"] = round(faltam / ritmo / 60.0 / 24.0, 1) if ritmo > 0 else None
            print(json.dumps(resumo, indent=1, ensure_ascii=False))
            if resumo["fora_do_alcance_gratis"]:
                print(f"\nATENCAO: {len(resumo['fora_do_alcance_gratis'])} data(s) ja fora do alcance gratis do "
                     f"GeckoTerminal (missing explicito, nunca silencioso): {resumo['fora_do_alcance_gratis']}")
            if resumo["eta_dias_no_ritmo_atual"] is not None:
                print(f"Ritmo medido nesta execucao: {resumo['ritmo_janelas_por_min']:.2f} janelas/min -> "
                     f"~{resumo['eta_dias_no_ritmo_atual']:.1f} dia(s) para as {faltam} janelas restantes do periodo "
                     f"'{args.periodo}' neste ritmo (QuickNode pode pausar e voltar sozinha no limite diario).")
            return 0
        if args.comando == "discovery":
            if args.rodada is None:
                raise SystemExit("--rodada 1 ou --rodada 2 e obrigatorio (EMENDA secao 14: 1h isolado primeiro "
                                 "-- rodada 1 --, 5m+4h depois -- rodada 2, obrigatoria em seguida)")
            tfs = ROUND_TFS[args.rodada]
            counts = run_period(ctx, "discovery", args.alvo or DISCOVERY_TARGET, args.max_janelas,
                                progress=lambda c: logging.info("%s", c), stop_tfs=tfs, active_tfs=tfs)
            from .baseline import run_baselines
            run_baselines(ctx, "discovery")
            print(json.dumps({"rodada": args.rodada, "tfs": tfs, **counts}, indent=1))
            return 0
        if args.comando == "escolher":
            # EMENDA 2026-10-19 (secao 14): 1 escolha POR RODADA (universo de comparacao de cada uma nunca se
            # mistura) -- no maximo 2 candidatos vao ao holdout; cada um e 1 teste de hipotese, declarados os 2.
            table = variant_table(ctx, "discovery")
            candidatos = []
            for rodada, tfs in ROUND_TFS.items():
                pick, stats = choose_variant_for_tfs(table, tfs)
                verdict = candidate(stats) if pick else {"criterios": {}, "candidato": False}
                candidatos.append({"rodada": rodada, "tfs": tfs, "variante": pick, "estatisticas": stats, **verdict})
            doc = {"candidatos": candidatos, "tabela": table,
                   "nota": "2 escolhas independentes (1 por rodada, EMENDA secao 14): rodada 1 so compete dentro "
                           "das 8 combinacoes de 1h; rodada 2 so dentro das 16 de 5m/4h. No maximo 2 vao ao "
                           "holdout; o relatorio declara que sao 2 testes de hipotese, nunca 1."}
            (DOCS / "escolha_discovery.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
            print(json.dumps({"candidatos": [{"rodada": c["rodada"], "variante": c["variante"], "candidato": c["candidato"]}
                                             for c in candidatos]}, indent=1))
            print(f"Commite {DOCS / 'escolha_discovery.json'} ANTES de abrir o holdout.")
            return 0
        if args.comando == "holdout":
            choice = json.loads((DOCS / "escolha_discovery.json").read_text(encoding="utf-8"))
            candidatos = [c for c in choice["candidatos"] if c.get("candidato")]
            if not candidatos:
                raise SystemExit("discovery nao produziu nenhum candidato nas 2 rodadas: holdout nao e aberto")
            sealed_windows = json.loads(seal_path.read_text(encoding="utf-8"))["janelas"]
            limit = min(sealed_windows, args.max_janelas or sealed_windows)   # nunca passa das janelas seladas
            tfs = tuple(c["variante"].split("/")[0] for c in candidatos)
            counts = run_period(ctx, "holdout", args.alvo or HOLDOUT_TARGET, limit, progress=lambda c: logging.info("%s", c),
                                stop_tfs=tfs, active_tfs=tfs)
            from .baseline import run_baselines
            run_baselines(ctx, "holdout")
            table_h = variant_table(ctx, "holdout")
            testes = [{"variante": c["variante"], "veredito": holdout_verdict(table_h.get(c["variante"], {})),
                      "estatisticas": table_h.get(c["variante"], {})} for c in candidatos]
            doc = {"testes": testes, "contagens": counts,
                   "nota": f"{len(testes)} teste(s) de hipotese reportado(s) (1 por rodada do discovery, EMENDA secao 14)"}
            (DOCS / "resultado_holdout.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
            print(json.dumps({"testes": [{"variante": t["variante"], "veredito": t["veredito"]} for t in testes]}, indent=1))
            return 0
        if args.comando == "funil":
            print(json.dumps(funil(ctx, args.periodo), indent=1, ensure_ascii=False))
            return 0
        if args.comando == "relatorio":
            from .report import write_report
            print(write_report(ctx, DOCS))
            return 0
        return 1
    finally:
        _track_usage(ctx, rpc, http)


if __name__ == "__main__":
    sys.exit(main())
