"""POS-RUNNER-V0: detector causal (fases 0-3), simulador de saidas A/B e custos. Sem rede."""

from __future__ import annotations

import dataclasses
import unittest

from ..pos_runner.candles import Bar, fill_gaps, missing_windows
from ..pos_runner.costs import CostModel, pumpswap_fee_pct
from ..pos_runner.detector import Detector, run
from ..pos_runner.params import Params, load_params, params_from_dict
from ..pos_runner.quotes import UsdSeries, to_mc_bars
from ..pos_runner.simulate import simulate

H = 3600
T0 = 1_790_000_000 - (1_790_000_000 % H)   # inicio alinhado na hora
GRAD = T0
L_BC = 50_000.0


def flat(ts: int, price: float, vol: float = 1_000.0) -> Bar:
    return Bar(ts, price, price * 1.01, price * 0.99, price, vol)


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


def textbook(range_len: int = 8, bottom: float = 150_000.0, test_low: float = 155_000.0, breakout_vol: float = 5_000.0,
             breakout_close: float = 290_000.0, breakout_high: float = 300_000.0, with_test: bool = True,
             start_flat: int = 50) -> Series:
    """Graduacao a 60k -> runner (maxima 1M) -> queda ate o fundo (150k, -85%) -> 1o repique (maxima 260k = R) ->
    lateral 200-240k -> teste de suporte de 3 candles (minima 155k, recupera) -> lateral -> rompimento de R."""
    s = Series()
    s.flat(60_000, 2)                                     # 0-1
    for p in (150_000, 300_000, 600_000, 900_000):        # 2-5
        s.add(p * 0.9, p * 1.02, p * 0.88, p)
    s.add(900_000, 1_000_000, 880_000, 950_000)          # 6: pico (maxima 1M)
    for p in (800_000, 600_000, 400_000, 250_000):        # 7-10
        s.add(p * 1.1, p * 1.12, p * 0.97, p)
    s.add(250_000, 255_000, 160_000, 165_000)            # 11: queda passa de 80% (minima 160k) -> fase 2, zona comeca
    s.add(165_000, 170_000, bottom, 155_000)             # 12: fundo
    s.add(155_000, 260_000, 154_000, 250_000)            # 13: 1o repique (fecha 250k >= 1,25 x S): fixa o fundo; R = 260k
    for k in range(range_len // 2):                       # lateral sem tocar a regiao do suporte (S x 1,10 = 165k)
        s.add(240_000, 245_000, 200_000, 210_000)
    if with_test:                                         # teste de 3 candles: desce ate 155k e recupera
        s.add(210_000, 212_000, 175_000, 180_000)
        s.add(180_000, 182_000, test_low, 162_000)
        s.add(162_000, 200_000, 158_000, 195_000)        # fecha 195k >= min((S+R)/2, 1,25 S) = 187,5k: teste completo
    else:
        s.add(210_000, 230_000, 190_000, 215_000)
        s.add(215_000, 232_000, 191_000, 220_000)
        s.add(220_000, 233_000, 192_000, 225_000)
    for k in range(range_len - range_len // 2):
        s.add(220_000, 245_000, 205_000, 230_000)
    s.add(240_000, breakout_high, 238_000, breakout_close, breakout_vol)   # rompimento de R
    s.flat(breakout_close, start_flat)
    return s


def params(**over) -> Params:
    base = Params(age_window_days=(0.0, 10_000.0))       # sem filtro de idade (o teste de idade usa os valores reais)
    return dataclasses.replace(base, **over)


def kinds(det: Detector) -> list[str]:
    return [e.kind for e in det.events]


CREATED = GRAD - 3 * 86400        # token criado 3 dias antes da graduacao: o rompimento cai dentro de 2-7 dias


class DetectorTests(unittest.TestCase):
    def test_textbook_setup_gives_one_primary_entry(self):
        s = textbook()
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1, kinds(det))
        e = entries[0]
        self.assertTrue(e.data["primario"])
        self.assertEqual(e.data["P_peak"], 1_000_000)
        self.assertEqual(e.data["faixa_pico"], "1-5M")                 # 1M exato cai em 1-5M (faixas [ini, fim))
        self.assertEqual(e.data["S"], 150_000)
        self.assertEqual(e.data["R"], 260_000)                 # o 1o repique faz parte da resistencia
        self.assertEqual(e.data["n_testes"], 1)
        self.assertEqual(e.data["ultimo_teste_minima"], 155_000)
        self.assertAlmostEqual(e.data["stop"], 155_000 * 0.97)
        self.assertAlmostEqual(e.data["tp"], 950_000)
        self.assertAlmostEqual(e.data["queda_pct"], 85.0)
        self.assertTrue(e.data["S_acima_100k"])
        self.assertEqual(e.data["box_start"], 12)              # a zona conta do fundo
        self.assertEqual(e.ts, s.bars[e.idx].ts)
        self.assertEqual(e.decision_ts, e.ts + H)
        k = kinds(det)
        self.assertLess(k.index("FASE2"), k.index("TESTE"))
        self.assertLess(k.index("TESTE"), k.index("WATCHLIST"))
        self.assertLess(k.index("WATCHLIST"), k.index("ENTRADA"))

    def test_no_lookahead_every_prefix_gives_the_same_events(self):
        s = textbook()
        full = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        for k in range(1, len(s.bars) + 1):
            part = run(s.bars[:k], params(), "1h", L_BC, GRAD, CREATED)
            expect = [(e.kind, e.idx, e.data) for e in full.events if e.idx < k]
            self.assertEqual([(e.kind, e.idx, e.data) for e in part.events], expect, f"prefixo {k}")

    def test_future_bars_cannot_change_a_past_decision(self):
        s = textbook()
        base = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        entry = next(e for e in base.events if e.kind == "ENTRADA")
        crashed = list(s.bars[: entry.idx + 1]) + [flat(b.ts, 1_000.0) for b in s.bars[entry.idx + 1:]]
        other = run(crashed, params(), "1h", L_BC, GRAD, CREATED)
        self.assertEqual([(e.kind, e.idx, e.data) for e in other.events if e.idx <= entry.idx],
                         [(e.kind, e.idx, e.data) for e in base.events if e.idx <= entry.idx])

    def test_drop_beyond_90_percent_is_a_dead_coin(self):
        det = run(textbook(bottom=95_000, test_low=100_000).bars, params(), "1h", L_BC, GRAD, CREATED)
        dead = [e for e in det.events if e.kind == "ONDA_INVALIDA"]
        self.assertTrue(dead and "moeda morta" in dead[0].data["motivo"], kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_bottom_below_75_percent_of_the_curve_level_invalidates(self):
        det = run(textbook().bars, params(), "1h", 210_000.0, GRAD, CREATED)      # 0,75 x 210k = 157,5k > fundo 150k
        dead = [e for e in det.events if e.kind == "ONDA_INVALIDA"]
        self.assertTrue(dead and "0.75 x L_bc" in dead[0].data["motivo"], kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))
        det = run(textbook().bars, params(), "1h", 195_000.0, GRAD, CREATED)      # 0,75 x 195k = 146k < 150k: vale
        self.assertIn("ENTRADA", kinds(det))

    def test_slow_breakout_without_volume_is_still_an_entry(self):
        det = run(textbook(breakout_vol=10.0).bars, params(), "1h", L_BC, GRAD, CREATED)
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1)
        self.assertLess(entries[0].data["vol_ratio"], 1.0)        # volume e so atributo

    def test_zone_must_mature(self):
        det = run(textbook(range_len=2).bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertNotIn("ENTRADA", kinds(det))
        det = run(textbook(range_len=2).bars, params(zone_min_candles=6), "1h", L_BC, GRAD, CREATED)
        self.assertIn("ENTRADA", kinds(det))

    def test_needs_a_support_test(self):
        det = run(textbook(with_test=False).bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertNotIn("TESTE", kinds(det))
        self.assertNotIn("WATCHLIST", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_first_bounce_is_never_bought(self):
        s = Series()
        s.flat(60_000, 2)
        for p in (150_000, 300_000, 600_000, 900_000):
            s.add(p * 0.9, p * 1.02, p * 0.88, p)
        s.add(900_000, 1_000_000, 880_000, 950_000)
        s.add(950_000, 960_000, 160_000, 170_000)            # queda de 84% num candle
        for _ in range(14):                                   # fundo arrastado (zona velha, mas sem teste)
            s.add(170_000, 172_000, 158_000, 165_000)
        s.add(165_000, 400_000, 164_000, 390_000)            # 1o repique forte, acima de tudo da zona
        s.flat(390_000, 5)
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertNotIn("ENTRADA", kinds(det))

    def test_multi_candle_test_counts_once_and_two_episodes_count_twice(self):
        s = textbook(range_len=8, start_flat=0)
        bars = s.bars[:-1]                                      # sem o rompimento
        t = bars[-1].ts + H
        extra = [(230_000, 232_000, 170_000, 172_000), (172_000, 175_000, 160_000, 168_000),   # 2o teste, 3 candles
                 (168_000, 205_000, 166_000, 200_000), (200_000, 240_000, 199_000, 230_000),
                 (240_000, 300_000, 238_000, 290_000, 5_000)]
        for k, row in enumerate(extra):
            bars.append(Bar(t + k * H, *row[:4], row[4] if len(row) > 4 else 1_000.0))
        det = run(bars, params(), "1h", L_BC, GRAD, CREATED)
        tests = [e for e in det.events if e.kind == "TESTE"]
        self.assertEqual(len(tests), 2)
        entry = next(e for e in det.events if e.kind == "ENTRADA")
        self.assertEqual(entry.data["n_testes"], 2)
        self.assertEqual(entry.data["ultimo_teste_minima"], 160_000)
        self.assertAlmostEqual(entry.data["stop"], 160_000 * 0.97)

    def test_a_descent_without_recovery_is_not_a_test(self):
        s = textbook(with_test=False, start_flat=0)
        bars = s.bars[:-1]
        t = bars[-1].ts + H
        for k, row in enumerate([(230_000, 231_000, 158_000, 160_000), (160_000, 170_000, 156_000, 162_000)]):
            bars.append(Bar(t + k * H, *row, 1_000.0))           # desce ate o suporte e fica la
        det = run(bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertNotIn("TESTE", kinds(det))

    def test_close_below_the_last_test_kills_the_setup_and_the_zone_restarts(self):
        s = textbook(start_flat=0)
        bars = s.bars[:-1]                                      # tira o rompimento
        t = bars[-1].ts + H
        bars.append(Bar(t, 210_000, 212_000, 140_000, 151_000, 1_000.0))        # fecha < 155k x 0,98 = 151,9k
        bars.append(Bar(t + H, 151_000, 345_000, 150_000, 340_000, 9_000.0))    # "rompimento" logo depois
        det = run(bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertIn("INVALIDADO", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_absurd_breakout_candle_is_vetoed(self):
        det = run(textbook(breakout_high=700_000, breakout_close=650_000).bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertIn("ABSURDO", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_age_since_creation_decides_the_primary_signal(self):
        bars = textbook().bars
        inside = run(bars, Params(), "1h", L_BC, GRAD, CREATED)           # 2-7 dias (criado 3 dias antes da graduacao)
        e = next(e for e in inside.events if e.kind == "ENTRADA")
        self.assertTrue(e.data["na_janela"] and e.data["primario"])
        self.assertGreater(e.data["idade_dias"], e.data["idade_grad_dias"])
        young = run(bars, Params(), "1h", L_BC, GRAD, GRAD - 600)         # ~1,3 dia: fora da janela
        e = next(e for e in young.events if e.kind == "ENTRADA")
        self.assertFalse(e.data["na_janela"] or e.data["primario"])
        unknown = run(bars, Params(), "1h", L_BC, GRAD, None)             # sem data de criacao: nunca primario
        e = next(e for e in unknown.events if e.kind == "ENTRADA")
        self.assertIsNone(e.data["idade_dias"])
        self.assertFalse(e.data["primario"])

    def test_tight_range_inside_the_support_region_has_no_tests(self):
        s = Series()
        s.flat(60_000, 2)
        for p in (150_000, 300_000, 600_000, 900_000):
            s.add(p * 0.9, p * 1.02, p * 0.88, p)
        s.add(900_000, 1_000_000, 880_000, 950_000)
        s.add(950_000, 960_000, 150_000, 155_000)
        for k in range(20):                                     # tudo dentro de S x 1,10: nao ha de onde "descer"
            s.add(155_000, 162_000, 151_000, 158_000 if k % 2 else 153_000)
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertNotIn("TESTE", kinds(det))

    def test_out_of_order_bars_are_rejected(self):
        det = Detector(params(), "1h", L_BC, GRAD)
        det.update(flat(T0 + H, 1.0))
        with self.assertRaises(ValueError):
            det.update(flat(T0, 1.0))


class ParamsTests(unittest.TestCase):
    def test_shipped_yaml_is_the_operator_rule_set(self):
        shipped = load_params()
        self.assertEqual(shipped, Params())                  # o yaml repete as regras do operador (codigo = documento)
        self.assertEqual(shipped.version, load_params().version)
        self.assertNotEqual(shipped.version, dataclasses.replace(shipped, drop_max=0.95).version)
        self.assertEqual([shipped.peak_band(x) for x in (300_000, 499_999, 500_000, 1_000_000, 4_999_999, 5_000_000, 299_999)],
                         ["300-500k", "300-500k", "500k-1M", "1-5M", "1-5M", ">5M", "?"])

    def test_unknown_or_invalid_params_fail(self):
        with self.assertRaises(ValueError):
            params_from_dict({"nao_existe": 1})
        with self.assertRaises(ValueError):
            Params(drop_min=0.9, drop_max=0.8)
        with self.assertRaises(ValueError):
            Params(test_zone=0.30, recover_mult=1.25)       # recuperacao precisa ficar acima da regiao do suporte

    def test_ints_and_floats_give_the_same_hash(self):
        self.assertEqual(params_from_dict({"runner_min_mc": 300000}).version, Params().version)
        self.assertEqual(params_from_dict({"age_window_days": [2, 7]}).version, Params().version)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.p = params()
        self.costs = CostModel()
        self.sol = lambda ts: 100.0

    def _entry(self, bars_before: list[Bar], stop: float = 90.0, tp: float = 200.0, peak: float = 1_000.0):
        from ..pos_runner.detector import Event
        idx = len(bars_before) - 1
        return Event("ENTRADA", idx, bars_before[-1].ts, bars_before[-1].ts + H, {"stop": stop, "tp": tp, "P_peak": peak})

    def _bars(self, *ohlc) -> list[Bar]:
        return [Bar(T0 + k * H, *row, 1_000.0) for k, row in enumerate(ohlc)]

    def test_exit_a_hits_target(self):
        bars = self._bars((100, 101, 99, 100), (100, 120, 95, 115), (115, 210, 110, 190))
        r = simulate(bars, self._entry(bars[:1], peak=210.0), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.status, r.reason, r.hit_tp), ("fechado", "alvo", True))
        self.assertAlmostEqual(r.gross_ret, 200 / 100 - 1)
        self.assertLess(r.net_ret, r.gross_ret)
        self.assertAlmostEqual(r.r_mult, r.net_ret / 0.10)
        self.assertAlmostEqual(r.max_path_pct, 100 * (200 - 100) / (210 - 100))   # saiu no alvo: maxima = nivel de saida

    def test_stop_gap_fills_at_open_and_ambiguous_counts_stop_first(self):
        bars = self._bars((100, 101, 99, 100), (100, 110, 95, 105), (80, 85, 70, 75))
        r = simulate(bars, self._entry(bars[:1]), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.reason, r.legs[-1].price), ("stop", 80))
        self.assertAlmostEqual(r.max_high, 110)                 # o candle inteiro antes do stop conta
        bars = self._bars((100, 101, 99, 100), (100, 250, 50, 150))
        r = simulate(bars, self._entry(bars[:1]), "A", self.p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertTrue(r.ambiguous)
        self.assertEqual((r.reason, r.legs[-1].price, r.hit_tp), ("stop", 90.0, False))
        self.assertEqual(r.max_high, 100)                       # dentro do candle ambiguo a maxima nao conta

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
        self.assertEqual(r.max_high, 105)

    def test_exhaustion_is_a_power_candle_near_the_last_top(self):
        p = params(atr_period=3)
        rows = [(100, 101, 99, 100), (100, 102, 99, 101), (101, 103, 100, 102), (102, 104, 101, 103)]
        near_top = self._bars(*rows, (103, 185, 102, 180), (175, 178, 170, 172))       # maxima 185 >= 0,85 x 200
        r = simulate(near_top, self._entry(near_top[:1], tp=190.0, peak=200.0), "A", p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual((r.reason, r.legs[-1].price), ("exaustao", 175))
        far = self._bars(*rows, (103, 160, 102, 158), (158, 159, 150, 155))             # power candle, mas longe do topo
        r = simulate(far, self._entry(far[:1], tp=190.0, peak=200.0), "A", p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertNotEqual(r.reason, "exaustao")
        red = self._bars(*rows, (103, 186, 100, 110), (110, 112, 105, 106))             # vermelho perto do topo tambem
        r = simulate(red, self._entry(red[:1], tp=190.0, peak=200.0), "A", p, self.costs, "pumpswap", 50.0, self.sol)
        self.assertEqual(r.reason, "exaustao")


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
