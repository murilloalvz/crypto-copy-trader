"""PEDIDO (PARTE 1 de 2) FASES 1-2: trajetoria pos-entrada e baseline pareada (funcoes puras, sem live.py)."""

from __future__ import annotations

import unittest

from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.params_v1 import ParamsV1
from ..pos_runner.simulate_v1 import LegV1
from ..pos_runner.evidencia import (
    calcular_trajetoria,
    candidatos_elegiveis,
    evento_controle,
    r_de,
    seed_de_entrada,
    simular_controle,
    sortear_controles,
)

H = 3600


def _flat_bars(n: int, price: float = 100.0, start_ts: int = 0) -> list[Bar]:
    return [Bar(start_ts + i * H, price, price, price, price, 1.0) for i in range(n)]


class RDeTests(unittest.TestCase):
    def test_basic_r_multiple(self) -> None:
        # entry=100, risco_frac=0.10 (1R = 10 em preco): preco 130 -> (1.30-1)/0.10 = 3.0R
        self.assertAlmostEqual(r_de(130.0, 100.0, 0.10), 3.0)
        self.assertAlmostEqual(r_de(70.0, 100.0, 0.10), -3.0)
        self.assertAlmostEqual(r_de(100.0, 100.0, 0.10), 0.0)

    def test_none_on_missing_price_or_invalid_risk(self) -> None:
        self.assertIsNone(r_de(None, 100.0, 0.10))
        self.assertIsNone(r_de(110.0, 100.0, 0.0))
        self.assertIsNone(r_de(110.0, 100.0, -0.05))


class CalcularTrajetoriaTests(unittest.TestCase):
    def test_mfe_mae_and_fixed_horizons(self) -> None:
        bars = _flat_bars(72)
        bars[5] = Bar(bars[5].ts, 100.0, 130.0, 100.0, 100.0, 1.0)   # h=6: pico favoravel +3.0R
        bars[10] = Bar(bars[10].ts, 100.0, 100.0, 70.0, 100.0, 1.0)  # h=11: fundo adverso -3.0R
        bars[23] = Bar(bars[23].ts, 100.0, 115.0, 100.0, 115.0, 1.0)  # h=24: fechamento +1.5R
        bars[71] = Bar(bars[71].ts, 100.0, 105.0, 100.0, 105.0, 1.0)  # h=72: fechamento +0.5R
        calc = calcular_trajetoria(bars, entry_idx=0, entry_ts=bars[0].ts, entry_price=100.0,
                                   risco_frac=0.10, step_s=H, legs=[], now=bars[0].ts + 72 * H)
        self.assertAlmostEqual(calc.mfe_r, 3.0)
        self.assertAlmostEqual(calc.mfe_h, 6.0)
        self.assertAlmostEqual(calc.mae_r, -3.0)
        self.assertAlmostEqual(calc.mae_h, 11.0)
        self.assertAlmostEqual(calc.retornos_r[24], 1.5)
        self.assertAlmostEqual(calc.retornos_r[72], 0.5)
        self.assertTrue(calc.fechado)

    def test_horizon_without_enough_candles_stays_none_never_interpolated(self) -> None:
        bars = _flat_bars(10)  # so cobre at h=10, nunca chega em h=24/48/72
        calc = calcular_trajetoria(bars, entry_idx=0, entry_ts=bars[0].ts, entry_price=100.0,
                                   risco_frac=0.10, step_s=H, legs=[], now=bars[0].ts + 10 * H)
        self.assertIsNotNone(calc.retornos_r[1])
        self.assertIsNotNone(calc.retornos_r[8])
        self.assertIsNone(calc.retornos_r[24])
        self.assertIsNone(calc.retornos_r[48])
        self.assertIsNone(calc.retornos_r[72])
        self.assertFalse(calc.fechado, "ainda nao passaram 72h reais desde a entrada")

    def test_closes_exactly_at_72h_never_before(self) -> None:
        bars = _flat_bars(72)
        entry_ts = bars[0].ts
        calc_antes = calcular_trajetoria(bars, 0, entry_ts, 100.0, 0.10, H, [], now=entry_ts + 72 * H - 1)
        calc_depois = calcular_trajetoria(bars, 0, entry_ts, 100.0, 0.10, H, [], now=entry_ts + 72 * H)
        self.assertFalse(calc_antes.fechado)
        self.assertTrue(calc_depois.fechado)

    def test_tocou_tp1_and_tocou_stop_antes_de_tp1_from_legs(self) -> None:
        bars = _flat_bars(10)
        legs_so_tp1 = [LegV1(3, bars[3].ts, 120.0, 0.3, "tp1", 1.0)]
        calc = calcular_trajetoria(bars, 0, bars[0].ts, 100.0, 0.10, H, legs_so_tp1, now=bars[0].ts)
        self.assertTrue(calc.tocou_tp1)
        self.assertFalse(calc.tocou_stop_antes_de_tp1)

        legs_so_stop = [LegV1(2, bars[2].ts, 90.0, 1.0, "stop", 1.0)]
        calc2 = calcular_trajetoria(bars, 0, bars[0].ts, 100.0, 0.10, H, legs_so_stop, now=bars[0].ts)
        self.assertFalse(calc2.tocou_tp1)
        self.assertTrue(calc2.tocou_stop_antes_de_tp1)

        legs_tp1_depois_stop = [LegV1(1, bars[1].ts, 90.0, 1.0, "stop", 1.0)]  # stop fecha o trade (sem tp1 antes)
        calc3 = calcular_trajetoria(bars, 0, bars[0].ts, 100.0, 0.10, H, legs_tp1_depois_stop, now=bars[0].ts)
        self.assertTrue(calc3.tocou_stop_antes_de_tp1)


