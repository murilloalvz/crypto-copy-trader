"""Parte A do POS-RUNNER-V0 com universo sintetico (sem rede): plano/sorteio, selagem do holdout, recusa de
vazamento, parada por contagem, retomada, linha de base pareada, metricas e travas do pre-registro."""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path

from ..http import ApiError
from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.enumerate import Graduation, WindowResult
from ..pos_runner.examples import EXAMPLES
from ..pos_runner.params import Params
from ..pos_runner.parte_a import cli as cli_mod
from ..pos_runner.parte_a.baseline import baseline_mean, run_baselines
from ..pos_runner.parte_a.metrics import (BAND_ORDER, CUTS, candidate, choose_variant, holdout_verdict, path_stats,
                                          summarize, variant_table)
from ..pos_runner.parte_a.pipeline import (IDADE_FAIXAS, Context, enumerate_windows, load_seal, prefetch_period,
                                            primary_under_window, run_period, seal_holdout)
from ..pos_runner.parte_a.plan import DAY, PeriodPlan, load_plan, write_plan
from ..pos_runner.parte_a.store import Store
from ..pos_runner.quotes import stable_series
from ..util import iso_utc
from .test_pos_runner import textbook

SUPPLY = 1e9
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def plan() -> PeriodPlan:
    return PeriodPlan("2026-10-17", window_minutes=60 * 24 * 5, horizon_days=10, exit_days=9)


class FakeOhlcv:
    """Serie em token de cotacao: runners seguem o padrao de livro (em qualquer tf); os outros ficam parados."""

    network = "solana"

    def __init__(self, runners: set[str]):
        self.runners = runners
        self.calls = 0
        self.grad: dict[str, int] = {}
        self.fail_401: set[str] = set()       # pools cuja data "ja saiu" do alcance gratis do GT (HTTP 401)

    def history(self, pool, tf, start_ts, end_ts=None, currency="usd", side="base"):
        self.calls += 1
        if pool in self.fail_401:
            raise ApiError("http", "GeckoTerminal: HTTP 401", 401)
        step = tf_seconds(tf)
        g = self.grad.get(pool, int(start_ts))
        g -= g % step                       # candles do GeckoTerminal sao alinhados ao timeframe
        if pool in self.runners:
            proto = textbook(start_flat=200).bars
        else:
            proto = [Bar(0, 50_000.0, 50_500.0, 49_500.0, 50_000.0, 100.0)] * 300
        out = []
        k = 0
        while True:          # depois do prototipo o pool segue negociando parado (como na vida real, ate o fim pedido)
            ts = g + k * step
            if ts >= end_ts:
                break
            b = proto[k] if k < len(proto) else Bar(0, proto[-1].close, proto[-1].close, proto[-1].close, proto[-1].close, 50.0)
            out.append(Bar(ts, b.open / SUPPLY, b.high / SUPPLY, b.low / SUPPLY, b.close / SUPPLY, b.volume))
            k += 1
        return out

    def repair(self, *a, **k):
        return 0


class FakeQuotes:
    def series(self, quote, start, end, period_start):
        return stable_series()


CREATED_BEFORE_GRAD = 2.5 * DAY     # criacao 2,5 dias antes da graduacao: o rompimento cai em 2-7 dias nos 3 tfs


def make_ctx(tmp: Path, runners: set[str], per_window: int = 2, extra_pool_in_discovery: str = "",
             no_creation: frozenset[str] = frozenset(), fail_401: frozenset[str] = frozenset()) -> Context:
    p = plan()
    store = Store(tmp / "a.sqlite")
    ohlcv = FakeOhlcv(runners)
    ohlcv.fail_401 = set(fail_401)
    creation_calls: list[str] = []

    def created(mint: str, migration_sig: str):
        pool = mint[1:]
        creation_calls.append(pool)
        if pool in no_creation or pool not in ohlcv.grad:
            return None                     # teto de paginas: criacao desconhecida
        return ohlcv.grad[pool] - CREATED_BEFORE_GRAD

    def enum(launchpad, lo, hi):
        res = WindowResult(launchpad, lo, hi)
        for k in range(per_window):
            pool = f"P_{launchpad[:4]}_{lo}_{k}"
            ohlcv.grad[pool] = lo + 60
            res.graduations.append(Graduation(launchpad, f"sig{pool}", lo + 60, 1, "MigrateV2", f"M{pool}", USDC, pool))
        if extra_pool_in_discovery and lo < p.periods()["embargo"][0]:
            res.graduations.append(Graduation(launchpad, "x", lo + 60, 1, "MigrateV2", "Mx", USDC, extra_pool_in_discovery))
        return res

    ctx = Context(p, Params(), store, ohlcv, FakeQuotes(), enum, lambda mint: SUPPLY, created)
    ctx.creation_calls = creation_calls      # type: ignore[attr-defined]
    return ctx


