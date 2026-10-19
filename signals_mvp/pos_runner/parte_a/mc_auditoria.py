"""DIAGNOSTICO 3 (somente leitura; ZERO escrita no SQLite; so leitura/cache de candles como qualquer comando
oficial ja faz): audita a conversao preco->MC em runners DBC suspeitos, comparando 3 fontes independentes por
pool:
  (1) "nosso" -- exatamente o que a producao gravou (`load_bars`, mesmo default side="base" sem verificar);
  (2) GT direto em USD (`currency=usd`, token=<lado REAL resolvido via /pools/{addr}>) -- isola se o erro e
      na NOSSA conversao (quote-reference/side) ou vem de cima (dado do proprio GT pra esse pool/token);
  (3) RPC `getTokenSupply` (decimals + supply reais, independente do GT).
Classifica cada pool em (a) escala constante, (b) escala variavel ao longo do tempo, ou (c) pico espurio
isolado (wick de 1 candle). Nenhuma regra, codigo de producao, banco ou selo e alterado.

Uso (Windows, raiz do repo, venv ativo, POS_RUNNER_RPC_URLS configurado):
    python mc_auditoria.py --periodo discovery --max-chamadas 30
"""
from __future__ import annotations

import argparse
import random
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

from signals_mvp.http import HttpClient, RateLimiter  # noqa: E402
from signals_mvp.pos_runner.candles import OhlcvStore, tf_seconds  # noqa: E402
from signals_mvp.pos_runner.parte_a.cli import DOCS, WORK  # noqa: E402
from signals_mvp.pos_runner.parte_a.pipeline import Context, load_bars  # noqa: E402
from signals_mvp.pos_runner.parte_a.plan import load_plan  # noqa: E402
from signals_mvp.pos_runner.parte_a.quotebook import QuoteBook  # noqa: E402
from signals_mvp.pos_runner.parte_a.store import Store  # noqa: E402
from signals_mvp.pos_runner.params import load_params  # noqa: E402
from signals_mvp.pos_runner.solana_rpc import SolanaRpc, endpoints_from_env  # noqa: E402

GT_BASE = "https://api.geckoterminal.com/api/v2"
DAY = 86400
LBC_REPETIDO = 19_958_639.0


class OrcamentoEsgotado(Exception):
    pass


class BudgetedHttp:
    """Mesmo HttpClient da producao, com um teto de chamadas (contagem real, inclusive 429 retentado)."""

    def __init__(self, http: HttpClient, teto: int):
        self.http = http
        self.teto = teto

    def get_json(self, path, params=None, max_wait_s=600.0):
        if self.http.calls >= self.teto:
            raise OrcamentoEsgotado(f"orcamento de {self.teto} chamadas ao GT esgotado")
        return self.http.get_json(path, params, max_wait_s=max_wait_s)

    @property
    def calls(self):
        return self.http.calls

    @property
    def headers(self):
        return self.http.headers

    @property
    def limiter(self):
        return self.http.limiter


def pool_info(http: BudgetedHttp, pool: str) -> dict:
    data = http.get_json(f"networks/solana/pools/{pool}")
    a = data["data"]["attributes"]
    rel = data["data"]["relationships"]
    base = rel["base_token"]["data"]["id"].split("_", 1)[-1]
    quote = rel["quote_token"]["data"]["id"].split("_", 1)[-1]
    return {
        "base": base, "quote": quote,
        "fdv_usd": float(a.get("fdv_usd") or 0) or None,
        "market_cap_usd": float(a.get("market_cap_usd") or 0) or None,
        "base_price_usd": float(a.get("base_token_price_usd") or 0) or None,
        "quote_price_usd": float(a.get("quote_token_price_usd") or 0) or None,
    }


def gt_usd_series(http: BudgetedHttp, pool: str, tf: str, side: str, start_ts: int, end_ts: int) -> list:
    """1 pagina (<=1000 candles), currency=usd, token=<side resolvido> -- preco direto do GT, SEM passar pela
    nossa referencia de cotacao (isola se o erro e nosso ou do proprio GT)."""
    endpoint, aggregate = {"5m": ("minute", 5), "1h": ("hour", 1), "4h": ("hour", 4)}[tf]
    params = {"aggregate": aggregate, "limit": 1000, "before_timestamp": int(end_ts), "currency": "usd", "token": side}
    data = http.get_json(f"networks/solana/pools/{pool}/ohlcv/{endpoint}", params)
    rows = data["data"]["attributes"]["ohlcv_list"] or []
    step = tf_seconds(tf)
    out = [(int(ts), o, h, l, c, v) for ts, o, h, l, c, v in rows if ts >= start_ts - step]
    out.sort()
    return out


def rpc_supply_decimals(rpc: SolanaRpc, mint: str) -> tuple:
    try:
        v = (rpc.call("getTokenSupply", [mint]) or {}).get("value") or {}
        return v.get("decimals"), float(v.get("uiAmountString") or 0) or None
    except Exception as exc:  # falha de RPC: explicito, nunca um palpite
        return None, None