class CandidatosElegiveisTests(unittest.TestCase):
    def test_no_candidate_before_any_peak(self) -> None:
        bars = _flat_bars(5, price=100.0)
        out = candidatos_elegiveis(bars, created_ts=bars[0].ts, age_window_days=(0.0, 100.0), step_s=H,
                                   excluir_idx=-1)
        self.assertEqual(out, [])

    def test_eligible_after_peak_with_enough_drop_and_mc(self) -> None:
        bars = _flat_bars(5, price=1_000_000.0)
        bars[0] = Bar(bars[0].ts, 1_000_000.0, 1_000_000.0, 1_000_000.0, 1_000_000.0, 1.0)  # pico
        bars[3] = Bar(bars[3].ts, 150_000.0, 150_000.0, 150_000.0, 150_000.0, 1.0)  # queda 85%, MC>=100k
        out = candidatos_elegiveis(bars, created_ts=bars[0].ts, age_window_days=(0.0, 100.0), step_s=H,
                                   excluir_idx=-1)
        self.assertIn(3, out)

    def test_excludes_the_real_trigger_candle(self) -> None:
        bars = _flat_bars(5, price=1_000_000.0)
        bars[3] = Bar(bars[3].ts, 150_000.0, 150_000.0, 150_000.0, 150_000.0, 1.0)
        out = candidatos_elegiveis(bars, created_ts=bars[0].ts, age_window_days=(0.0, 100.0), step_s=H,
                                   excluir_idx=3)
        self.assertNotIn(3, out)

    def test_excludes_outside_the_age_window(self) -> None:
        bars = _flat_bars(5, price=1_000_000.0)
        bars[3] = Bar(bars[3].ts, 150_000.0, 150_000.0, 150_000.0, 150_000.0, 1.0)
        out = candidatos_elegiveis(bars, created_ts=bars[0].ts, age_window_days=(10.0, 20.0), step_s=H,
                                   excluir_idx=-1)
        self.assertEqual(out, [])

    def test_excludes_below_the_drop_or_mc_floor(self) -> None:
        bars = _flat_bars(5, price=1_000_000.0)
        bars[3] = Bar(bars[3].ts, 900_000.0, 900_000.0, 900_000.0, 900_000.0, 1.0)  # so 10% de queda
        out = candidatos_elegiveis(bars, created_ts=bars[0].ts, age_window_days=(0.0, 100.0), step_s=H,
                                   excluir_idx=-1)
        self.assertEqual(out, [])

    def test_no_created_ts_is_never_eligible(self) -> None:
        bars = _flat_bars(5, price=1_000_000.0)
        bars[3] = Bar(bars[3].ts, 150_000.0, 150_000.0, 150_000.0, 150_000.0, 1.0)
        out = candidatos_elegiveis(bars, created_ts=None, age_window_days=(0.0, 100.0), step_s=H, excluir_idx=-1)
        self.assertEqual(out, [])

    def test_a_future_even_bigger_peak_never_makes_an_earlier_candle_eligible_anti_lookahead(self) -> None:
        """EMENDA 1 (2026-10-29) item 5: confirma a verificacao anti-lookahead pedida -- `peak` aqui so
        acumula o maximo dos candles ANTERIORES (`peak = bar.high` roda DEPOIS do check, nunca antes),
        entao um pico muito maior que so aparece DEPOIS nunca pode, retroativamente, fazer um candle
        anterior parecer ter caido mais do que realmente tinha caido at= aquele momento."""
        bars = _flat_bars(5, price=1_000_000.0)
        bars[0] = Bar(bars[0].ts, 1_000_000.0, 1_000_000.0, 1_000_000.0, 1_000_000.0, 1.0)  # pico CONHECIDO em t=0
        bars[1] = Bar(bars[1].ts, 300_000.0, 300_000.0, 300_000.0, 300_000.0, 1.0)  # queda 70% do pico conhecido (< 80%)
        bars[2] = Bar(bars[2].ts, 100_000_000.0, 100_000_000.0, 100_000_000.0, 100_000_000.0, 1.0)  # pico GIGANTE, so DEPOIS
        out = candidatos_elegiveis(bars, created_ts=bars[0].ts, age_window_days=(0.0, 100.0), step_s=H, excluir_idx=-1)
        self.assertNotIn(1, out, "o pico de t=2 e futuro em relacao a t=1 -- um lookahead bug usaria "
                                  "o maximo GLOBAL (100M) e inflaria a queda de t=1 p/ 99.7%, >= 80%")