class PlanTests(unittest.TestCase):
    def test_periods_ordered_with_embargo_and_deterministic_windows(self):
        p = PeriodPlan("2026-10-17")
        per = p.periods()
        self.assertLess(per["discovery"][1], per["holdout"][0])
        self.assertEqual(per["embargo"][1] - per["embargo"][0], 7 * DAY)
        self.assertEqual(p.windows("discovery"), PeriodPlan("2026-10-17").windows("discovery"))
        self.assertNotEqual(p.windows("discovery")[:5], PeriodPlan("2026-10-17", seed=1).windows("discovery")[:5])
        last_grad = per["holdout"][1]
        freeze = per["holdout"][1] + (p.horizon_days + p.exit_days + p.tail_margin_days) * DAY
        self.assertLessEqual(last_grad + (p.horizon_days + p.exit_days) * DAY, freeze)

    def test_plan_file_roundtrip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plano.json"
            write_plan(PeriodPlan("2026-10-17"), path, "cfg")
            self.assertEqual(load_plan(path), PeriodPlan("2026-10-17"))
            doc = json.loads(path.read_text())
            doc["plano"]["seed"] = 7
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                load_plan(path)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ctxs: list[Context] = []

    def tearDown(self):
        for c in self.ctxs:
            c.store.close()

    def ctx(self, *a, **k) -> Context:
        c = make_ctx(*a, **k)
        self.ctxs.append(c)
        return c

    def test_seal_then_discovery_refuses_holdout_pools(self):
        ctx = self.ctx(self.tmp, set())
        doc = seal_holdout(ctx, 2, self.tmp / "selo.json")
        self.assertTrue(doc["graduacoes"])
        sealed = load_seal(self.tmp / "selo.json", ctx, require_commit=False)
        leaked = doc["graduacoes"][0]["pool"]
        ctx2 = self.ctx(self.tmp / "b", set(), extra_pool_in_discovery=leaked)
        ctx2.sealed_holdout = sealed
        with self.assertRaises(RuntimeError):
            run_period(ctx2, "discovery", 1, max_windows=1)

    def test_examples_are_excluded_from_both_discovery_and_holdout(self):
        """Os 5 exemplos do professor ficam fora de TODAS as metricas -- inclusive do holdout, nao so do discovery
        (os dois usam a mesma `enumerate_windows`; confirma que o filtro de EXCLUDED nao depende do periodo)."""
        ex = EXAMPLES[0]

        def enum(launchpad, lo, hi):
            res = WindowResult(launchpad, lo, hi)
            res.graduations.append(Graduation(launchpad, "sig", lo + 60, 1, "MigrateV2", ex.mint, USDC, ex.pool))
            return res

        for period in ("discovery", "holdout"):
            store = Store(self.tmp / f"excl_{period}.sqlite")
            ctx = Context(plan(), Params(), store, FakeOhlcv(set()), FakeQuotes(), enum, lambda mint: SUPPLY, lambda *a: None)
            self.ctxs.append(ctx)
            enumerate_windows(ctx, period, [0])
            self.assertEqual(ctx.store.graduations(period), [], period)

    def test_out_of_free_range_is_an_explicit_status_never_silent(self):
        """HTTP 401 do GeckoTerminal (janela ja fora dos ~180 dias gratis) vira status explicito, por pool -- nunca
        'sem_dados' generico nem um crash que derruba o resto da coleta (os outros pools da mesma janela seguem)."""
        lo = plan().windows("discovery")[0][0]
        target = f"P_pump_{lo}_0"
        ctx = self.ctx(self.tmp, set(), per_window=1, fail_401={target})
        counts = run_period(ctx, "discovery", target_min_setups=1, max_windows=1)
        self.assertEqual(counts["estagio1"].get("fora_do_alcance_gratis"), 1)
        self.assertEqual(counts["estagio1"].get("ok"), 2)          # raydium_launchlab e meteora_dbc seguiram normal
        st = ctx.store.stage1(target)
        self.assertEqual(st[0], "fora_do_alcance_gratis")
        self.assertIsNone(st[2])                                    # runner desconhecido, nao False
        self.assertEqual(json.loads(st[5])["grad_ts"], lo + 60)     # explicito, por data -- nunca silencioso
        # status terminal: uma 2a chamada (retomada) nao tenta de novo (nao soma mais chamadas de rede a esse pool)
        calls_before = ctx.ohlcv.calls
        from ..pos_runner.parte_a.pipeline import stage1
        row = next(r for r in ctx.store.graduations("discovery") if r["pool"] == target)
        stage1(ctx, row)
        self.assertEqual(ctx.ohlcv.calls, calls_before)

    def test_tampered_seal_is_rejected(self):
        ctx = self.ctx(self.tmp, set())
        seal_holdout(ctx, 1, self.tmp / "selo.json")
        doc = json.loads((self.tmp / "selo.json").read_text())
        doc["graduacoes"].pop()
        (self.tmp / "selo.json").write_text(json.dumps(doc))
        with self.assertRaises(RuntimeError):
            load_seal(self.tmp / "selo.json", ctx, require_commit=False)

    def test_seal_from_an_older_config_version_is_still_accepted_same_plan(self):
        """EMENDA 2026-10-16 (pre-registro secao 10): `seal_holdout` so enumera janelas on-chain (nunca le
        `ctx.params`) -- um selo gravado sob a versao_config ANTERIOR a uma emenda de grade continua valido (so
        o plano/periodo das janelas importa). Um plano diferente (janelas sorteadas diferentes) continua rejeitado."""
        ctx = self.ctx(self.tmp, set())
        seal_holdout(ctx, 1, self.tmp / "selo.json")
        doc = json.loads((self.tmp / "selo.json").read_text())
        doc["versao_config"] = "outra_config_antiga"
        (self.tmp / "selo.json").write_text(json.dumps(doc))
        pools = load_seal(self.tmp / "selo.json", ctx, require_commit=False)   # nao levanta: so provenance mudou
        self.assertTrue(pools)
        doc["versao_plano"] = "outro_plano"
        (self.tmp / "selo.json").write_text(json.dumps(doc))
        with self.assertRaises(RuntimeError):
            load_seal(self.tmp / "selo.json", ctx, require_commit=False)

    def test_restamp_versao_config_refuses_when_params_dependent_tables_are_not_empty(self):
        """`restamp_versao_config` (store.py) e a UNICA forma permitida de trocar a versao_config gravada no meio
        de uma coleta (nunca editar o SQLite na mao). So e aceito quando stage1/stage2/setups/trades estao vazios
        (nada dependente de `ctx.params` existe ainda -- so `graduations`, enumeracao on-chain pura)."""
        ctx = self.ctx(self.tmp, set())
        ctx.store.require("versao_config", ctx.params.version)   # como build_context() faz no cli.py real
        seal_holdout(ctx, 1, self.tmp / "selo.json")   # so grava graduations (period=holdout), nada dependente de params
        self.assertTrue(ctx.store.graduations("holdout"))
        old = ctx.store.restamp_versao_config("nova_config_emendada", "teste: emenda de grade")
        self.assertEqual(old, ctx.params.version)
        self.assertEqual(ctx.store.get("versao_config"), "nova_config_emendada")
        self.assertTrue(ctx.store.graduations("holdout"))   # graduations (params-independente) nao foi tocado
        ctx.store.save_setups("qualquer_pool", "1h", [{"kind": "ENTRADA", "idx": 1, "ts": 1, "decision_ts": 1, "data": {}}])
        with self.assertRaises(RuntimeError):
            ctx.store.restamp_versao_config("outra_config", "nao deveria passar: ha setup gravado")

    def test_count_based_stop_resume_metrics_and_baseline(self):
        windows = plan().windows("discovery")
        runners = {f"P_{lp[:4]}_{windows[w][0]}_{k}" for w in range(3) for lp in ("pumpfun", "raydium_launchlab") for k in range(2)}
        ctx = self.ctx(self.tmp, runners)
        counts = run_period(ctx, "discovery", target_min_setups=4, max_windows=10)
        stop = json.loads(ctx.store.get("discovery:parada"))
        self.assertEqual(stop["motivo"], "contagem")
        self.assertLessEqual(stop["janelas"], 3)
        self.assertTrue(all(v >= 4 for v in counts["setups_primarios"].values()), counts)
        self.assertEqual(counts["runners"], sum(1 for p in runners if ctx.store.stage1(p) is not None))
        n_trades = ctx.store.db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        run_period(ctx, "discovery", target_min_setups=4, max_windows=10)      # retomada: idempotente, mesmo ponto de parada
        self.assertEqual(ctx.store.counts("discovery"), counts)
        self.assertEqual(ctx.store.db.execute("SELECT COUNT(*) FROM trades").fetchone()[0], n_trades)
        self.assertEqual(json.loads(ctx.store.get("discovery:parada")), stop)
        self.assertGreater(run_baselines(ctx, "discovery"), 0)
        pool, tf, n, *_ = ctx.store.setups("discovery", "1h")[0]
        self.assertIsNotNone(baseline_mean(ctx, pool, tf, n, "A"))
        table = variant_table(ctx, "discovery")
        self.assertEqual(set(table), {f"{tf}/{v}/{m}/{a}" for tf in ("5m", "1h", "4h") for v in ("A", "B")
                                      for m in ("extremos", "fechamentos") for a in ("2-7", "1-10")})
        self.assertGreater(table["1h/A/extremos/2-7"]["n"], 0)
        self.assertIn("edge_sobre_base_pct", table["1h/A/extremos/2-7"])
        self.assertIn("custo_2x", table["1h/A/extremos/2-7"])
        # resultado completo por faixa de pico e os cortes pre-registrados (atributos)
        st = table["1h/A/extremos/2-7"]
        self.assertEqual(list(st["por_pico"]), ["1-5M"])                    # o padrao de livro tem pico de 1M
        self.assertEqual(st["por_pico"]["1-5M"]["n"], st["n"])
        self.assertIn("custo_2x", st["por_pico"]["1-5M"])
        for name, _key in CUTS:
            self.assertEqual(sum(v["n"] for v in st[name].values()), st["n"], name)
        self.assertEqual(set(st["por_testes"]), {"1"})
        self.assertEqual(set(st["por_S_100k"]), {"sim"})                     # S = 150k
        self.assertEqual(set(st["por_cotacao"]), {"SOL/estavel"})             # cotados em USDC
        self.assertGreater(st["caminho_max"]["n"], 0)
        # idade desde a criacao: so runners (cada mint uma vez) e todos dentro da janela 2-7 dias
        self.assertEqual(sorted(ctx.creation_calls), sorted(p for p in runners if ctx.store.stage1(p) is not None))
        for pool, tf, n, _prim, _ts, ev in ctx.store.setups("discovery"):
            self.assertTrue(2.0 <= json.loads(ev)["data"]["idade_dias"] <= 7.0, (tf, json.loads(ev)["data"]["idade_dias"]))

    def test_report_has_the_bands_the_cuts_and_the_sampled_trades(self):
        from ..pos_runner.parte_a.report import write_report
        windows = plan().windows("discovery")
        runners = {f"P_{lp[:4]}_{windows[w][0]}_{k}" for w in range(2) for lp in ("pumpfun", "raydium_launchlab") for k in range(2)}
        ctx = self.ctx(self.tmp, runners)
        run_period(ctx, "discovery", target_min_setups=4, max_windows=10)
        run_baselines(ctx, "discovery")
        text = write_report(ctx, self.tmp / "rel").read_text(encoding="utf-8")
        for needle in ("## 2. Discovery — as 6 variantes", "Por faixa de pico do runner (resultado completo):", "por_testes",
                       "por_cotacao", "por_S_100k", "por_R_S", "por_volume", "por_power_candle", "sem data de criação on-chain: 0",
                       "teste(s) de suporte", "do caminho até o pico",
                       "por_hora_brt", "por_vol_teste"):   # EMENDA 2026-10-16: atributos secundarios (hora BRT, vol. do teste)
            self.assertIn(needle, text)

    def test_runner_without_creation_date_has_no_primary_setup(self):
        windows = plan().windows("discovery")
        pools = [f"P_{lp[:4]}_{windows[0][0]}_{k}" for lp in ("pumpfun", "raydium_launchlab", "meteora_dbc") for k in range(2)]
        ctx = self.ctx(self.tmp, set(pools), no_creation=frozenset(pools[:1]))
        counts = run_period(ctx, "discovery", target_min_setups=1000, max_windows=1)
        self.assertEqual(counts["runners"], len(pools))
        self.assertEqual(counts["runners_sem_criacao"], 1)
        self.assertEqual(json.loads(ctx.store.stage1(pools[0])[5])["criacao"], "sem_dado")
        self.assertIsNone(ctx.store.stage1(pools[0])[6])
        mine = [row for row in ctx.store.setups("discovery", primary_only=False) if row[0] == pools[0]]
        self.assertTrue(mine)                                               # o detector ve o setup (diagnostico)...
        self.assertTrue(all(row[3] == 0 for row in mine))                   # ...mas sem idade nenhum e primario
        self.assertEqual(counts["setups_primarios"],
                         {tf: len(pools) - 1 for tf in ("5m", "1h", "4h", "5m_fecham", "1h_fecham", "4h_fecham")})
        run_baselines(ctx, "discovery")
        for pool, tf, n, *_ in ctx.store.setups("discovery"):
            rows = json.loads(ctx.store.get(f"base:{pool}:{tf}:{n}"))
            self.assertNotIn(pools[0], {r["pool"] for r in rows})           # sem criacao tambem nao entra na base

    def test_primary_under_window_is_recomputed_independently_per_idade_faixa(self):
        """EMENDA 2026-10-16 (grade de 24): 'primeiro setup por token' NAO herda a primaria de uma faixa de idade
        para outra -- cada janela de idade reclassifica do zero a partir do `idade_dias` ja gravado no setup (nunca
        roda o detector de novo). Um pool com uma entrada no dia 1,5 (fora de 2-7, dentro de 1-10) e outra no dia 3
        (dentro das duas, na mesma zona/tf): sob 2-7 a primaria e a do dia 3 (a de 1,5 nem conta, fica de fora);
        sob 1-10 a primaria passa a ser a do dia 1,5 -- a do dia 3 NUNCA e herdada como primaria, vira reentrada
        sob essa janela mais larga."""
        period = "discovery"
        pool, tf_label = "P_pool_idade_x", "1h"
        store = Store(self.tmp / "primary_window.sqlite")
        self.addCleanup(store.close)
        with store.db:
            store.db.execute("INSERT INTO graduations VALUES (?,?,?,?,?,?,?,?,?)",
                             (pool, "MINTX", USDC, "pumpfun", 0, "sig", period, 0, "ok"))
        store.save_setups(pool, tf_label, [
            {"kind": "ENTRADA", "idx": 1, "ts": 1, "decision_ts": 1, "data": {"idade_dias": 1.5}},  # dia 1,5
            {"kind": "ENTRADA", "idx": 2, "ts": 2, "decision_ts": 2, "data": {"idade_dias": 3.0}},  # dia 3
        ])
        stub = types.SimpleNamespace(store=store)
        lo27, hi27 = IDADE_FAIXAS["2-7"]
        lo110, hi110 = IDADE_FAIXAS["1-10"]
        prim_27 = primary_under_window(stub, period, tf_label, lo27, hi27)
        prim_110 = primary_under_window(stub, period, tf_label, lo110, hi110)
        self.assertEqual(prim_27, {(pool, tf_label, 2)})       # 1,5 fica fora de [2,7]: a primaria e a do dia 3
        self.assertEqual(prim_110, {(pool, tf_label, 1)})      # 1,5 entra em [1,10] e e a 1a: vira a primaria
        self.assertNotIn((pool, tf_label, 2), prim_110)        # a do dia 3 NUNCA e herdada como primaria sob 1-10