def classify(fator_1: float, fator_peak: float, fator_last: float, nosso_high: float, nosso_close: float,
            gt_high: float, gt_close: float) -> str:
    fatores = [f for f in (fator_1, fator_peak, fator_last) if f is not None and f > 0]
    if not fatores:
        return "sem_dado"
    razao_fatores = max(fatores) / min(fatores)
    media_log_dist_de_1 = max(abs(f - 1.0) for f in fatores)
    nosso_wick = (nosso_high / nosso_close) if nosso_close else None
    gt_wick = (gt_high / gt_close) if gt_close else None
    if media_log_dist_de_1 < 0.5:  # fator ~1 (nossa conversao bate com o GT direto) em todos os pontos
        if nosso_wick and gt_wick and nosso_wick > 3 and gt_wick > 3:
            return "(c) pico espurio isolado (wick de 1 candle, presente nos DOIS lados -- dado do proprio GT)"
        return "sem erro de conversao detectado (fator~1); MC alto pode ser real ou vir de outro lugar"
    if razao_fatores < 3:
        return "(a) escala CONSTANTE (mesmo fator nos 3 pontos) -- provavel bug de conversao fixo, corrigivel"
    return "(b) escala VARIAVEL ao longo do tempo -- nao e um fator fixo, investigar mais"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--periodo", default="discovery", choices=["discovery", "holdout"])
    ap.add_argument("--tf", default="1h", choices=["5m", "1h", "4h"])
    ap.add_argument("--max-chamadas", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--db", default=None)
    ap.add_argument("--cache", default=None)
    args = ap.parse_args()

    plan = load_plan(DOCS / "plano_parte_a.json")
    params = load_params()
    store = Store(Path(args.db) if args.db else WORK / "parte_a.sqlite")
    cache_dir = Path(args.cache) if args.cache else WORK / "ohlcv"
    real_http = HttpClient(GT_BASE, RateLimiter(26, 2, pause_s=30, pause_max_s=240, jitter_s=1.5), 30, name="GeckoTerminal")
    http = BudgetedHttp(real_http, args.max_chamadas)
    # EMENDA (achado no proprio teste deste script): `ohlcv` tem que usar o MESMO `http` orcado -- senao um
    # buraco de cache em `load_bars` (ex.: janela nao coberta) sai pra rede SEM contar no teto de 30 chamadas,
    # e fica reagindo a 429 (pausa de 30s) por minutos sem nunca estourar o orcamento. Com `http` (orcado), a
    # MESMA tentativa de chamada -- inclusive uma retentativa apos 429 -- conta e para cedo.
    ohlcv = OhlcvStore(http, cache_dir)
    quotes = QuoteBook(ohlcv, cache_dir.parent / "referencias_cotacao.json")
    ctx = Context(plan, params, store, ohlcv, quotes, lambda *a: None, lambda m: None, lambda m, s: None)
    rpc = SolanaRpc(endpoints_from_env())

    store.db.row_factory = __import__("sqlite3").Row
    q = ("SELECT g.pool, g.mint, g.quote, g.grad_ts, s.max_mc, s.l_bc, s.created_ts "
        "FROM stage1 s JOIN graduations g ON g.pool=s.pool "
        "WHERE g.period=? AND g.launchpad=? AND s.runner=1 AND s.status='ok'")
    dbc = store.db.execute(q, (args.periodo, "meteora_dbc")).fetchall()
    pump = store.db.execute(q, (args.periodo, "pumpfun")).fetchall()
    store.db.row_factory = None

    rng = random.Random(args.seed)
    por_maxmc = sorted((r for r in dbc if r["max_mc"] is not None), key=lambda r: -r["max_mc"])[:5]
    por_lbc_min = sorted((r for r in dbc if r["l_bc"] is not None), key=lambda r: r["l_bc"])[:4]
    repetido = [r for r in dbc if r["l_bc"] is not None and abs(r["l_bc"] - LBC_REPETIDO) < 1.0][:3]
    faixa_cands = [r for r in dbc if r["l_bc"] is not None and 30_000 <= r["l_bc"] <= 500_000]
    rng.shuffle(faixa_cands)
    faixa = faixa_cands[:3]
    pump_amostra = sorted((r for r in pump if r["max_mc"] is not None), key=lambda r: -r["max_mc"])[:3]

    vistos: dict[str, dict] = {}
    for grupo, rows in (("top_max_mc", por_maxmc), ("min_l_bc", por_lbc_min),
                        (f"l_bc=={LBC_REPETIDO:.0f}", repetido), ("l_bc_30k-500k", faixa), ("pumpfun", pump_amostra)):
        for r in rows:
            vistos.setdefault(r["pool"], {"row": r, "grupos": []})["grupos"].append(grupo)

    print(f"{len(vistos)} pools selecionados (orcamento GT: {args.max_chamadas} chamadas)\n")
    header = (f"{'pool':10} {'grupos':22} {'decimals':8} {'supply':>14} {'lado_prod':9} {'lado_real':9} "
             f"{'L_bc(banco)':>12} {'max_mc(banco)':>14} {'preco_1o':>10} {'preco_pico':>10} "
             f"{'fator@1o':>9} {'fator@pico':>10} {'fator@ult':>9} {'wick_nosso':>10} {'wick_gt':>8} {'classificacao'}")
    print(header)

    for pool, info in vistos.items():
        row = info["row"]
        grupos = ",".join(info["grupos"])
        if http.calls >= args.max_chamadas:
            print(f"{pool[:10]:10} {grupos:22} -- orcamento de GT esgotado, pool pulado --")
            continue
        decimals, supply_rpc = rpc_supply_decimals(rpc, row["mint"])
        supply = supply_rpc or ctx.supply_fn(row["mint"]) or 1.0
        try:
            info_gt = pool_info(http, pool)
        except OrcamentoEsgotado:
            print(f"{pool[:10]:10} {grupos:22} -- orcamento de GT esgotado, pool pulado --")
            continue
        except Exception as exc:
            print(f"{pool[:10]:10} {grupos:22} -- erro no /pools/{{addr}}: {exc} --")
            continue
        lado_real = "base" if info_gt["base"] == row["mint"] else ("quote" if info_gt["quote"] == row["mint"] else "?")

        bars_dict = {"pool": row["pool"], "quote": row["quote"], "period": args.periodo, "grad_ts": row["grad_ts"]}
        try:
            nosso = load_bars(ctx, bars_dict, args.tf, {})
        except Exception as exc:
            print(f"{pool[:10]:10} {grupos:22} -- erro lendo candles do nosso cache: {exc} --")
            continue
        if not nosso:
            print(f"{pool[:10]:10} {grupos:22} -- sem candles em cache (stage2 nao rodou nesse tf) --")
            continue

        peak_bar = max(nosso, key=lambda b: b.high)
        start_ts, end_ts = nosso[0].ts, nosso[-1].ts + tf_seconds(args.tf)
        try:
            gt_series = gt_usd_series(http, pool, args.tf, lado_real if lado_real in ("base", "quote") else "base",
                                      start_ts, end_ts)
        except OrcamentoEsgotado:
            print(f"{pool[:10]:10} {grupos:22} -- orcamento de GT esgotado, pool pulado --")
            continue
        except Exception as exc:
            print(f"{pool[:10]:10} {grupos:22} -- erro no OHLCV usd do GT: {exc} --")
            continue
        gt_by_ts = {ts: (o, h, l, c, v) for ts, o, h, l, c, v in gt_series}

        def gt_mc_em(ts: int) -> tuple:
            g = gt_by_ts.get(ts)
            return (None, None) if g is None else (g[1] * supply, g[3] * supply)   # (high_mc, close_mc)

        nosso_mc_1o = nosso[0].high
        gt_mc_1o_h, gt_mc_1o_c = gt_mc_em(nosso[0].ts)
        nosso_mc_peak = peak_bar.high
        gt_mc_peak_h, gt_mc_peak_c = gt_mc_em(peak_bar.ts)
        nosso_mc_ult = nosso[-1].high
        gt_mc_ult_h, gt_mc_ult_c = gt_mc_em(nosso[-1].ts)

        def fator(nosso_v, gt_v):
            return (nosso_v / gt_v) if (nosso_v and gt_v) else None

        f1, fp, fu = fator(nosso_mc_1o, gt_mc_1o_h), fator(nosso_mc_peak, gt_mc_peak_h), fator(nosso_mc_ult, gt_mc_ult_h)
        gt_peak_close = gt_mc_peak_c if gt_mc_peak_c else None
        classe = classify(f1, fp, fu, peak_bar.high, peak_bar.close, gt_mc_peak_h or 0, gt_peak_close or 0)

        def fmt(v):
            return "—" if v is None else (f"{v:.2e}" if abs(v) >= 1e6 or (0 < abs(v) < 1e-3) else f"{v:,.2f}")

        preco_1o = nosso[0].open / supply if supply else None
        preco_pico = peak_bar.high / supply if supply else None
        wick_nosso = (peak_bar.high / peak_bar.close) if peak_bar.close else None
        wick_gt = (gt_mc_peak_h / gt_mc_peak_c) if (gt_mc_peak_h and gt_mc_peak_c) else None

        print(f"{pool[:10]:10} {grupos:22} {str(decimals):8} {fmt(supply):>14} {'base':9} {lado_real:9} "
             f"{fmt(row['l_bc']):>12} {fmt(row['max_mc']):>14} {fmt(preco_1o):>10} {fmt(preco_pico):>10} "
             f"{fmt(f1):>9} {fmt(fp):>10} {fmt(fu):>9} {fmt(wick_nosso):>10} {fmt(wick_gt):>8} {classe}")

    print(f"\nTotal de chamadas ao GT usadas: {http.calls} / {args.max_chamadas}")
    store.close()


if __name__ == "__main__":
    main()
