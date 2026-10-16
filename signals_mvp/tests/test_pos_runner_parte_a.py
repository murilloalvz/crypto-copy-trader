"""Parte A do POS-RUNNER-V0 com universo sintetico (sem rede): plano/sorteio, selagem do holdout, recusa de
vazamento, parada por contagem, retomada, linha de base pareada, metricas e travas do pre-registro."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.enumerate import Graduation, WindowResult
from ..pos_runner.params import Params
from ..pos_runner.parte_a import cli as cli_mod
from ..pos_runner.parte_a.baseline import baseline_mean, run_baselines
from ..pos_runner.parte_a.metrics import (BAND_ORDER, CUTS, candidate, choose_variant, holdout_verdict, path_stats,
                                          summarize, variant_table)
from ..pos_runner.parte_a.pipeline import Context, load_seal, run_period, seal_holdout
from ..pos_runner.parte_a.plan import DAY, PeriodPlan, load_plan, write_plan
from ..pos_runner.parte_a.store import Store
from ..pos_runner.quotes import stable_series
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

    def history(self, pool, tf, start_ts, end_ts=None, currency="usd", side="base"):
        self.calls += 1
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
             no_creation: frozenset[str] = frozenset()) -> Context:
    p = plan()
    store = Store(tmp / "a.sqlite")
    ohlcv = FakeOhlcv(runners)
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

    def test_tampered_seal_is_rejected(self):
        ctx = self.ctx(self.tmp, set())
        seal_holdout(ctx, 1, self.tmp / "selo.json")
        doc = json.loads((self.tmp / "selo.json").read_text())
        doc["graduacoes"].pop()
        (self.tmp / "selo.json").write_text(json.dumps(doc))
        with self.assertRaises(RuntimeError):
            load_seal(self.tmp / "selo.json", ctx, require_commit=False)

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
        self.assertEqual(set(table), {f"{tf}/{v}" for tf in ("5m", "1h", "4h") for v in ("A", "B")})
        self.assertGreater(table["1h/A"]["n"], 0)
        self.assertIn("edge_sobre_base_pct", table["1h/A"])
        self.assertIn("custo_2x", table["1h/A"])
        # resultado completo por faixa de pico e os cortes pre-registrados (atributos)
        st = table["1h/A"]
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
                       "teste(s) de suporte", "do caminho até o pico"):
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
        self.assertEqual(counts["setups_primarios"], {tf: len(pools) - 1 for tf in ("5m", "1h", "4h")})
        run_baselines(ctx, "discovery")
        for pool, tf, n, *_ in ctx.store.setups("discovery"):
            rows = json.loads(ctx.store.get(f"base:{pool}:{tf}:{n}"))
            self.assertNotIn(pools[0], {r["pool"] for r in rows})           # sem criacao tambem nao entra na base


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