class UsdGapTests(unittest.TestCase):
    def test_candle_without_usd_stops_the_series_instead_of_becoming_a_fake_flat_candle(self):
        from ..pos_runner.parte_a.pipeline import _mc_bars
        from ..pos_runner.quotes import UsdSeries
        ctx = make_ctx(Path(tempfile.mkdtemp()), {"P"})
        ctx.ohlcv.grad["P"] = 1_789_000_000 - 1_789_000_000 % 3600
        g = ctx.ohlcv.grad["P"]
        usd = UsdSeries([g + k * 3600 for k in range(10)], [1.0] * 10, [1.0] * 10)   # cotacao so nas 10 primeiras horas
        row = {"pool": "P", "grad_ts": g}
        stats: dict = {}
        bars = _mc_bars(ctx, row, "1h", g + 40 * 3600, SUPPLY, usd, stats)
        # 6 h de folga depois da ultima hora com cotacao; dali em diante a serie PARA (nada inventado)
        self.assertEqual(len(bars), 16)
        self.assertFalse(any(b.filled for b in bars))
        self.assertEqual(stats["sem_usd_cortados"], 40 - 16)
        ctx.store.close()


class MetricsTests(unittest.TestCase):
    def test_summarize(self):
        s = summarize([0.5, -0.2, -0.1, 0.3, -0.4, -0.1])
        self.assertAlmostEqual(s["ev_liq_pct"], 100 * 0.0 / 6)
        self.assertAlmostEqual(s["pf"], 0.8 / 0.8)
        self.assertEqual(s["pior_sequencia_perdas"], 2)
        self.assertAlmostEqual(s["acerto_pct"], 100 * 2 / 6)

    def test_choose_variant_tie_goes_to_1h_a_and_criteria(self):
        table = {"5m/A": {"n": 40, "ev_liq_pct": 5.0}, "1h/A": {"n": 40, "ev_liq_pct": 5.0}, "4h/B": {"n": 40, "ev_liq_pct": 1.0}}
        pick, _ = choose_variant(table)
        self.assertEqual(pick, "1h/A")
        ok = candidate({"n": 30, "ev_liq_pct": 1.0, "pf": 1.2, "edge_sobre_base_pct": 0.5})
        self.assertTrue(ok["candidato"])
        self.assertFalse(candidate({"n": 29, "ev_liq_pct": 1.0, "pf": 1.2, "edge_sobre_base_pct": 0.5})["candidato"])
        self.assertEqual(holdout_verdict({"n": 29, "ev_liq_pct": 9, "pf": 3}), "INCONCLUSIVE")     # minimo 30 (conservador)
        self.assertEqual(holdout_verdict({"n": 30, "ev_liq_pct": -1, "pf": 3}), "FAIL")
        self.assertEqual(holdout_verdict({"n": 30, "ev_liq_pct": 2, "pf": 1.5}), "PASS")

    def test_path_stats_and_band_order(self):
        st = path_stats([{"max_caminho_pct": v} for v in (10.0, 50.0, 100.0, 120.0)] + [{"max_caminho_pct": None}])
        self.assertEqual(st["n"], 4)
        self.assertAlmostEqual(st["mediana_pct"], 75.0)
        self.assertAlmostEqual(st["chegou_a_metade_pct"], 75.0)
        self.assertAlmostEqual(st["chegou_ao_topo_pct"], 50.0)
        self.assertEqual(path_stats([]), {"n": 0})
        self.assertEqual(BAND_ORDER[:4], ("300-500k", "500k-1M", "1-5M", ">5M"))
        p = Params()
        self.assertEqual([p.peak_band(x) for x in (300_000, 499_999, 500_000, 999_999, 1_000_000, 5_000_000)],
                         ["300-500k", "300-500k", "500k-1M", "500k-1M", "1-5M", ">5M"])


