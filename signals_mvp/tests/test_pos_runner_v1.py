"""POS-RUNNER-V1 ("regras do professor"): Params, detector (Setup 1 + 3 gatilhos) e simulador (TP1/EXIT FULL/stop).
Sem rede. Ver docs/pos-runner-v1/INTERPRETACOES.md para a justificativa de cada limiar testado aqui."""

from __future__ import annotations

import dataclasses
import unittest

from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1, EventV1, run
from ..pos_runner.params_v1 import ParamsV1, load_params_v1, params_v1_from_dict
from ..pos_runner.simulate_v1 import simulate_v1

H = 3600
T0 = 1_790_000_000 - (1_790_000_000 % H)
GRAD = T0
L_BC = 50_000.0


class Series:
    def __init__(self, start: int = T0):
        self.bars: list[Bar] = []
        self.t = start

    def add(self, o: float, h: float, l: float, c: float, v: float = 1_000.0) -> "Series":
        self.bars.append(Bar(self.t, o, h, l, c, v))
        self.t += H
        return self

    def flat(self, price: float, n: int = 1, v: float = 1_000.0) -> "Series":
        for _ in range(n):
            self.bars.append(Bar(self.t, price, price * 1.01, price * 0.99, price, v))
            self.t += H
        return self


def textbook_v1(breakout_high: float = 450_000.0, breakout_close: float = 400_000.0, breakout_vol: float = 1_000.0,
                 lateral: int = 4) -> Series:
    """Graduacao -> runner (pico 1M) -> queda 85% -> 1o repique (R=260k) -> lateral -> 1 teste de suporte
    (minima 155k, dentro de S x 1,05 = 157,5k) -> lateral -> rompimento de R por power candle."""
    s = Series()
    s.flat(60_000, 2)                                      # 0-1
    for p in (150_000, 300_000, 600_000, 900_000):         # 2-5
        s.add(p * 0.9, p * 1.02, p * 0.88, p)
    s.add(900_000, 1_000_000, 880_000, 950_000)           # 6: pico
    for p in (800_000, 600_000, 400_000, 250_000):         # 7-10
        s.add(p * 1.1, p * 1.12, p * 0.97, p)
    s.add(250_000, 255_000, 155_000, 165_000)             # 11: queda 84,5% -> FASE2, zona comeca
    s.add(165_000, 170_000, 150_000, 155_000)             # 12: fundo (S=150k, anchor)
    s.add(155_000, 260_000, 154_000, 250_000)             # 13: 1o repique (fecha 250k >= 187,5k): fixa R=260k
    for _ in range(lateral):                               # lateral sem tocar S x 1,05 = 157,5k
        s.add(240_000, 245_000, 200_000, 210_000)
    s.add(210_000, 212_000, 175_000, 180_000)             # desce
    s.add(180_000, 182_000, 155_000, 162_000)             # teste: minima 155k (dentro de [142,5k; 157,5k])
    s.add(162_000, 200_000, 158_000, 195_000)             # fecha 195k >= min(205k; 187,5k): teste completo
    for _ in range(lateral):                               # fecha ABAIXO da maxima do wick (182k): sem
        s.add(170_000, 179_000, 168_000, 175_000)          # reacao_suporte prematura antes do rompimento real
    s.add(174_000, breakout_high, 168_000, breakout_close, breakout_vol)   # rompimento
    s.flat(breakout_close, 20)
    return s


def params(**over) -> ParamsV1:
    base = ParamsV1(age_window_days=(0.0, 10_000.0))
    return dataclasses.replace(base, **over)


def kinds(det: DetectorV1) -> list[str]:
    return [e.kind for e in det.events]


CREATED = GRAD - 3 * 86400


