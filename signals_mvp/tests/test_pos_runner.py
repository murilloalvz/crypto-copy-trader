"""POS-RUNNER-V0: detector causal (fases 0-3), simulador de saidas A/B e custos. Sem rede."""

from __future__ import annotations

import dataclasses
import unittest

from ..pos_runner.candles import Bar, fill_gaps, missing_windows
from ..pos_runner.costs import CostModel, pumpswap_fee_pct
from ..pos_runner.detector import Detector, is_hammer, run
from ..pos_runner.params import Params, load_params, params_from_dict
from ..pos_runner.quotes import UsdSeries, to_mc_bars
from ..pos_runner.simulate import simulate

H = 3600
T0 = 1_790_000_000 - (1_790_000_000 % H)   # inicio alinhado na hora
GRAD = T0
L_BC = 50_000.0


def flat(ts: int, price: float, vol: float = 1_000.0) -> Bar:
    return Bar(ts, price, price * 1.01, price * 0.99, price, vol)


def hammer(ts: int, low: float, close: float, vol: float = 1_000.0) -> Bar:
    # corpo pequeno perto do topo, pavio inferior longo
    return Bar(ts, close * 0.995, close * 1.005, low, close, vol)


class Series:
    """Monta candles de 1h em sequencia (cada `add` usa o proximo horario)."""

    def __init__(self, start: int = T0):
        self.bars: list[Bar] = []
        self.t = start

    def add(self, o: float, h: float, l: float, c: float, v: float = 1_000.0) -> "Series":
        self.bars.append(Bar(self.t, o, h, l, c, v))
        self.t += H
        return self

    def flat(self, price: float, n: int = 1, v: float = 1_000.0) -> "Series":
        for _ in range(n):
            self.bars.append(flat(self.t, price, v))
            self.t += H
        return self

    def hammer(self, low: float, close: float, v: float = 1_000.0) -> "Series":
        self.bars.append(hammer(self.t, low, close, v))
        self.t += H
        return self


def textbook(box_len: int = 14, wick_low: float = 150_000.0, drop_low: float = 150_000.0, breakout_vol: float = 5_000.0,
             breakout_close: float = 330_000.0, breakout_high: float = 340_000.0, start_flat: int = 50) -> Series:
    """Graduacao a 50k -> runner a 1M -> queda a 150k (-85%) -> repique -> caixa 150k-300k com martelo -> rompimento."""
    s = Series()
    s.flat(60_000, 2)
    for p in (150_000, 300_000, 600_000, 900_000):
        s.add(p * 0.9, p * 1.02, p * 0.88, p)
    s.add(900_000, 1_000_000, 880_000, 950_000)          # pico 1M
    for p in (800_000, 600_000, 400_000, 250_000, 180_000):
        s.add(p * 1.1, p * 1.12, p * 0.97, p)
    s.add(180_000, 182_000, drop_low, 160_000)           # fundo da queda
    s.add(160_000, 200_000, 158_000, 195_000)
    s.add(195_000, 280_000, 190_000, 270_000)            # 1o repique (topo fractal)
    s.add(270_000, 272_000, 220_000, 230_000)
    s.add(230_000, 235_000, 205_000, 210_000)
    # caixa: oscila 200k-300k, com um martelo no suporte
    for k in range(box_len):
        if k == box_len - 3:
            s.hammer(wick_low, 215_000)
        else:
            s.add(240_000, 300_000 if k % 4 == 1 else 260_000, 200_000, 245_000)
    s.add(250_000, breakout_high, 248_000, breakout_close, breakout_vol)   # rompimento
    s.flat(breakout_close, start_flat)
    return s


def params(**over) -> Params:
    base = Params(age_window_days={"5m": None, "1h": None, "4h": None})
    return dataclasses.replace(base, **over)


def kinds(det: Detector) -> list[str]:
    return [e.kind for e in det.events]