class PrefetchTests(unittest.TestCase):
    """Decisao operacional de 2026-10-16: baixar o bruto com a janela mais ANTIGA do calendario primeiro (nunca pela
    ordem sorteada), para nunca perder dado por causa do limite movel de ~180 dias do GeckoTerminal."""

    def test_prefetch_enumerates_chronologically_not_by_the_seeded_shuffle(self):
        tmp = Path(tempfile.mkdtemp())
        seen: list[int] = []

        def enum(launchpad, lo, hi):
            seen.append(lo)
            return WindowResult(launchpad, lo, hi)

        store = Store(tmp / "p.sqlite")
        ctx = Context(plan(), Params(), store, FakeOhlcv(set()), FakeQuotes(), enum, lambda mint: SUPPLY, lambda *a: None)
        prefetch_period(ctx, "discovery", max_windows=6)
        pumpfun_order = seen[0::3]                               # 3 launchpads por janela, nesta ordem fixa
        self.assertEqual(pumpfun_order, sorted(pumpfun_order))    # cronologico, mais antiga primeiro
        shuffled = [w[0] for w in plan().windows("discovery")[:6]]
        self.assertNotEqual(shuffled, sorted(shuffled))           # confirma que a ordem sorteada NAO e cronologica
        store.close()

    def test_run_period_after_a_full_prefetch_makes_no_new_network_call(self):
        """O prefetch so GRAVA bruto; a parada por contagem continua na ordem sorteada (`run_period`), e depois de um
        prefetch COMPLETO (as mesmas janelas, so em outra ordem) ela roda so sobre o cache (nenhuma chamada nova de
        RPC ou GeckoTerminal), porque a ordem de visita nao muda QUAIS janelas sao enumeradas -- so QUANDO."""
        tmp = Path(tempfile.mkdtemp())
        total = len(plan().windows("discovery"))
        ctx = self.ctxPatch(tmp, set())
        prefetch_period(ctx, "discovery")                          # todas as janelas, cronologico
        enum_calls_before, gt_calls_before = ctx.enumerate_calls, ctx.ohlcv.calls
        self.assertGreater(enum_calls_before, 0)
        run_period(ctx, "discovery", target_min_setups=10**9, max_windows=total)   # mesmas janelas, ordem sorteada
        self.assertEqual(ctx.enumerate_calls, enum_calls_before)   # enumerate_windows pulou tudo (window_done)
        self.assertEqual(ctx.ohlcv.calls, gt_calls_before)         # stage1 veio 100% do cache do estagio
        ctx.store.close()

    def test_stage1_stage2_are_interleaved_per_window_not_only_after_all_enumeration(self):
        """Reforco de 2026-10-16 (prioridade do discovery antigo): o OHLCV da janela mais antiga precisa comecar
        ANTES de terminar a enumeracao do periodo inteiro -- senao "mais antiga primeiro" so vale pra enumeracao
        (RPC, sem o limite de ~180 dias), e o que realmente tem o limite (o OHLCV) só comecaria depois de
        enumerar tudo, tarde demais pras janelas mais proximas do limite."""
        tmp = Path(tempfile.mkdtemp())
        windows = plan().windows("discovery")
        lo = min(w[0] for w in windows)                       # cronologicamente a 1a (nao a 1a do sorteio)
        runners = {f"P_pump_{lo}_0"}
        ctx = make_ctx(tmp, runners, per_window=1)
        eventos: list[dict] = []
        captured: list[tuple[int, int, int]] = []
        prefetch_period(ctx, "discovery", max_windows=5,
                        progress=lambda e: (eventos.append(e), captured.append((e["janelas_feitas"], e["de"], ctx.ohlcv.calls))))
        first_feita, first_de, first_calls = captured[0]
        self.assertEqual(first_feita, 1)
        self.assertLess(first_feita, first_de)       # ainda faltam janelas
        self.assertGreater(first_calls, 0)           # o OHLCV do runner da 1a janela JA rodou
        self.assertIn("dias_restantes_gt", eventos[0])
        ctx.store.close()

    def test_prefetch_reports_dates_lost_to_the_free_window_explicitly(self):
        tmp = Path(tempfile.mkdtemp())
        windows = plan().windows("discovery")
        lo = min(w[0] for w in windows)                       # cronologicamente a 1a (nao a 1a do sorteio)
        target = f"P_pump_{lo}_0"
        ctx = make_ctx(tmp, set(), per_window=1, fail_401={target})
        resumo = prefetch_period(ctx, "discovery", max_windows=1)
        self.assertEqual(resumo["fora_do_alcance_gratis"], [iso_utc(lo + 60)])
        ctx.store.close()

    @staticmethod
    def ctxPatch(tmp: Path, runners: set[str]) -> Context:
        ctx = make_ctx(tmp, runners, per_window=1)
        real_enum = ctx.enumerate_fn
        ctx.enumerate_calls = 0

        def counted(lp, lo, hi):
            ctx.enumerate_calls += 1
            return real_enum(lp, lo, hi)

        ctx.enumerate_fn = counted
        return ctx


