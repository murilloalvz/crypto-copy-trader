"""Estagios da Parte A (enumeracao -> estagio 1 -> estagio 2 -> detector -> trades), com checkpoint e parada por
CONTAGEM (nunca por retorno). Tudo aqui so le dado publico; nada assina nem envia transacao.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ...http import ApiError
from ...util import iso_utc, short_hash, utc_now
from ..candles import Bar, OhlcvStore, fill_gaps, missing_windows, tf_seconds
from ..costs import CostModel
from ..detector import Event, run
from ..enumerate import LAUNCHPADS, WindowResult, enumerate_window
from ..examples import EXAMPLES
from ..params import Params
from ..quotes import UsdSeries, to_mc_bars
from ..simulate import simulate
from .plan import DAY, PeriodPlan
from .quotebook import QuoteBook
from .store import Store

log = logging.getLogger("signals_mvp.pos_runner.parte_a")

TFS = ("5m", "1h", "4h")
DEX_OF_LAUNCHPAD = {"pumpfun": "pumpswap", "raydium_launchlab": "raydium_cpmm", "meteora_dbc": "meteora_damm_v2"}
# os 5 exemplos do professor (pool de graduacao, pool do handoff e mint) ficam fora de TODAS as metricas
EXCLUDED = {ex.pool for ex in EXAMPLES} | {ex.handoff_pool for ex in EXAMPLES} | {ex.mint for ex in EXAMPLES}


def is_committed(path: Path) -> bool:
    """O arquivo esta no git e sem mudanca local (selagem do holdout precisa estar commitada)."""
    try:
        logged = subprocess.run(["git", "log", "-1", "--format=%H", "--", str(path)], cwd=Path(path).parent,
                                capture_output=True, text=True, timeout=30)
        clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(path)], cwd=Path(path).parent, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(logged.stdout.strip()) and clean.returncode == 0


@dataclass
class Context:
    plan: PeriodPlan
    params: Params
    store: Store
    ohlcv: OhlcvStore
    quotes: QuoteBook
    enumerate_fn: Callable[[str, int, int], WindowResult]          # (launchpad, ini, fim) -> resultado
    supply_fn: Callable[[str], Optional[float]]                     # mint -> supply total
    creation_fn: Callable[[str, str], Optional[float]] = lambda mint, migration_sig: None   # criacao do token (on-chain)
    costs: CostModel = field(default_factory=CostModel)
    sealed_holdout: set[str] = field(default_factory=set)
    _usd: dict[tuple[str, str], Optional[UsdSeries]] = field(default_factory=dict)
    # cache em memoria do nome/simbolo do token por pool (so exibicao no relatorio de banca; nunca filtro)
    _token_names: dict[str, Optional[str]] = field(default_factory=dict)

    def period_span(self, period: str) -> tuple[int, int]:
        lo, hi = self.plan.periods()[period]
        return lo - DAY, hi + (self.plan.horizon_days + self.plan.exit_days + 1) * DAY

    def usd(self, quote: str, period: str) -> Optional[UsdSeries]:
        key = (quote, period)
        if key not in self._usd:
            lo, hi = self.period_span(period)
            self._usd[key] = self.quotes.series(quote, lo, hi, self.plan.periods()[period][0])
        return self._usd[key]


def make_rpc_enumerator(rpc: Any) -> Callable[[str, int, int], WindowResult]:
    return lambda launchpad, lo, hi: enumerate_window(rpc, LAUNCHPADS[launchpad], lo, hi)


# ---------------------------------------------------------------------------
# enumeracao
# ---------------------------------------------------------------------------


def enumerate_windows(ctx: Context, period: str, orders: Iterable[int]) -> int:
    """Enumera as janelas (na ordem do sorteio) que ainda nao foram feitas. Devolve quantas graduacoes novas."""
    windows = ctx.plan.windows(period)
    new = 0
    for k in orders:
        lo, hi = windows[k]
        for lp in ctx.plan.launchpads:
            if ctx.store.window_done(period, k, lp):
                continue
            res = ctx.enumerate_fn(lp, lo, hi)
            status = "ok" if not res.error else "erro"
            grads = [g for g in res.graduations if g.pool and g.pool not in EXCLUDED and (g.mint or "") not in EXCLUDED]
            if period != "holdout":
                leaked = [g.pool for g in grads if g.pool in ctx.sealed_holdout]
                if leaked:
                    raise RuntimeError(f"pool do holdout selado apareceu no {period}: {leaked[:3]}")
            ctx.store.save_window(period, k, lo, hi, lp, status, grads if status == "ok" else [],
                                  {"assinaturas": res.signatures_seen, "tx": res.tx_fetched, "nao_migracao": res.not_migration,
                                   "nao_resolvida": res.nao_resolvida, "erro": res.error, "contas": list(res.accounts)})
            new += len(grads) if status == "ok" else 0
    return new


# ---------------------------------------------------------------------------
# estagios de preco
# ---------------------------------------------------------------------------


def _fetch_history(ctx: Context, pool: str, tf: str, start_ts: int, end_ts: int, stats: Optional[dict] = None,
                   **kwargs: Any) -> list[Bar]:
    """`ctx.ohlcv.history` protegida contra o limite movel de ~180 dias do GeckoTerminal (decisao operacional de
    2026-10-16): HTTP 401 = a janela ja envelheceu e saiu do alcance gratis. Isso NUNCA vira candle vazio em
    silencio nem erro generico: fica marcado (`stats["fora_do_alcance_gratis"]`) para o estagio chamador gravar
    um status explicito, por data, no relatorio."""
    try:
        return ctx.ohlcv.history(pool, tf, start_ts, end_ts, **kwargs)
    except ApiError as exc:
        if exc.status == 401:
            if stats is not None:
                stats["fora_do_alcance_gratis"] = True
            return []
        raise


def _mc_bars(ctx: Context, row: Any, tf: str, end_ts: int, supply: float, usd: UsdSeries,
             stats: Optional[dict] = None) -> list[Bar]:
    """Candles de MC. A serie PARA no 1o candle sem cotacao/USD no fechamento (como na Parte B, que espera): o candle
    real nunca e trocado por um candle plano inventado. `fill_gaps` so preenche intervalos sem negocio no GT."""
    raw = _fetch_history(ctx, row["pool"], tf, row["grad_ts"], end_ts, stats, currency="token")
    step = tf_seconds(tf)
    closed = [b for b in raw if b.ts + step <= end_ts]
    prefix = []
    for b in closed:
        f = usd.at(b.ts + step)
        if f is None or f <= 0:
            break
        prefix.append(b)
    if stats is not None:
        stats["sem_usd_cortados"] = len(closed) - len(prefix)
    mc, _missing = to_mc_bars(prefix, tf, usd, supply)
    return fill_gaps(mc, step)


def stage1(ctx: Context, row: Any) -> tuple[str, Optional[bool]]:
    """1h de graduacao ate graduacao + horizonte: quem chegou a MC >= piso (runner)."""
    done = ctx.store.stage1(row["pool"])
    if done is not None and done[0] in ("ok", "sem_referencia", "sem_supply", "sem_dados", "fora_do_alcance_gratis"):
        return done[0], None if done[2] is None else bool(done[2])
    usd = ctx.usd(row["quote"], row["period"]) if row["quote"] else None
    if usd is None:
        ctx.store.save_stage1(row["pool"], "sem_referencia", None, None, None, None, {"cotacao": row["quote"]})
        return "sem_referencia", None
    supply = ctx.supply_fn(row["mint"])
    if not supply:
        ctx.store.save_stage1(row["pool"], "sem_supply", None, None, None, None, {})
        return "sem_supply", None
    end = row["grad_ts"] + ctx.plan.horizon_days * DAY
    cut: dict = {}
    bars = _mc_bars(ctx, row, "1h", end, supply, usd, cut)
    real = [b for b in bars if not b.filled]
    if not real:
        if cut.get("fora_do_alcance_gratis"):
            ctx.store.save_stage1(row["pool"], "fora_do_alcance_gratis", None, None, None, supply,
                                  {"grad_ts": row["grad_ts"]})
            return "fora_do_alcance_gratis", None
        ctx.store.save_stage1(row["pool"], "sem_dados", None, None, None, supply, {})
        return "sem_dados", None
    max_mc = max(b.high for b in real)
    runner = max_mc >= ctx.params.runner_min_mc
    # idade = desde a CRIACAO do token (regra do operador): so para runners (os unicos que podem ter setup); sem a
    # data a idade fica desconhecida e nenhum setup do token e primario (falta explicita, contada no relatorio)
    created = ctx.creation_fn(row["mint"], row["signature"]) if runner and row["mint"] and row["signature"] else None
    ctx.store.save_stage1(row["pool"], "ok", max_mc, runner, real[0].open, supply,
                          {"candles": len(real), "criacao": "ok" if created else ("sem_dado" if runner else "nao_precisa"),
                           "sem_usd_cortados": cut.get("sem_usd_cortados", 0)},
                          created)
    return "ok", runner


# quanto alem do horizonte cada tf precisa para o trade sair (48 candles: 4h no 5m, 2 dias no 1h, 8 dias no 4h)
EXIT_ALLOWANCE_DAYS = {"5m": 1, "1h": 3, "4h": 9}


def series_end(ctx: Context, row: Any, tf: str) -> int:
    return row["grad_ts"] + (ctx.plan.horizon_days + min(EXIT_ALLOWANCE_DAYS[tf], ctx.plan.exit_days)) * DAY


def load_bars(ctx: Context, row: Any, tf: str, stats: Optional[dict] = None) -> list[Bar]:
    """Candles de MC de um pool ja baixado (do cache em disco; usado tambem pela linha de base)."""
    st = ctx.store.stage1(row["pool"])
    usd = ctx.usd(row["quote"], row["period"])
    if st is None or usd is None or not st[4]:
        return []
    return _mc_bars(ctx, row, tf, series_end(ctx, row, tf), st[4], usd, stats)


def stage2_bars(ctx: Context, row: Any, skip_tfs: frozenset[str] = frozenset()) -> dict[str, list[Bar]]:
    """5m/1h/4h de graduacao ate graduacao + horizonte + saida; o 5m e conferido contra o 1h (buracos rebaixados).

    EMENDA 2026-10-17 (cega a resultado, operacional -- minimizar tempo de download, NUNCA o limiar de parada por
    contagem em si): `skip_tfs` poupa o download dos tfs REAIS ja listados (status explicito `meta_atingida`,
    nunca silencioso; o detector nunca roda neles -- `detect_and_trade` so roda com stage2 'ok'). Quem decide
    `skip_tfs` e o `run_period`, UMA VEZ por janela (nunca no meio dela -- janela inteira sempre processada do
    mesmo jeito, so a PROXIMA janela ve a contagem atualizada; sem isso, pools dentro da MESMA janela ja
    contariam diferente so por ordem de processamento, o que seria mudar resultado, nao so poupar rede). A regra
    de parada oficial continua sem mudar: `min(per_tf) >= target_min_setups` sobre `stop_tfs`. `prefetch_period`
    nunca passa `skip_tfs` (baixa tudo, cronologico, sem saber ainda a contagem da ordem sorteada)."""
    out: dict[str, list[Bar]] = {}
    skip = {tf: tf in skip_tfs for tf in TFS}
    for tf in (tf_ for tf_ in TFS if skip[tf_]):
        ctx.store.save_stage2(row["pool"], tf, "meta_atingida", 0, 0, {"motivo": "setups_primarios[tf] >= meta"})
        out[tf] = []
    h1_stats: dict = {}
    h1_raw: list[Bar] = []
    if not skip["1h"] or not skip["5m"]:
        h1_raw = _fetch_history(ctx, row["pool"], "1h", row["grad_ts"], series_end(ctx, row, "1h"), h1_stats, currency="token")
    for tf in TFS:
        if skip[tf]:
            continue
        holes = 0
        cut: dict = dict(h1_stats) if tf == "1h" else {}
        if tf == "5m":
            end = series_end(ctx, row, tf)
            raw = _fetch_history(ctx, row["pool"], tf, row["grad_ts"], end, cut, currency="token")
            h1_cut = [b for b in h1_raw if b.ts < end]
            gaps = missing_windows(raw, tf, h1_cut, "1h")
            if gaps and not cut.get("fora_do_alcance_gratis"):
                ctx.ohlcv.repair(row["pool"], tf, gaps, currency="token")
                raw = _fetch_history(ctx, row["pool"], tf, row["grad_ts"], end, cut, currency="token")
                holes = len(missing_windows(raw, tf, h1_cut, "1h"))
        bars = load_bars(ctx, row, tf, cut)
        if cut.get("fora_do_alcance_gratis"):
            status = "fora_do_alcance_gratis"
        else:
            status = "ok" if holes == 0 and bars else ("buracos" if holes else "sem_dados")
        ctx.store.save_stage2(row["pool"], tf, status, len(bars), holes, cut)
        out[tf] = bars
    return out


# EMENDA 2026-10-16 (ANTES de qualquer calculo do discovery, novo hash de config): grade ampliada para 24
# combinacoes (tf x saida x medida da queda x idade), pre-registrada como nova hipotese -- motivo: "ampliar a
# grade antes de ver dado". A medida "extremos" mantem o rotulo de tf IGUAL ao de antes (compatibilidade: a parada
# por contagem e a combinacao primaria original -- 1h, A, extremos, 2-7d -- continuam identicas sem nenhuma
# mudanca no codigo que decide a parada); "fechamentos" usa o MESMO candle (nenhuma chamada de rede nova), so com
# outro Params do detector, guardado num rotulo de tf separado.
QUEDA_MEDIDAS = ("extremos", "fechamentos")


def tf_variant(tf: str, medida: str) -> str:
    return tf if medida == "extremos" else f"{tf}_fecham"


def real_tf(label: str) -> str:
    """Rotulo de tf guardado (pode levar o sufixo da medida 'fechamentos') -> tf REAL (5m/1h/4h), o unico que
    `tf_seconds`/o cache de candles conhece -- os dois usam o MESMO candle, so o detector muda."""
    return label[: -len("_fecham")] if label.endswith("_fecham") else label


# idade (EMENDA 2026-10-16): dimensao da grade reclassificada DEPOIS da coleta, a partir do `idade_dias` ja
# gravado em cada evento -- nunca precisa rodar o detector de novo (a idade nao muda o caminho de preco nem a
# decisao de ENTRADA/zona, so se ela conta como "primaria"). "2-7" e a janela original (a mesma que o detector
# usa em `ctx.params.age_window_days`, e por isso a regra de parada por contagem, que conta `primary_flag`
# gravado na coleta, continua sendo exatamente a combinacao primaria original sem nenhuma mudanca de codigo).
IDADE_FAIXAS: dict[str, tuple[float, float]] = {"2-7": (2.0, 7.0), "1-10": (1.0, 10.0)}
PRIMARY_COMBO = "1h/A/extremos/2-7"   # combinacao primaria original; tambem o desempate da escolha


def combo_key(tf: str, variant: str, medida: str, idade_label: str) -> str:
    return f"{tf}/{variant}/{medida}/{idade_label}"


def primary_under_window(ctx: Context, period: str, tf_label: str, idade_min: float, idade_max: float) -> set[tuple[str, str, int]]:
    """(pool, tf_label, n) do 1o setup de cada pool nesse tf_label cuja idade cai em [idade_min, idade_max] --
    reclassifica a PARTIR dos atributos ja gravados (nunca roda o detector de novo), replicando a mesma regra
    ("1o setup elegivel por token e timeframe e primario") que o detector aplica na coleta para a janela original."""
    rows = sorted(ctx.store.setups(period, tf_label, primary_only=False), key=lambda r: (r[0], r[2]))
    done: set[str] = set()
    out: set[tuple[str, str, int]] = set()
    for pool, tf_, n, _prim, _ts, ev in rows:
        if pool in done:
            continue
        idade = json.loads(ev)["data"].get("idade_dias")
        if idade is not None and idade_min <= idade <= idade_max:
            out.add((pool, tf_, n))
            done.add(pool)
    return out


def params_for_medida(params: Params, medida: str) -> Params:
    return params if medida == "extremos" else dataclasses.replace(params, queda_medida="fechamentos")


def detect_and_trade(ctx: Context, row: Any, bars: dict[str, list[Bar]]) -> dict[str, int]:
    """Detector em cada (tf, medida da queda) -- so sinais ate graduacao + horizonte -- + trades A/B (custo 1x e
    2x) de cada entrada."""
    st = ctx.store.stage1(row["pool"])
    l_bc = st[3]
    sol = ctx.usd("So11111111111111111111111111111111111111112", row["period"])
    sol_at = sol.at if sol else (lambda t: None)
    dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
    limit = row["grad_ts"] + ctx.plan.horizon_days * DAY
    counts = {}
    for tf, tf_bars in bars.items():
        if ctx.store.stage2(row["pool"], tf)[0] != "ok":
            for medida in QUEDA_MEDIDAS:
                counts[tf_variant(tf, medida)] = 0
            continue
        for medida in QUEDA_MEDIDAS:
            label = tf_variant(tf, medida)
            params = params_for_medida(ctx.params, medida)
            det = run(tf_bars, params, tf, l_bc, row["grad_ts"], st[6])
            entries = [e for e in det.events if e.kind == "ENTRADA" and e.decision_ts <= limit]
            ctx.store.save_setups(row["pool"], label, [{"kind": e.kind, "idx": e.idx, "ts": e.ts, "decision_ts": e.decision_ts, "data": e.data} for e in entries])
            for n, e in enumerate(entries, start=1):
                for variant in ("A", "B"):
                    for kind, costs in (("setup", ctx.costs), ("setup_custo2x", dataclasses.replace(ctx.costs, multiplier=2.0))):
                        res = simulate(tf_bars, e, variant, params, costs, dex, l_bc, sol_at)
                        ctx.store.save_trade(row["pool"], label, n, variant, kind, res, trade_info(e, res))
            counts[label] = sum(1 for e in entries if e.data.get("primario"))
    return counts


def trade_info(e: Any, res: Any) -> dict[str, Any]:
    """Atributos do setup guardados com cada trade (cortes do relatorio; nenhum deles e filtro)."""
    d = e.data
    return {"entrada": res.entry_price, "stop": res.stop, "alvo": res.tp, "risco": res.risk_frac, "entry_ts": res.entry_ts,
            "ambiguo": res.ambiguous, "P_peak": d["P_peak"], "faixa_pico": d["faixa_pico"], "n_testes": d["n_testes"],
            "S_acima_100k": d["S_acima_100k"], "R_S": d["R_S"], "S_sobre_Lbc": d["S_sobre_Lbc"], "vol_ratio": d["vol_ratio"],
            "power_candle": d["power_candle"], "idade_d": d["idade_dias"], "idade_grad_d": d["idade_grad_dias"],
            "zona_candles": d["box_len"], "max_caminho_pct": res.max_path_pct,
            # EMENDA 2026-10-16 (3 atributos secundarios, nunca filtro -- so estratificacao descritiva no relatorio):
            "teste_vol_ratio": d.get("teste_vol_ratio")}


# ---------------------------------------------------------------------------
# download do bruto em ordem CRONOLOGICA (decisao operacional de 2026-10-16)
# ---------------------------------------------------------------------------


def prefetch_period(ctx: Context, period: str, max_windows: Optional[int] = None,
                    progress: Optional[Callable[[dict], None]] = None) -> dict[str, Any]:
    """Baixa o BRUTO (enumeracao on-chain + candles de estagio 1/2) com a janela mais ANTIGA do calendario primeiro,
    nunca pela ordem sorteada. Motivo: o OHLCV gratis do GeckoTerminal so cobre ~180 dias e esse limite anda 1 dia
    por dia; uma janela antiga que so fosse visitada tarde na ordem sorteada (a que decide o resultado, em
    `run_period`) correria o risco de sair do alcance antes de ser baixada. So GRAVA dado bruto, com checkpoint
    (retomavel): nao roda o detector nem decide parada por contagem. Depois de um prefetch completo, `run_period`
    na ordem sorteada nao faz NENHUMA chamada de rede nova — so le o que ja esta em cache/checkpoint.

    Decisao operacional de 2026-10-16 (reforco): o estagio 1/2 (que de fato consome o OHLCV do GeckoTerminal) e
    feito JANELA POR JANELA, intercalado com a enumeracao, em vez de so depois de enumerar TODAS as janelas do
    periodo -- senao o "mais antigo primeiro" vale so para a enumeracao (RPC, sem o limite de ~180 dias) e o
    OHLCV das graduacoes mais antigas so comecaria a ser baixado depois de terminar a enumeracao inteira do
    periodo (podendo ser tarde demais para as mais proximas do limite)."""
    windows = ctx.plan.windows(period)
    order = sorted(range(len(windows)), key=lambda k: windows[k][0])      # cronologico, mais antiga primeiro
    if max_windows is not None:
        order = order[:max_windows]
    total_grads = 0
    total_runners = 0
    for i, k in enumerate(order, start=1):
        enumerate_windows(ctx, period, [k])
        rows = sorted((r for r in ctx.store.graduations(period, exact_ord=k) if r["status"] == "ok"), key=lambda r: r["grad_ts"])
        for row in rows:
            total_grads += 1
            status, runner = stage1(ctx, row)
            if status == "ok" and runner:
                total_runners += 1
                stage2_bars(ctx, row)
        if progress:
            dias_restantes_gt = (windows[k][0] + ctx.plan.free_days * DAY - utc_now()) / DAY
            progress({"fase": "janela", "periodo": period, "janelas_feitas": i, "de": len(order),
                      "janela_inicio": windows[k][0], "pools_feitos": total_grads, "runners": total_runners,
                      "dias_restantes_gt": round(dias_restantes_gt, 1)})
    perdidas = ctx.store.db.execute(
        "SELECT DISTINCT g.grad_ts FROM stage1 s JOIN graduations g ON g.pool = s.pool "
        "WHERE g.period=? AND s.status='fora_do_alcance_gratis'", (period,)).fetchall()
    return {"janelas": len(order), "graduacoes": total_grads, "runners": total_runners,
            "fora_do_alcance_gratis": sorted(iso_utc(r[0]) for r in perdidas)}


# ---------------------------------------------------------------------------
# laco principal (parada por contagem)
# ---------------------------------------------------------------------------


def run_period(ctx: Context, period: str, target_min_setups: int, max_windows: Optional[int] = None,
               progress: Optional[Callable[[dict], None]] = None, stop_tfs: tuple[str, ...] = TFS) -> dict[str, Any]:
    """Processa janelas na ordem do sorteio ate o MENOR numero de setups primarios entre os tfs de `stop_tfs`
    chegar a `target_min_setups` (ou acabarem as janelas). A regra so olha contagem."""
    windows = ctx.plan.windows(period)
    limit = len(windows) if max_windows is None else min(max_windows, len(windows))
    for k in range(limit):
        # skip_tfs e decidido UMA VEZ por janela, com a contagem de ANTES dela comecar -- nunca no meio (EMENDA
        # 2026-10-17): assim toda janela e processada do mesmo jeito para todos os seus pools, so a PROXIMA
        # janela ve a contagem atualizada. Poupa rede sem mudar quais pools contam dentro de uma mesma janela.
        counts_before = ctx.store.counts(period)["setups_primarios"]
        skip_tfs = frozenset(tf for tf in TFS if counts_before.get(tf, 0) >= target_min_setups)
        enumerate_windows(ctx, period, [k])
        for row in [r for r in ctx.store.graduations(period, k) if r["ord"] == k]:
            if row["status"] != "ok":
                continue
            status, runner = stage1(ctx, row)
            if status == "ok" and runner:
                bars = stage2_bars(ctx, row, skip_tfs=skip_tfs)
                detect_and_trade(ctx, row, bars)
        counts = ctx.store.counts(period)
        per_tf = [counts["setups_primarios"].get(tf, 0) for tf in stop_tfs]
        ctx.store.set(f"{period}:janelas_processadas", str(k + 1))
        if progress:
            progress({"periodo": period, "janela": k + 1, **counts})
        if min(per_tf) >= target_min_setups:
            ctx.store.set(f"{period}:parada", json.dumps({"motivo": "contagem", "janelas": k + 1, "setups": counts["setups_primarios"]}))
            return counts
    ctx.store.set(f"{period}:parada", json.dumps({"motivo": "acabaram_janelas", "janelas": limit}))
    return ctx.store.counts(period)


# ---------------------------------------------------------------------------
# selagem do holdout
# ---------------------------------------------------------------------------


def seal_holdout(ctx: Context, n_windows: int, path: Path) -> dict[str, Any]:
    """Enumera (SEM preco) as primeiras `n_windows` janelas do holdout e grava a lista + hash. Commitar antes do discovery."""
    enumerate_windows(ctx, "holdout", range(min(n_windows, len(ctx.plan.windows("holdout")))))
    rows = ctx.store.graduations("holdout", n_windows - 1)
    pools = sorted({r["pool"] for r in rows})
    doc = {
        "versao_plano": ctx.plan.version,
        "versao_config": ctx.params.version,
        "janelas": n_windows,
        "graduacoes": [{"pool": r["pool"], "mint": r["mint"], "launchpad": r["launchpad"], "grad_ts": r["grad_ts"], "ord": r["ord"]} for r in rows],
        "hash_pools": short_hash(pools, 32),
    }
    Path(path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def restamp_seal_versao_plano(path: Path, new_versao_plano: str, reason: str) -> str:
    """Re-grava SO a chave `versao_plano` do selo do holdout (provenance) -- NUNCA toca `graduacoes`/`hash_pools`.
    Usado quando uma emenda muda o hash do plano sem mudar NENHUM dado do holdout (EMENDA 2026-10-17:
    `discovery_start_override` so recorta o INICIO do discovery; holdout/embargo ficam byte-a-byte iguais, ja
    confirmado pelo teste `test_discovery_start_override_never_touches_embargo_or_holdout`). Confirma o hash dos
    pools ANTES e DEPOIS para provar que os dados nao mudaram. Devolve o `versao_plano` antigo."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    pools = sorted({g["pool"] for g in doc["graduacoes"]})
    if short_hash(pools, 32) != doc["hash_pools"]:
        raise RuntimeError("selo corrompido antes do restamp (hash_pools nao bate) -- recusado")
    old = doc["versao_plano"]
    doc["versao_plano"] = new_versao_plano
    Path(path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    pools_depois = sorted({g["pool"] for g in doc["graduacoes"]})
    if short_hash(pools_depois, 32) != doc["hash_pools"]:
        raise RuntimeError("restamp quebrou o selo (hash_pools nao bate depois) -- nao deveria acontecer")
    log.info("selo do holdout: versao_plano re-gravada (so provenance, graduacoes/hash_pools intocados): "
            "%s -> %s | motivo: %s", old, new_versao_plano, reason)
    return old


def load_seal(path: Path, ctx: Context, require_commit: bool = True) -> set[str]:
    """`versao_plano` tem que bater (janelas sorteadas diferentes = selo de outro periodo). `versao_config` so e
    provenance/auditoria (log se mudou) -- a selagem e so enumeracao on-chain (`seal_holdout`, sem ler `ctx.params`);
    uma emenda que amplia a grade (EMENDA 2026-10-16, pre-registro secao 10: "a selecao de janelas nao depende da
    regra") NUNCA invalida um selo ja comitado."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc["versao_plano"] != ctx.plan.version:
        raise RuntimeError("selagem do holdout e de outro plano")
    if doc["versao_config"] != ctx.params.version:
        log.info("selo do holdout foi gravado sob outra versao_config (%s != %s atual) -- aceito: a selagem e so "
                "enumeracao on-chain, nao depende da regra (pre-registro secao 10)", doc["versao_config"], ctx.params.version)
    pools = sorted({g["pool"] for g in doc["graduacoes"]})
    if short_hash(pools, 32) != doc["hash_pools"]:
        raise RuntimeError("lista do holdout alterada depois de selada (hash nao bate)")
    if require_commit and not is_committed(Path(path)):
        raise RuntimeError(f"selagem do holdout ({path}) ainda nao foi commitada: commite antes do discovery")
    return set(pools)