class DetectorV1Tests(unittest.TestCase):
    def test_power_candle_breakout_gives_one_entry(self):
        s = textbook_v1()
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1, kinds(det))
        e = entries[0]
        self.assertIn("power_candle_rompimento", e.data["gatilho"])
        self.assertEqual(e.data["P_peak"], 1_000_000)
        self.assertEqual(e.data["TOPO"], 1_000_000)
        self.assertEqual(e.data["S"], 150_000)
        self.assertEqual(e.data["R"], 260_000)
        self.assertEqual(e.data["n_testes"], 1)
        self.assertAlmostEqual(e.data["stop"], 155_000 * 0.98)
        self.assertAlmostEqual(e.data["queda_pct"], 85.0)
        self.assertTrue(e.data["na_janela_idade"])
        k = kinds(det)
        self.assertLess(k.index("FASE2"), k.index("TESTE"))
        self.assertLess(k.index("TESTE"), k.index("WATCHLIST"))
        self.assertLess(k.index("WATCHLIST"), k.index("ENTRADA"))

    def test_no_lookahead_every_prefix_gives_the_same_events(self):
        s = textbook_v1()
        full = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        for k in range(1, len(s.bars) + 1):
            part = run(s.bars[:k], params(), "1h", L_BC, GRAD, CREATED)
            expect = [(e.kind, e.idx, e.data) for e in full.events if e.idx < k]
            self.assertEqual([(e.kind, e.idx, e.data) for e in part.events], expect, f"prefixo {k}")

    def test_rompimento_volume_gatilho(self):
        """Mesmo setup, mas o rompimento fica abaixo do limiar de power candle e tem volume alto: so
        rompimento_volume dispara (nao power_candle_rompimento)."""
        s = textbook_v1(breakout_high=262_000.0, breakout_close=261_000.0, breakout_vol=50_000.0)
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1, kinds(det))
        self.assertIn("rompimento_volume", entries[0].data["gatilho"])
        self.assertNotIn("power_candle_rompimento", entries[0].data["gatilho"])

    def test_reacao_suporte_gatilho_fires_before_the_box_ceiling(self):
        """Candle verde que fecha acima da maxima do candle do wick (162k), dentro da zona do suporte --
        dispara reacao_suporte mesmo sem fechar acima de R (260k)."""
        s = textbook_v1(lateral=0)
        s.add(195_000, 210_000, 194_000, 205_000)       # fecha acima da maxima do wick (182k) -- reacao_suporte
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        entries = [e for e in det.events if e.kind == "ENTRADA"]
        self.assertEqual(len(entries), 1, kinds(det))
        self.assertEqual(entries[0].data["gatilho"], ["reacao_suporte"])

    def test_runner_floor_is_a_filter(self):
        s = Series()
        s.flat(60_000, 2)
        s.add(60_000, 299_999, 55_000, 250_000)   # pico abaixo de 300k: nunca entra em fase 1
        s.flat(250_000, 20)
        det = run(s.bars, params(), "1h", L_BC, GRAD, CREATED)
        self.assertEqual(kinds(det), [])

    def test_drop_beyond_90_percent_invalidates_the_wave(self):
        s = textbook_v1()
        s.bars[11] = Bar(s.bars[11].ts, 250_000, 255_000, 95_000, 100_000, 1_000.0)   # queda de 90,5%
        det = run(s.bars[:12], params(), "1h", L_BC, GRAD, CREATED)
        self.assertIn("ONDA_INVALIDA", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_breaking_the_graduation_level_invalidates_the_wave(self):
        s = textbook_v1()
        s.bars[11] = Bar(s.bars[11].ts, 250_000, 255_000, 48_000, 165_000, 1_000.0)   # minima abaixo de L_bc (50k)
        det = run(s.bars[:12], params(), "1h", L_BC, GRAD, CREATED)
        self.assertIn("ONDA_INVALIDA", kinds(det))

    def test_zone_must_mature_before_12_candles(self):
        s = textbook_v1(lateral=0)
        det = run(s.bars[:20], params(), "1h", L_BC, GRAD, CREATED)   # corta antes da caixa chegar a 12 candles
        self.assertNotIn("WATCHLIST", kinds(det))
        self.assertNotIn("ENTRADA", kinds(det))

    def test_age_outside_window_never_becomes_entrada(self):
        s = textbook_v1()
        created = GRAD - 30 * 86400   # 30 dias antes da graduacao: fora de [2,7] dias na entrada
        det = run(s.bars, params(age_window_days=(2.0, 7.0)), "1h", L_BC, GRAD, created)
        self.assertNotIn("ENTRADA", kinds(det))
        self.assertIn("FORA_DA_IDADE", kinds(det))

    def test_out_of_order_bars_are_rejected(self):
        det = DetectorV1(params(), "1h", L_BC, GRAD, CREATED)
        det.update(Bar(T0, 1, 1, 1, 1, 1))
        with self.assertRaises(ValueError):
            det.update(Bar(T0, 1, 1, 1, 1, 1))


class ParamsV1Tests(unittest.TestCase):
    def test_shipped_yaml_matches_the_defaults(self):
        self.assertEqual(load_params_v1(), ParamsV1())

    def test_unknown_param_rejected(self):
        with self.assertRaises(ValueError):
            params_v1_from_dict({"nao_existe": 1})

    def test_ints_and_floats_give_the_same_hash(self):
        a = params_v1_from_dict({"runner_min_mc": 300000})
        b = params_v1_from_dict({"runner_min_mc": 300000.0})
        self.assertEqual(a.version, b.version)

    def test_hash_is_independent_from_v0(self):
        from ..pos_runner.params import Params
        self.assertNotEqual(ParamsV1().version, Params().version)


def _ev(stop: float, topo: float, s_support: float, idx: int = 0) -> EventV1:
    return EventV1("ENTRADA", idx, T0 + idx * H, T0 + (idx + 1) * H,
                   {"stop": stop, "TOPO": topo, "S": s_support})


class SimulateV1Tests(unittest.TestCase):
    costs = CostModel(terminal_pct=0.0, network_sol=0.0, multiplier=1.0)

    def _run(self, bars: list[Bar], ev: EventV1):
        return simulate_v1(bars, ev, params(), self.costs, "pumpswap", None,
                           lambda ts: 150.0, pool_fee_pct=0.0)

    def test_stop_hit(self):
        bars = [
            Bar(T0, 100, 100, 100, 100, 1),
            Bar(T0 + H, 110, 120, 108, 115, 1),
            Bar(T0 + 2 * H, 109, 112, 80, 90, 1),
        ]
        res = self._run(bars, _ev(stop=90, topo=300, s_support=100))
        self.assertEqual(res.status, "fechado")
        self.assertEqual(res.reason, "stop")
        self.assertEqual(res.legs[-1].price, 90)

    def test_cancelled_when_next_open_is_outside_the_plan(self):
        bars = [Bar(T0, 100, 100, 100, 100, 1), Bar(T0 + H, 85, 90, 80, 88, 1)]
        res = self._run(bars, _ev(stop=90, topo=300, s_support=50))
        self.assertEqual(res.status, "cancelado")

    def test_open_trade_without_enough_bars(self):
        bars = [Bar(T0, 100, 100, 100, 100, 1), Bar(T0 + H, 110, 120, 108, 115, 1)]
        res = self._run(bars, _ev(stop=50, topo=300, s_support=30))
        self.assertEqual(res.status, "em_aberto")

    def test_tp1_then_exit_full_on_close_below_support(self):
        bars = [
            Bar(T0, 100, 100, 100, 100, 1),                            # 0: decisao
            Bar(T0 + H, 110, 120, 105, 115, 1),                        # 1: entrada (open=110)
            Bar(T0 + 2 * H, 150, 320, 148, 155, 1),                    # 2: toca o TOPO com pavio longo (exaustao)
            Bar(T0 + 3 * H, 200, 210, 195, 205, 1),                    # 3: preenche TP1 no open (200)
            Bar(T0 + 4 * H, 105, 108, 92, 90, 1),                      # 4: fecha abaixo de S (100) -> exit_full
            Bar(T0 + 5 * H, 88, 90, 85, 87, 1),                        # 5: preenche exit_full no open (88)
        ]
        res = self._run(bars, _ev(stop=50, topo=300, s_support=100))
        self.assertEqual(res.status, "fechado")
        self.assertEqual([leg.reason for leg in res.legs], ["tp1", "exit_full"])
        self.assertAlmostEqual(res.legs[0].frac, 0.30)
        self.assertAlmostEqual(res.legs[1].frac, 0.70)
        self.assertEqual(res.legs[0].price, 200)
        self.assertEqual(res.legs[1].price, 88)
        self.assertLess(res.net_ret, res.gross_ret)   # custos sempre reduzem o retorno


if __name__ == "__main__":
    unittest.main()