class SortearControlesTests(unittest.TestCase):
    def test_same_entry_id_and_versao_always_sorts_the_same(self) -> None:
        candidatos = list(range(50))
        a = sortear_controles(candidatos, entry_id=42, versao="v1")
        b = sortear_controles(candidatos, entry_id=42, versao="v1")
        self.assertEqual(a, b)

    def test_different_versao_can_sort_a_different_sample(self) -> None:
        candidatos = list(range(50))
        v1 = sortear_controles(candidatos, entry_id=42, versao="v1")
        v2 = sortear_controles(candidatos, entry_id=42, versao="v2")
        self.assertNotEqual(v1, v2)

    def test_respects_n_and_the_available_pool_size(self) -> None:
        self.assertEqual(len(sortear_controles(list(range(50)), 1, "v1", n=10)), 10)
        self.assertEqual(len(sortear_controles([1, 2, 3], 1, "v1", n=10)), 3)
        self.assertEqual(seed_de_entrada(1, "v1"), seed_de_entrada(1, "v1"))
        self.assertNotEqual(seed_de_entrada(1, "v1"), seed_de_entrada(2, "v1"))


class EventoEsimularControleTests(unittest.TestCase):
    def test_evento_controle_scales_topo_and_s_by_the_real_signal_ratio(self) -> None:
        bars = _flat_bars(5, price=200_000.0)
        ev = evento_controle(bars, idx=1, risco_pct_sinal=20.0, topo_mult=1.5, s_mult=0.9)
        self.assertIsNotNone(ev)
        entry = bars[2].open
        self.assertAlmostEqual(ev.data["stop"], entry * 0.80)
        self.assertAlmostEqual(ev.data["TOPO"], entry * 1.5)
        self.assertAlmostEqual(ev.data["S"], entry * 0.9)

    def test_evento_controle_none_without_a_next_candle(self) -> None:
        bars = _flat_bars(3)
        self.assertIsNone(evento_controle(bars, idx=2, risco_pct_sinal=20.0, topo_mult=1.5, s_mult=0.9))

    def test_simular_controle_runs_simulate_v1_end_to_end(self) -> None:
        bars = _flat_bars(10, price=200_000.0)
        bars[5] = Bar(bars[5].ts, 200_000.0, 260_000.0, 200_000.0, 250_000.0, 1.0)  # toca o TOPO escalado
        res = simular_controle(bars, idx=1, risco_pct_sinal=20.0, topo_mult=1.3, s_mult=0.9,
                               params=ParamsV1(), costs=CostModel(), dex="pumpswap", l_bc=None,
                               sol_usd_at=lambda ts: 150.0)
        self.assertIsNotNone(res)
        self.assertIsNotNone(res.entry_price)

    def test_simular_controle_none_without_enough_candles(self) -> None:
        bars = _flat_bars(3)
        res = simular_controle(bars, idx=2, risco_pct_sinal=20.0, topo_mult=1.3, s_mult=0.9,
                               params=ParamsV1(), costs=CostModel(), dex="pumpswap", l_bc=None,
                               sol_usd_at=lambda ts: 150.0)
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