class DetectorTests(unittest.TestCase):
    def test_textbook_setup_gives_one_primary_entry(self):
        s = textbook()
        det = run(s.bars, params(), "1h", L_BC, GRAD)
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1, kinds(det))
        e = entries[0]
        self.assertTrue(e.data["primario"])
        self.assertEqual(e.data["P_peak"], 1_000_000)
        self.assertAlmostEqual(e.data["S"], 150_000)
        self.assertEqual(e.data["R"], 300_000)
        self.assertEqual(e.data["n_wicks"], 1)
        self.assertAlmostEqual(e.data["stop"], 150_000 * 0.97)
        self.assertAlmostEqual(e.data["tp"], 950_000)
        self.assertEqual(e.ts, s.bars[e.idx].ts)
        self.assertEqual(e.decision_ts, e.ts + H)
        self.assertIn("WATCHLIST", kinds(det))
        self.assertLess(kinds(det).index("WATCHLIST"), kinds(det).index("ENTRADA"))

    def test_no_lookahead_every_prefix_gives_the_same_events(self):
        s = textbook()
        full = run(s.bars, params(), "1h", L_BC, GRAD)
        for k in range(1, len(s.bars) + 1):
            part = run(s.bars[:k], params(), "1h", L_BC, GRAD)
            expect = [(e.kind, e.idx, e.data) for e in full.events if e.idx < k]
            self.assertEqual([(e.kind, e.idx, e.data) for e in part.events], expect, f"prefixo {k}")

    def test_future_bars_cannot_change_a_past_decision(self):
        s = textbook()
        base = run(s.bars, params(), "1h", L_BC, GRAD)
        entry = next(e for e in base.events if e.kind == "ENTRADA")
        crashed = list(s.bars[: entry.idx + 1]) + [flat(b.ts, 1_000.0) for b in s.bars[entry.idx + 1:]]
        other = run(crashed, params(), "1h", L_BC, GRAD)
        self.assertEqual([(e.kind, e.idx, e.data) for e in other.events if e.idx <= entry.idx],
                         [(e.kind, e.idx, e.data) for e in base.events if e.idx <= entry.idx])

    def test_drop_beyond_max_invalidates_the_wave(self):
        det = run(textbook(drop_low=80_000, wick_low=80_000).bars, params(), "1h", L_BC, GRAD)
        self.assertIn("ONDA_INVALIDA", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_low_below_bonding_curve_level_invalidates(self):
        det = run(textbook().bars, params(drop_max=0.97), "1h", 155_000.0, GRAD)
        invalid = [e for e in det.events if e.kind == "ONDA_INVALIDA"]
        self.assertTrue(invalid and invalid[0].data["motivo"] == "minima furou L_bc", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_breakout_without_volume_is_not_an_entry(self):
        det = run(textbook(breakout_vol=1_500).bars, params(), "1h", L_BC, GRAD)
        self.assertNotIn("ENTRADA", kinds(det))

    def test_box_must_mature(self):
        det = run(textbook(box_len=6).bars, params(), "1h", L_BC, GRAD)
        self.assertNotIn("ENTRADA", kinds(det))
        det = run(textbook(box_len=6).bars, params(box_min_candles=6), "1h", L_BC, GRAD)
        self.assertIn("ENTRADA", kinds(det))

    def test_needs_a_wick_at_support(self):
        # "martelo" fora da zona S +-5%: o suporte (minima da caixa) fica no fundo da queda, longe do martelo
        det = run(textbook(wick_low=190_000, drop_low=150_000).bars, params(bounce_fractal=1, box_min_candles=12), "1h", L_BC, GRAD)
        box_events = [e for e in det.events if e.kind == "ENTRADA"]
        for e in box_events:
            self.assertGreaterEqual(e.data["n_wicks"], 1)

    def test_absurd_breakout_candle_is_skipped(self):
        det = run(textbook(breakout_high=800_000, breakout_close=700_000).bars, params(), "1h", L_BC, GRAD)
        self.assertIn("ABSURDO", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_losing_the_last_wick_invalidates_and_box_restarts(self):
        s = textbook(start_flat=0)
        s.bars.pop()                                   # tira o rompimento
        s.t -= H
        s.add(210_000, 212_000, 140_000, 141_000)       # fecha abaixo da minima da wick -2%
        s.add(141_000, 345_000, 140_000, 340_000, 9_000)  # "rompimento" logo depois: caixa nova ainda imatura
        det = run(s.bars, params(drop_max=0.95), "1h", L_BC, GRAD)
        self.assertIn("INVALIDADO", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_age_window_marks_out_of_window_entries_as_not_primary(self):
        det = run(textbook().bars, Params(), "1h", L_BC, GRAD)   # janela 2-7 dias no 1h; o rompimento e com ~1,5 dia
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].data["na_janela"])
        self.assertFalse(entries[0].data["primario"])

    def test_close_measure_uses_closes(self):
        p = params(measure="close")
        det = run(textbook().bars, p, "1h", L_BC, GRAD)
        runner = [e for e in det.events if e.kind == "FASE2"]
        self.assertTrue(runner)
        self.assertEqual(runner[0].data["P_peak"], 950_000)

    def test_out_of_order_bars_are_rejected(self):
        det = Detector(params(), "1h", L_BC, GRAD)
        det.update(flat(T0 + H, 1.0))
        with self.assertRaises(ValueError):
            det.update(flat(T0, 1.0))

    def test_hammer_definition(self):
        self.assertTrue(is_hammer(Bar(0, 100, 101, 80, 99, 1.0), 2.0))     # pavio 19 >= 2 x corpo 1
        self.assertFalse(is_hammer(Bar(0, 100, 101, 95, 90, 1.0), 2.0))    # vermelho, sem pavio inferior relevante
        self.assertFalse(is_hammer(Bar(0, 100, 100, 100, 100, 0.0, True), 2.0))   # candle preenchido


class ParamsTests(unittest.TestCase):
    def test_shipped_yaml_matches_handoff_defaults_and_has_stable_hash(self):
        shipped = load_params()
        self.assertEqual(shipped, Params())
        self.assertEqual(shipped.version, Params().version)
        self.assertNotEqual(shipped.version, dataclasses.replace(shipped, drop_max=0.95).version)

    def test_unknown_or_invalid_params_fail(self):
        with self.assertRaises(ValueError):
            params_from_dict({"nao_existe": 1})
        with self.assertRaises(ValueError):
            Params(drop_min=0.9, drop_max=0.8)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.p = params()
        self.costs = CostModel()
        self.sol = lambda ts: 100.0

    def _entry(self, bars_before: list[Bar], stop: float = 90.0, tp: float = 200.0):
        from ..pos_runner.detector import Event
        idx = len(bars_before) - 1
        return Event("ENTRADA", idx, bars_before[-1].ts, bars_before[-1].ts + H, {"stop": stop, "tp": tp})

    def _bars(self, *ohlc) -> list[Bar]:
        return [Bar(T0 + k * H, *row, 1_000.0) for k, row in enumerate(ohlc)]

    def test_exit_a_hits_target(self):
        bars = self._bars((100, 101, 99, 100), (100, 120, 95, 115), (115, 210, 110, 190))
        r = simulate(bars, self._entry(bars[:1]), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.status, r.reason, r.hit_tp), ("fechado", "alvo", True))
        self.assertAlmostEqual(r.gross_ret, 200 / 100 - 1)
        self.assertLess(r.net_ret, r.gross_ret)
        self.assertAlmostEqual(r.r_mult, r.net_ret / 0.10)

    def test_stop_gap_fills_at_open_and_ambiguous_counts_stop_first(self):
        bars = self._bars((100, 101, 99, 100), (100, 110, 95, 105), (80, 85, 70, 75))
        r = simulate(bars, self._entry(bars[:1]), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.reason, r.legs[-1].price), ("stop", 80))
        bars = self._bars((100, 101, 99, 100), (100, 250, 50, 150))
        r = simulate(bars, self._entry(bars[:1]), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertTrue(r.ambiguous)
        self.assertEqual((r.reason, r.legs[-1].price, r.hit_tp), ("stop", 90.0, False))

    def test_cancelled_when_next_open_is_outside_the_plan(self):
        bars = self._bars((100, 101, 99, 100), (85, 90, 80, 85))
        r = simulate(bars, self._entry(bars[:1]), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual(r.status, "cancelado")

    def test_exit_b_partial_then_trailing(self):
        bars = self._bars((100, 101, 99, 100), (100, 205, 99, 200), (200, 300, 195, 290), (290, 292, 210, 220))
        r = simulate(bars, self._entry(bars[:1]), "B", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual([leg.reason for leg in r.legs], ["alvo_parcial", "trailing"])
        self.assertAlmostEqual(r.legs[1].price, 0.75 * 300)
        self.assertAlmostEqual(r.gross_ret, 0.5 * 2.0 + 0.5 * 2.25 - 1)

    def test_time_stop_and_open_trade(self):
        p = params(time_stop_candles=3)
        bars = self._bars((100, 101, 99, 100), (100, 105, 95, 101), (101, 104, 96, 100), (100, 103, 97, 99), (99, 100, 98, 99))
        r = simulate(bars, self._entry(bars[:1]), "A", p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.reason, r.legs[-1].idx, r.bars_held), ("tempo", 4, 4))
        r = simulate(bars[:3], self._entry(bars[:1]), "A", p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual(r.status, "em_aberto")

    def test_exhaustion_power_candle_exits_next_open(self):
        p = params(atr_period=3)
        bars = self._bars((100, 101, 99, 100), (100, 102, 99, 101), (101, 103, 100, 102), (102, 104, 101, 103),
                          (103, 190, 102, 185), (180, 182, 170, 175))
        r = simulate(bars, self._entry(bars[:1], tp=400.0), "A", p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.reason, r.legs[-1].price), ("exaustao", 180))


class CostTests(unittest.TestCase):
    def test_pumpswap_tiers(self):
        self.assertEqual(pumpswap_fee_pct(100), 1.25)
        self.assertEqual(pumpswap_fee_pct(420), 1.25)
        self.assertEqual(pumpswap_fee_pct(421), 1.2)
        self.assertEqual(pumpswap_fee_pct(5_000), 1.0)
        self.assertEqual(pumpswap_fee_pct(1e6), 0.3)

    def test_leg_cost_parts_and_multiplier(self):
        c = CostModel()
        leg = c.leg_pct("pumpswap", 1_000_000, 50_000, 100.0)
        expected = pumpswap_fee_pct(10_000) + 1.0 + 0.2 + c.slippage_pct(1_000_000, 50_000, 100.0)
        self.assertAlmostEqual(leg, expected)
        self.assertAlmostEqual(CostModel(multiplier=2.0).leg_pct("pumpswap", 1_000_000, 50_000, 100.0), 2 * expected)
        self.assertEqual(c.pool_fee_pct("desconhecido", 1e6, 100.0), 1.25)


class _FakeOhlcvHttp:
    """GeckoTerminal de mentira: `before_timestamp` inclusivo, no maximo `span` segundos e 1000 candles por
    resposta, respostas vazias falsas em `glitch` (uma vez cada) e queda simulada depois de `crash_after` chamadas."""

    class _Limiter:
        @staticmethod
        def blocked_for() -> float:
            return 0.0

    def __init__(self, candles: list[list[float]], span: int, glitch: set[int] = frozenset(), crash_after: int = 0):
        self.candles = sorted(candles)
        self.span = span
        self.glitch = set(glitch)
        self.crash_after = crash_after
        self.calls = 0
        self.headers: dict[str, str] = {}
        self.limiter = self._Limiter()

    def get_json(self, path, params, max_wait_s=0.0):
        self.calls += 1
        if self.crash_after and self.calls > self.crash_after:
            raise KeyboardInterrupt("queda simulada")
        before = int(params["before_timestamp"])
        if before in self.glitch:
            self.glitch.discard(before)
            rows = []
        else:
            rows = [c for c in self.candles if before - self.span < c[0] <= before][-int(params["limit"]):]
        return {"data": {"attributes": {"ohlcv_list": [list(r) for r in reversed(rows)]}}}


class CandleStoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        # 5m durante 30 dias, com um buraco de 8 dias sem negociacao no meio
        start = T0
        self.start = start
        self.rows = [[start + k * 300, 1.0, 1.1, 0.9, 1.0, 5.0] for k in range(30 * 288) if not (10 * 288 <= k < 18 * 288)]
        self.end = start + 30 * 86400

    def _store(self, http):
        from ..pos_runner.candles import OhlcvStore
        return OhlcvStore(http, self.tmp, sleep=lambda s: None)

    def test_walks_back_through_span_limits_gaps_and_glitches(self):
        glitch = {self.start + 25 * 86400 - 1}
        http = _FakeOhlcvHttp(self.rows, span=int(13.5 * 86400), glitch=glitch)
        bars = self._store(http).history("POOL", "5m", self.start, self.end)
        self.assertEqual([b.ts for b in bars], [r[0] for r in self.rows])

    def test_resumes_after_a_crash_without_losing_pages(self):
        import tempfile
        from pathlib import Path
        from ..pos_runner.candles import OhlcvStore
        fresh = _FakeOhlcvHttp(self.rows, span=3 * 86400)
        OhlcvStore(fresh, Path(tempfile.mkdtemp()), sleep=lambda s: None).history("POOL", "5m", self.start, self.end)
        http = _FakeOhlcvHttp(self.rows, span=3 * 86400, crash_after=4)
        with self.assertRaises(KeyboardInterrupt):
            self._store(http).history("POOL", "5m", self.start, self.end)
        http2 = _FakeOhlcvHttp(self.rows, span=3 * 86400)
        bars = self._store(http2).history("POOL", "5m", self.start, self.end)
        self.assertEqual(len(bars), len(self.rows))
        self.assertEqual(http2.calls, fresh.calls - 4)   # retomou do checkpoint: so as chamadas que faltavam
        http3 = _FakeOhlcvHttp(self.rows, span=3 * 86400)
        self._store(http3).history("POOL", "5m", self.start, self.end)
        self.assertEqual(http3.calls, 0)            # tudo em cache


class CandleTests(unittest.TestCase):
    def test_fill_gaps_inserts_flat_zero_volume_bars(self):
        bars = [Bar(0, 1, 2, 0.5, 1.5, 10), Bar(3 * H, 1.5, 2, 1, 1.8, 5)]
        out = fill_gaps(bars, H)
        self.assertEqual([b.ts for b in out], [0, H, 2 * H, 3 * H])
        self.assertTrue(out[1].filled and out[1].volume == 0 and out[1].close == 1.5)

    def test_missing_windows_against_coarser_series(self):
        fine = [Bar(0, 1, 1, 1, 1, 1), Bar(300, 1, 1, 1, 1, 1)]
        coarse = [Bar(0, 1, 1, 1, 1, 5), Bar(H, 1, 1, 1, 1, 7), Bar(2 * H, 1, 1, 1, 1, 0)]
        self.assertEqual(missing_windows(fine, "5m", coarse, "1h"), [(H, 2 * H)])

    def test_token_to_usd_conversion_uses_reference_at_candle_close(self):
        usd = UsdSeries([0, H], [100.0, 110.0], [110.0, 120.0])
        # o 2o candle fecha 9h depois do fim da referencia (folga maxima de 6h): fica sem USD
        bars, missing = to_mc_bars([Bar(0, 1.0, 2.0, 0.5, 1.5, 3.0), Bar(10 * H, 1, 1, 1, 1, 1)], "1h", usd, 1_000.0)
        self.assertEqual(missing, 1)
        self.assertAlmostEqual(bars[0].close, 1.5 * 110.0 * 1_000.0)
        self.assertAlmostEqual(bars[0].volume, 3.0 * 110.0)


if __name__ == "__main__":
    unittest.main()
