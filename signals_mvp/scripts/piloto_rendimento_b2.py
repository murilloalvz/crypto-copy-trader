"""RODADA 22 (pedido 2026-11-16, item 2): PILOTO DE RENDIMENTO do B2 -- quantos tokens recem-graduados
geram >=1 ENTRADA da V3 CONGELADA (`ParamsV3=56762db29cd6`), por 1.000 graduacoes, numa amostra
sorteada (semente fixa) de janelas de 30 min FORA de qualquer holdout. PAPER/READ-ONLY.

O QUE ESTE SCRIPT NAO FAZ (por desenho, nao por convencao):
- nunca chama `simulate_v1`/`horizonte_fixo`/`CostModel` -- nenhum R, nenhum P&L, nenhum desfecho;
- nunca grava no banco do bot (nem abre `estado.sqlite`); cache e checkpoint ficam em `--trabalho`;
- nunca usa o RPC/orcamento do bot: RPC proprio (`--rpc-url`, padrao o publico) e GT gratuito com
  limitador proprio -- rodar FORA da VM.

Universo: TODAS as graduacoes enumeradas on-chain (`pos_runner/enumerate.py`, mesma enumeracao da
Parte A -- pega token morto, nao depende de indexador) dos 3 launchpads, nas janelas sorteadas.
Candles: MESMA conversao da Parte A (`parte_a/pipeline._mc_bars`, sem copia: candles 1h em token de
cotacao -> MC em USD, para no 1o candle sem USD, `fill_gaps`), de `grad_ts` ate `grad_ts + 14 d`
(`idade_max_dias` do bot ao vivo). `L_bc` = open do 1o candle real (mesma regra da Parte A e de
`live.py:4148`). Portao de qualidade = `qualidade_v1.avaliar_qualidade` (mesmo do ao vivo/retro).
Detector = `DetectorV1(ParamsV3, "1h", L_bc, grad_ts, created_ts=grad_ts)`.

SIMPLIFICACOES DECLARADAS:
- `created_ts = grad_ts` (em vez da criacao on-chain, que custa ate 100 paginas/token): equivalente
  para a EMISSAO de ENTRADA so porque a janela de idade da V3 e [0, 36500] dias -- qualquer criacao
  <= graduacao cai dentro dela. Nao vale para V1 (2-7 d). Covariavel `idade_dias` fica errada (nao
  usada aqui).
- o filtro ao vivo `mc_atual < min_mc_usd` na construcao do detector (`live.py:2162`) depende do
  instante em que o bot pegou o pool -- nao se aplica a um universo enumerado; fica de fora.
- conta ENTRADA (decisao) -- nao confere se o candle seguinte abriria dentro do plano (isso exige
  `simulate_v1`, fora do escopo "sem desfecho").
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..http import HttpClient, RateLimiter
from ..pos_runner.candles import OhlcvStore
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.enumerate import LAUNCHPADS, enumerate_window
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.parte_a.pipeline import _mc_bars
from ..pos_runner.parte_a.quotebook import QuoteBook
from ..pos_runner.qualidade_v1 import avaliar_qualidade
from ..pos_runner.solana_rpc import SolanaRpc

REPO = Path(__file__).resolve().parents[2]
GT_BASE = "https://api.geckoterminal.com/api/v2"
RPC_PUBLICO = "https://api.mainnet-beta.solana.com"
DAY = 86400
JANELA_S = 1800
HORIZONTE_RASTREIO_S = 14 * DAY          # idade_max_dias do bot ao vivo (config.yaml)
ALVO_TOKENS_SINALIZADOS = 200


def _ts(texto: str) -> int:
    return int(datetime.strptime(texto, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


# Intervalos PROIBIDOS para o piloto (nunca sorteados): holdout selado do V0 + sua semana de embargo, e a
# janela limpa candidata do B2 (22/09 ate o inicio da Parte B ao vivo, 16/10 -- o fim exato depende de
# MIN(grad_ts) de pr_pools, secao (e) de fase_a_vm.py; 16/10 e o limite CONSERVADOR).
PROIBIDOS: tuple[tuple[int, int, str], ...] = (
    (_ts("2026-07-26"), _ts("2026-09-22"), "V0 embargo + holdout selado"),
    (_ts("2026-09-22"), _ts("2026-10-16"), "janela limpa candidata do B2"),
)


def sortear_janelas(inicio: int, fim: int, n: int, semente: int) -> list[tuple[int, int]]:
    total = (fim - inicio) // JANELA_S
    if n > total:
        raise ValueError(f"so ha {total} janelas de 30 min no periodo")
    idx = sorted(random.Random(semente).sample(range(total), n))
    janelas = [(inicio + k * JANELA_S, inicio + (k + 1) * JANELA_S) for k in idx]
    for lo, hi in janelas:
        for p_lo, p_hi, nome in PROIBIDOS:
            if lo < p_hi and hi > p_lo:
                raise ValueError(f"janela {lo}-{hi} cruza intervalo proibido: {nome}")
    return janelas


def _pools_selados() -> set[str]:
    path = REPO / "docs" / "pos-runner-v0" / "holdout_selado.json"
    if not path.exists():
        return set()
    return {g["pool"] for g in json.loads(path.read_text(encoding="utf-8")).get("graduacoes", [])}


def clopper_pearson(x: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """IC exato por bissecao na CDF binomial (sem SciPy)."""
    if n == 0:
        return 0.0, 1.0
    a = (1 - conf) / 2

    def cdf(k: int, p: float) -> float:
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))

    def bis(cond) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            m = (lo + hi) / 2
            lo, hi = (lo, m) if cond(m) else (m, hi)
        return (lo + hi) / 2
    lo = 0.0 if x == 0 else bis(lambda p: 1 - cdf(x - 1, p) >= a)
    hi = 1.0 if x == n else bis(lambda p: cdf(x, p) <= a)
    return lo, hi


def n_para_alvo(p: float, alvo: int = ALVO_TOKENS_SINALIZADOS, z: float = 1.2816) -> Optional[int]:
    """Menor N com P(Binomial(N,p) >= alvo) ~>= 90% (aprox. normal): N*p - z*sqrt(N*p*(1-p)) >= alvo."""
    if p <= 0:
        return None
    n = math.ceil(alvo / p)
    while n * p - z * math.sqrt(n * p * (1 - p)) < alvo:
        n += max(1, n // 200)
    return n


def processar_graduacao(g: dict[str, Any], ctx: Any, usd_de: Any, rpc: SolanaRpc, params: Any,
                        agora: int) -> dict[str, Any]:
    """Contagem de eventos da V3 para 1 graduacao. Nunca simula trade. `usd_de(quote)` devolve a serie
    USD da cotacao para o PERIODO inteiro (1 serie por cotacao, como `parte_a.pipeline.Context.usd`)."""
    out: dict[str, Any] = {"pool": g["pool"], "launchpad": g["launchpad"], "grad_ts": g["grad_ts"]}
    fim = min(g["grad_ts"] + HORIZONTE_RASTREIO_S, agora)
    usd = usd_de(g["quote_mint"]) if g["quote_mint"] else None
    if usd is None:
        return out | {"status": "sem_referencia_usd"}
    try:
        supply = rpc.token_supply(g["mint"])
    except Exception as exc:   # falta explicita, nunca chute
        return out | {"status": "sem_supply", "erro": type(exc).__name__}
    if not supply:
        return out | {"status": "sem_supply"}
    stats: dict[str, Any] = {}
    row = {"pool": g["pool"], "grad_ts": g["grad_ts"]}
    bars = _mc_bars(ctx, row, "1h", fim, supply, usd, stats)
    if stats.get("fora_do_alcance_gratis"):
        return out | {"status": "fora_do_alcance_gratis"}
    reais = [b for b in bars if not b.filled]
    if not reais:
        return out | {"status": "sem_candles"}
    out["n_candles_reais"] = len(reais)
    qual = avaliar_qualidade(bars, params)
    if not qual.valido:
        return out | {"status": "dado_invalido", "motivo": qual.motivo}
    det = DetectorV1(params, "1h", reais[0].open, g["grad_ts"], float(g["grad_ts"]))
    kinds: dict[str, int] = {}
    for bar in bars:
        for ev in det.update(bar):
            kinds[ev.kind] = kinds.get(ev.kind, 0) + 1
    return out | {"status": "ok", "eventos": kinds, "runner": kinds.get("RUNNER", 0) > 0,
                  "n_entrada": kinds.get("ENTRADA", 0)}


def resumo(linhas: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    grupos: dict[str, list[dict[str, Any]]] = {"TOTAL": linhas}
    for lp in sorted({l["launchpad"] for l in linhas}):
        grupos[lp] = [l for l in linhas if l["launchpad"] == lp]
    for nome, ls in grupos.items():
        n = len(ls)
        status: dict[str, int] = {}
        for l in ls:
            status[l["status"]] = status.get(l["status"], 0) + 1
        runners = sum(1 for l in ls if l.get("runner"))
        sinal = sum(1 for l in ls if l.get("n_entrada", 0) > 0)
        n_ent = sum(l.get("n_entrada", 0) for l in ls)
        lo, hi = clopper_pearson(sinal, n)
        p = sinal / n if n else 0.0
        out.append(f"### {nome}: graduacoes={n} | status={status}")
        out.append(f"- runner (pico >= 300k em 14 d): {runners} ({1000 * runners / n:.1f}/1000)" if n else "- vazio")
        if not n:
            continue
        out.append(f"- tokens com >=1 ENTRADA V3 em 14 d: {sinal} -> {1000 * p:.1f} por 1.000 graduacoes "
                   f"(IC95% {1000 * lo:.1f}-{1000 * hi:.1f}); ENTRADAs totais={n_ent} ({1000 * n_ent / n:.1f}/1000)")
        if sinal:
            out.append(f"- N de graduacoes a sortear p/ >= {ALVO_TOKENS_SINALIZADOS} tokens sinalizados: ponto="
                       f"{math.ceil(ALVO_TOKENS_SINALIZADOS / p)}; com 90% de chance={n_para_alvo(p)}; "
                       f"pessimista (limite inferior do IC)={math.ceil(ALVO_TOKENS_SINALIZADOS / lo) if lo > 0 else 'inf'}")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Piloto de rendimento do B2 (contagem de sinais V3, sem desfecho).")
    ap.add_argument("--inicio", default="2026-10-16")
    ap.add_argument("--fim", default="2026-11-01", help="exclusivo; precisa estar >= 14 d no passado")
    ap.add_argument("--janelas", type=int, default=12)
    ap.add_argument("--semente", type=int, default=20261117)
    ap.add_argument("--launchpads", default="pumpfun,meteora_dbc,raydium_launchlab")
    ap.add_argument("--trabalho", type=Path, required=True, help="cache/checkpoint PROPRIOS (nunca dados/ do bot)")
    ap.add_argument("--rpc-url", default=os.environ.get("PILOTO_RPC_URL", RPC_PUBLICO))
    ap.add_argument("--rpc-por-min", type=float, default=60.0)
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    agora = int(time.time())
    inicio, fim = _ts(args.inicio), _ts(args.fim)
    if fim > agora - HORIZONTE_RASTREIO_S:
        raise SystemExit("--fim precisa estar >= 14 dias no passado (rastreio completo de 14 d)")
    janelas = sortear_janelas(inicio, fim, args.janelas, args.semente)
    args.trabalho.mkdir(parents=True, exist_ok=True)
    ckpt = args.trabalho / "piloto_b2.jsonl"
    feitos: dict[str, dict[str, Any]] = {}
    janelas_feitas: set[str] = set()
    if ckpt.exists():
        for linha in ckpt.read_text().splitlines():
            d = json.loads(linha)
            if d.get("tipo") == "janela":
                janelas_feitas.add(d["chave"])
            else:
                feitos[d["pool"]] = d
    http = HttpClient(GT_BASE, RateLimiter(24, 2, pause_s=30, pause_max_s=240, jitter_s=1.5), 30, name="GeckoTerminal")
    ohlcv = OhlcvStore(http, args.trabalho / "ohlcv")
    quotes = QuoteBook(ohlcv, args.trabalho / "referencias_cotacao.json")
    rpc = SolanaRpc([args.rpc_url], per_min=args.rpc_por_min)
    ctx = types.SimpleNamespace(ohlcv=ohlcv)
    params = load_params_v3()
    selados = _pools_selados()
    usd_cache: dict[str, Any] = {}

    def usd_de(quote: str) -> Any:
        if quote not in usd_cache:
            usd_cache[quote] = quotes.series(quote, inicio - DAY, fim + HORIZONTE_RASTREIO_S + DAY, inicio)
        return usd_cache[quote]
    print(f"ParamsV3={params.version} | janelas={len(janelas)} semente={args.semente} | {args.inicio}..{args.fim}",
          flush=True)
    with ckpt.open("a") as fh:
        for lo, hi in janelas:
            for lp in args.launchpads.split(","):
                chave = f"{lp}:{lo}"
                if chave in janelas_feitas:
                    continue
                res = enumerate_window(rpc, LAUNCHPADS[lp], lo, hi)
                if res.error:
                    print(f"janela {chave} ERRO {res.error} -- fica para a proxima execucao", flush=True)
                    continue
                grads = [g for g in res.graduations if g.status == "ok" and g.pool]
                vazou = [g.pool for g in grads if g.pool in selados]
                if vazou:
                    raise SystemExit(f"pool do holdout selado do V0 apareceu no piloto: {vazou[:3]}")
                for g in grads:
                    if g.pool in feitos:
                        continue
                    d = processar_graduacao({"pool": g.pool, "mint": g.mint, "quote_mint": g.quote_mint,
                                             "launchpad": lp, "grad_ts": g.block_time},
                                            ctx, usd_de, rpc, params, agora)
                    feitos[g.pool] = d
                    fh.write(json.dumps(d) + "\n")
                    fh.flush()
                fh.write(json.dumps({"tipo": "janela", "chave": chave, "n_grad": len(grads),
                                     "nao_resolvida": res.nao_resolvida}) + "\n")
                fh.flush()
                print(f"janela {chave}: {len(grads)} graduacoes (nao_resolvida={res.nao_resolvida}) | "
                      f"RPC={rpc.calls} GT={http.calls}", flush=True)
    print("\n".join(resumo(list(feitos.values()))))
    print(f"chamadas nesta execucao: RPC={rpc.calls} GT={http.calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