class RpcPaceTests(unittest.TestCase):
    def test_rpc_per_min_is_configurable_and_infra_only(self):
        """Ritmo-teto do RPC pago (QuickNode etc.) vem de POS_RUNNER_RPC_PER_MIN; sem ela, o padrao continua 100
        (igual antes desta decisao operacional -- nao muda nenhuma regra, so a velocidade do download)."""
        import os
        from ..pos_runner.parte_a.cli import ENV_RPC_PER_MIN, build_context

        tmp = Path(tempfile.mkdtemp())
        old_env = os.environ.get(ENV_RPC_PER_MIN)
        try:
            os.environ.pop(ENV_RPC_PER_MIN, None)
            _ctx, rpc_default, _http = build_context(tmp / "a", plan())
            self.assertEqual(rpc_default.limiters[list(rpc_default.limiters)[0]].max_per_min, 100.0)
            os.environ[ENV_RPC_PER_MIN] = "900"
            _ctx2, rpc_fast, _http2 = build_context(tmp / "b", plan())
            self.assertEqual(rpc_fast.limiters[list(rpc_fast.limiters)[0]].max_per_min, 900.0)
        finally:
            if old_env is None:
                os.environ.pop(ENV_RPC_PER_MIN, None)
            else:
                os.environ[ENV_RPC_PER_MIN] = old_env


