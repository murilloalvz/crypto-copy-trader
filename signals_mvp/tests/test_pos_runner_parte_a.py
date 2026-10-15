"""Parte A do POS-RUNNER-V0 com universo sintetico (sem rede): plano/sorteio, selagem do holdout, recusa de
vazamento, parada por contagem, retomada, linha de base pareada, metricas e travas do pre-registro."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.enumerate import Graduation, WindowResult
from ..pos_runner.params import Params
from ..pos_runner.parte_a import cli as cli_mod
from ..pos_runner.parte_a.baseline import baseline_mean, run_baselines
from ..pos_runner.parte_a.metrics import candidate, choose_variant, holdout_verdict, summarize, variant_table
from ..pos_runner.parte_a.pipeline import Context, load_seal, run_period, seal_holdout
from ..pos_runner.parte_a.plan import DAY, PeriodPlan, load_plan, write_plan
from ..pos_runner.parte_a.store import Store
from ..pos_runner.quotes import stable_series
from .test_pos_runner import textbook

SUPPLY = 1e9


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


def make_ctx(tmp: Path, runners: set[str], per_window: int = 2, extra_pool_in_discovery: str = "") -> Context:
    p = plan()
    store = Store(tmp / "a.sqlite")
    ohlcv = FakeOhlcv(runners)

    def enum(launchpad, lo, hi):
        res = WindowResult(launchpad, lo, hi)
        for k in range(per_window):
            pool = f"P_{launchpad[:4]}_{lo}_{k}"
            ohlcv.grad[pool] = lo + 60
            res.graduations.append(Graduation(launchpad, f"sig{pool}", lo + 60, 1, "MigrateV2", f"M{pool}", "USDC", pool))
        if extra_pool_in_discovery and lo < p.periods()["embargo"][0]:
            res.graduations.append(Graduation(launchpad, "x", lo + 60, 1, "MigrateV2", "Mx", "USDC", extra_pool_in_discovery))
        return res

    params = dataclasses.replace(Params(), measure="body", drop_max=0.95, wick_body_mult=1.5, tp_reference="wick",
                                 age_window_days={"5m": None, "1h": None, "4h": None})
    return Context(p, params, store, ohlcv, FakeQuotes(), enum, lambda mint: SUPPLY)


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
        self.assertEqual(holdout_verdict({"n": 19, "ev_liq_pct": 9, "pf": 3}), "INCONCLUSIVE")
        self.assertEqual(holdout_verdict({"n": 25, "ev_liq_pct": -1, "pf": 3}), "FAIL")
        self.assertEqual(holdout_verdict({"n": 25, "ev_liq_pct": 2, "pf": 1.5}), "PASS")


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

    def test_shipped_preregistration_is_still_a_draft(self):
        with self.assertRaises(SystemExit):
            cli_mod.check_preregistration(cli_mod.PREREG, "qualquer")


if __name__ == "__main__":
    unittest.main()
