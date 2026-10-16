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

from ...util import short_hash
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
                                   "erro": res.error, "contas": list(res.accounts)})
            new += len(grads) if status == "ok" else 0
    return new


# ---------------------------------------------------------------------------
# estagios de preco
# ---------------------------------------------------------------------------


def _mc_bars(ctx: Context, row: Any, tf: str, end_ts: int, supply: float, usd: UsdSeries,
             stats: Optional[dict] = None) -> list[Bar]:
    """Candles de MC. A serie PARA no 1o candle sem cotacao/USD no fechamento (como na Parte B, que espera): o candle
    real nunca e trocado por um candle plano inventado. `fill_gaps` so preenche intervalos sem negocio no GT."""
    raw = ctx.ohlcv.history(row["pool"], tf, row["grad_ts"], end_ts, currency="token")
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
    if done is not None and done[0] in ("ok", "sem_referencia", "sem_supply", "sem_dados"):
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


def stage2_bars(ctx: Context, row: Any) -> dict[str, list[Bar]]:
    """5m/1h/4h de graduacao ate graduacao + horizonte + saida; o 5m e conferido contra o 1h (buracos rebaixados)."""
    out: dict[str, list[Bar]] = {}
    h1_raw = ctx.ohlcv.history(row["pool"], "1h", row["grad_ts"], series_end(ctx, row, "1h"), currency="token")
    for tf in TFS:
        holes = 0
        if tf == "5m":
            end = series_end(ctx, row, tf)
            raw = ctx.ohlcv.history(row["pool"], tf, row["grad_ts"], end, currency="token")
            h1_cut = [b for b in h1_raw if b.ts < end]
            gaps = missing_windows(raw, tf, h1_cut, "1h")
            if gaps:
                ctx.ohlcv.repair(row["pool"], tf, gaps, currency="token")
                raw = ctx.ohlcv.history(row["pool"], tf, row["grad_ts"], end, currency="token")
                holes = len(missing_windows(raw, tf, h1_cut, "1h"))
        cut: dict = {}
        bars = load_bars(ctx, row, tf, cut)
        status = "ok" if holes == 0 and bars else ("buracos" if holes else "sem_dados")
        ctx.store.save_stage2(row["pool"], tf, status, len(bars), holes, cut)
        out[tf] = bars
    return out


def detect_and_trade(ctx: Context, row: Any, bars: dict[str, list[Bar]]) -> dict[str, int]:
    """Detector em cada tf (so sinais ate graduacao + horizonte) + trades A/B (custo 1x e 2x) de cada entrada."""
    st = ctx.store.stage1(row["pool"])
    l_bc = st[3]
    sol = ctx.usd("So11111111111111111111111111111111111111112", row["period"])
    sol_at = sol.at if sol else (lambda t: None)
    dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
    limit = row["grad_ts"] + ctx.plan.horizon_days * DAY
    counts = {}
    for tf, tf_bars in bars.items():
        if ctx.store.stage2(row["pool"], tf)[0] != "ok":
            counts[tf] = 0
            continue
        det = run(tf_bars, ctx.params, tf, l_bc, row["grad_ts"], st[6])
        entries = [e for e in det.events if e.kind == "ENTRADA" and e.decision_ts <= limit]
        ctx.store.save_setups(row["pool"], tf, [{"kind": e.kind, "idx": e.idx, "ts": e.ts, "decision_ts": e.decision_ts, "data": e.data} for e in entries])
        for n, e in enumerate(entries, start=1):
            for variant in ("A", "B"):
                for kind, costs in (("setup", ctx.costs), ("setup_custo2x", dataclasses.replace(ctx.costs, multiplier=2.0))):
                    res = simulate(tf_bars, e, variant, ctx.params, costs, dex, l_bc, sol_at)
                    ctx.store.save_trade(row["pool"], tf, n, variant, kind, res, trade_info(e, res))
        counts[tf] = sum(1 for e in entries if e.data.get("primario"))
    return counts


def trade_info(e: Any, res: Any) -> dict[str, Any]:
    """Atributos do setup guardados com cada trade (cortes do relatorio; nenhum deles e filtro)."""
    d = e.data
    return {"entrada": res.entry_price, "stop": res.stop, "alvo": res.tp, "risco": res.risk_frac, "entry_ts": res.entry_ts,
            "ambiguo": res.ambiguous, "P_peak": d["P_peak"], "faixa_pico": d["faixa_pico"], "n_testes": d["n_testes"],
            "S_acima_100k": d["S_acima_100k"], "R_S": d["R_S"], "S_sobre_Lbc": d["S_sobre_Lbc"], "vol_ratio": d["vol_ratio"],
            "power_candle": d["power_candle"], "idade_d": d["idade_dias"], "idade_grad_d": d["idade_grad_dias"],
            "zona_candles": d["box_len"], "max_caminho_pct": res.max_path_pct}


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
        enumerate_windows(ctx, period, [k])
        for row in [r for r in ctx.store.graduations(period, k) if r["ord"] == k]:
            if row["status"] != "ok":
                continue
            status, runner = stage1(ctx, row)
            if status == "ok" and runner:
                bars = stage2_bars(ctx, row)
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


def load_seal(path: Path, ctx: Context, require_commit: bool = True) -> set[str]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc["versao_plano"] != ctx.plan.version or doc["versao_config"] != ctx.params.version:
        raise RuntimeError("selagem do holdout e de outro plano/config")
    pools = sorted({g["pool"] for g in doc["graduacoes"]})
    if short_hash(pools, 32) != doc["hash_pools"]:
        raise RuntimeError("lista do holdout alterada depois de selada (hash nao bate)")
    if require_commit and not is_committed(Path(path)):
        raise RuntimeError(f"selagem do holdout ({path}) ainda nao foi commitada: commite antes do discovery")
    return set(pools)