class BankrollTests(unittest.TestCase):
    """Addendum de relatorio (2026-10-16): tabela de trades + gestao de banca por ajuste -- banca US$100, posicao
    5%, no maximo 3 abertas, stop diario/semanal. NAO muda regra nem escolha da variante (so uma leitura extra
    dos MESMOS trades fechados, com o tamanho real da posicao)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ctxs: list[Context] = []

    def tearDown(self):
        for c in self.ctxs:
            c.store.close()

    def ctx(self, *a, **k) -> Context:
        c = make_ctx(*a, **k)
        self.ctxs.append(c)
        return c

    def _four_simultaneous_entries(self):
        """4 pools com a MESMA graduacao (mesmo padrao sintetico): entradas identicas no tempo, 1h/A."""
        windows = plan().windows("discovery")
        lo = windows[0][0]
        runners = {f"P_pump_{lo}_{k}" for k in range(4)}
        ctx = self.ctx(self.tmp, runners, per_window=4)
        run_period(ctx, "discovery", target_min_setups=1, max_windows=1)
        return ctx

    def test_limit_of_three_open_positions_and_bankroll_compounding(self):
        from ..pos_runner.parte_a.bankroll import COLUMNS, BankrollParams, simulate_bankroll

        ctx = self._four_simultaneous_entries()
        # desliga o stop diario/semanal para isolar so a trava de 3 posicoes abertas
        folgado = BankrollParams(stop_diario_frac=1.0, stop_diario_perdas_seguidas=99, stop_semanal_frac=1.0)
        rows, resumo = simulate_bankroll(ctx, "discovery", "1h", "extremos", "2-7", "A", folgado)
        self.assertEqual(len(rows), 4)                       # 4 entradas identicas no tempo (mesmo pool pattern)
        self.assertEqual(set(rows[0]), set(COLUMNS))
        motivos = [r["motivo_saida"] for r in rows]
        self.assertEqual(motivos.count("pulado: limite"), 1)   # so 3 cabem ao mesmo tempo
        reais = [r for r in rows if r["resultado_usd"] is not None]
        self.assertEqual(len(reais), 3)
        self.assertEqual(resumo["n_trades"], 3)
        banca = 100.0
        for r in reais:
            self.assertAlmostEqual(r["tamanho_posicao_usd"], banca * 0.05, places=6)
            banca += r["resultado_usd"]
            self.assertAlmostEqual(r["banca_depois_usd"], banca, places=6)
        self.assertAlmostEqual(resumo["banca_final_usd"], banca, places=6)
        self.assertEqual(resumo["pct_com_lucro"], 100.0 * sum(r["resultado_usd"] > 0 for r in reais) / 3)
        # a linha pulada nao entra no resumo nem muda a banca
        pulada = next(r for r in rows if r["motivo_saida"] == "pulado: limite")
        self.assertIsNone(pulada["resultado_usd"])
        self.assertIsNone(pulada["banca_depois_usd"])

    def test_daily_stop_after_three_losses_pauses_the_rest_of_the_day(self):
        from ..pos_runner.parte_a.bankroll import simulate_bankroll

        ctx = self._four_simultaneous_entries()
        rows, resumo = simulate_bankroll(ctx, "discovery", "1h", "extremos", "2-7", "A")   # parametros padrao: 3 perdas seguidas
        reais = [r for r in rows if r["resultado_usd"] is not None]
        self.assertEqual(len(reais), 3)
        self.assertTrue(all(r["resultado_usd"] < 0 for r in reais), reais)   # o padrao sintetico perde aqui (saida "tempo")
        self.assertEqual(rows[3]["motivo_saida"], "pulado: stop diário")     # 3 perdas seguidas pausaram o dia
        self.assertEqual(resumo["n_trades"], 3)

    def test_write_bankroll_reports_only_for_periods_already_run(self):
        from ..pos_runner.parte_a.bankroll import AJUSTES, write_bankroll_reports

        windows = plan().windows("discovery")
        runners = {f"P_{lp[:4]}_{windows[0][0]}_{k}" for lp in ("pumpfun", "raydium_launchlab") for k in range(2)}
        ctx = self.ctx(self.tmp, runners)
        run_period(ctx, "discovery", target_min_setups=1, max_windows=1)
        out = write_bankroll_reports(ctx, self.tmp / "docs")
        self.assertEqual(len(out["arquivos_csv"]), len(AJUSTES) + 2)          # 24 combinacoes + 2 de diagnostico; so discovery
        self.assertTrue(all("discovery_" in p for p in out["arquivos_csv"]))
        path = Path(out["arquivos_csv"][0])
        self.assertTrue(path.exists())
        header = path.read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("lucro_liquido_%", header)
        self.assertIn("banca_depois_usd", header)

    def test_token_name_fetch_failure_is_explicit_never_a_crash(self):
        from ..pos_runner.parte_a.bankroll import _token_name

        ctx = self.ctx(self.tmp, set())
        self.assertIsNone(_token_name(ctx, "qualquer_pool"))   # FakeOhlcv nao tem .http: cai no fallback, sem crash

    def test_ledger_state_round_trip_survives_a_restart(self):
        """A Parte B persiste o estado do ledger entre reinicios (BankrollState.to_json/from_json); restaurar um
        estado no meio da serie precisa continuar EXATAMENTE como se nunca tivesse parado."""
        from ..pos_runner.bankroll import BankrollLedger, BankrollState
        from ..pos_runner.detector import Event
        from ..pos_runner.parte_a.pipeline import load_bars
        from ..pos_runner.quotes import SOL_MINT

        ctx = self._four_simultaneous_entries()
        prim = ctx.store.setups("discovery", "1h", primary_only=True)
        closed = {(r[0], r[1], r[2]) for r in ctx.store.trades("discovery", "setup") if r[3] == "A" and r[4] == "fechado"}
        grads = {g["pool"]: g for g in ctx.store.graduations("discovery")}
        sol_at = ctx.usd(SOL_MINT, "discovery").at
        entradas = []
        for r in sorted((r for r in prim if (r[0], r[1], r[2]) in closed), key=lambda r: r[4]):
            g = grads[r[0]]
            bars = load_bars(ctx, g, "1h")
            d = json.loads(r[5])
            ev = Event(kind=d["kind"], idx=d["idx"], ts=d["ts"], decision_ts=d["decision_ts"], data=d["data"])
            meta = {"token": None, "contrato": g["mint"], "launchpad": g["launchpad"], "tf": "1h", "saida": "A"}
            entradas.append((bars, ev, meta))
        self.assertEqual(len(entradas), 4)

        continuo = BankrollLedger(ctx.params, ctx.costs)
        linhas_continuo = [continuo.step(bars, ev, "A", "pumpswap", None, sol_at, meta) for bars, ev, meta in entradas]

        # restaura no meio: processa 2, serializa, recria o ledger do JSON, processa o resto
        reiniciado = BankrollLedger(ctx.params, ctx.costs)
        linhas_reiniciado = [reiniciado.step(*entradas[0][:2], "A", "pumpswap", None, sol_at, entradas[0][2]),
                              reiniciado.step(*entradas[1][:2], "A", "pumpswap", None, sol_at, entradas[1][2])]
        estado_salvo = reiniciado.state.to_json()
        retomado = BankrollLedger(ctx.params, ctx.costs, state=BankrollState.from_json(estado_salvo))
        linhas_reiniciado += [retomado.step(*entradas[2][:2], "A", "pumpswap", None, sol_at, entradas[2][2]),
                              retomado.step(*entradas[3][:2], "A", "pumpswap", None, sol_at, entradas[3][2])]

        self.assertEqual(linhas_continuo, linhas_reiniciado)
        self.assertEqual(continuo.state.resumo(), retomado.state.resumo())


class GateTests(unittest.TestCase):
    def test_preregistration_gate(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "prereg.md"
            doc.write_text("Status: **RASCUNHO — NAO CONGELADO.** hash abc123\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cli_mod.check_preregistration(doc, "abc123")
            doc.write_text("Status: **PRE-REGISTRADO**. config hash `zzz`\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cli_mod.check_preregistration(doc, "abc123")
            doc.write_text("Status: **PRE-REGISTRADO**. config hash `abc123`\n", encoding="utf-8")
            cli_mod.check_preregistration(doc, "abc123")

    def test_only_the_status_line_opens_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "prereg.md"
            # o texto de um rascunho pode citar o status final e o hash: a trava le so a linha de status
            doc.write_text("# x\n\nStatus: **RASCUNHO PRONTO PARA CONGELAR.** hash `abc123`\n\n"
                           "Com o OK: `Status: **PRE-REGISTRADO**` + hash `abc123`.\nStatus: **PRE-REGISTRADO**\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cli_mod.check_preregistration(doc, "abc123")
            from ..pos_runner.live import config_status
            self.assertEqual(config_status("abc123", doc), "rascunho")
            for status in ("**PRE-REGISTRADO? NÃO**", "**PRE-REGISTRADOS na fila**", "PRE-REGISTRADO"):
                doc.write_text(f"Status: {status} config `abc123`\n", encoding="utf-8")
                with self.assertRaises(SystemExit, msg=status):
                    cli_mod.check_preregistration(doc, "abc123")
            doc.write_text("# x\n\nStatus: **PRE-REGISTRADO** (2026-10-20), config `abc123`\n", encoding="utf-8")
            cli_mod.check_preregistration(doc, "abc123")
            self.assertEqual(config_status("abc123", doc), "pre-registrada")

    def test_shipped_preregistration_is_frozen_with_the_live_config_hash(self):
        """Congelado em 2026-10-16: o pre-registro do repo abre a trava com o hash da config em uso, mas continua
        recusando qualquer outro hash (protege contra config e pre-registro saindo de sincronia)."""
        cli_mod.check_preregistration(cli_mod.PREREG, Params().version)
        with self.assertRaises(SystemExit):
            cli_mod.check_preregistration(cli_mod.PREREG, "outro_hash_qualquer")


if __name__ == "__main__":
    unittest.main()
