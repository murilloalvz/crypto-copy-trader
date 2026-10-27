"""PATCH 2026-10-27 (diagnostico McRib/yagi): testes puros de `pos_runner/qualidade_candle.py`."""

from __future__ import annotations

import unittest

from ..pos_runner.candles import Bar
from ..pos_runner.qualidade_candle import LimiaresQualidadeCandle, motivo_suspeito, ohlc_coerente


def _bar(o: float, h: float, l: float, c: float) -> Bar:
    return Bar(1_000, o, h, l, c, 1.0)


class OhlcCoerenteTests(unittest.TestCase):
    def test_a_normal_candle_is_coherent(self) -> None:
        self.assertTrue(ohlc_coerente(_bar(100.0, 110.0, 95.0, 105.0)))

    def test_high_below_close_is_incoherent(self) -> None:
        self.assertFalse(ohlc_coerente(_bar(100.0, 102.0, 95.0, 105.0)))

    def test_low_above_open_is_incoherent(self) -> None:
        self.assertFalse(ohlc_coerente(_bar(100.0, 110.0, 101.0, 105.0)))


class MotivoSuspeitoTests(unittest.TestCase):
    def test_clean_candle_consistent_with_neighbors_is_confiavel(self) -> None:
        bar = _bar(100.0, 105.0, 98.0, 102.0)
        self.assertIsNone(motivo_suspeito(bar, vizinho_anterior_close=100.0, peak=200.0))

    def test_incoherent_ohlc_is_always_suspeito_even_without_any_neighbor(self) -> None:
        bar = _bar(100.0, 102.0, 95.0, 105.0)
        self.assertEqual(motivo_suspeito(bar, None, None), "ohlc_incoerente")

    def test_dexpaprika_confirmed_divergence_is_decisive_regardless_of_neighbors(self) -> None:
        bar = _bar(100.0, 105.0, 98.0, 102.0)
        self.assertEqual(motivo_suspeito(bar, 100.0, 200.0, dex_divergente=True), "dexpaprika_divergente")

    def test_close_far_above_the_peak_is_suspeito_mcrib_style(self) -> None:
        # McRib: pico (P_peak) 1,4M, close do gatilho 44,1M -- ~31x o pico.
        bar = _bar(1_400_000.0, 44_200_000.0, 1_300_000.0, 44_100_000.0)
        self.assertEqual(motivo_suspeito(bar, vizinho_anterior_close=440_000.0, peak=1_400_000.0), "close_vs_pico")

    def test_a_spike_vs_the_previous_candle_with_no_next_candle_yet_is_unconfirmed_not_dismissed(self) -> None:
        bar = _bar(2_600_000.0, 2_700_000.0, 2_500_000.0, 2_650_000.0)
        motivo = motivo_suspeito(bar, vizinho_anterior_close=227_000.0, peak=2_600_000.0, vizinho_seguinte_open=None)
        self.assertEqual(motivo, "sem_confirmacao_candle_seguinte")

    def test_a_spike_that_reverts_on_the_next_candle_is_confirmed_suspeito(self) -> None:
        bar = _bar(2_600_000.0, 2_700_000.0, 2_500_000.0, 2_650_000.0)
        motivo = motivo_suspeito(bar, vizinho_anterior_close=227_000.0, peak=2_600_000.0,
                                 vizinho_seguinte_open=230_000.0)
        self.assertEqual(motivo, "candle_isolado_vs_vizinhos")

    def test_a_spike_that_persists_on_the_next_candle_is_cleared_a_real_move_not_a_glitch(self) -> None:
        bar = _bar(2_600_000.0, 2_700_000.0, 2_500_000.0, 2_650_000.0)
        motivo = motivo_suspeito(bar, vizinho_anterior_close=227_000.0, peak=2_700_000.0,
                                 vizinho_seguinte_open=2_640_000.0)
        self.assertIsNone(motivo)

    def test_custom_limiares_are_honored(self) -> None:
        # pico_candle=105, vizinho=30 -> razao 3.5x: dentro do limiar PADRAO (10x), fora do customizado (2x).
        limiares = LimiaresQualidadeCandle(razao_vizinho_max=2.0, razao_pico_max=1.5)
        bar = _bar(100.0, 105.0, 98.0, 102.0)
        self.assertIsNone(motivo_suspeito(bar, 30.0, 200.0, limiares=LimiaresQualidadeCandle()))
        self.assertEqual(motivo_suspeito(bar, 30.0, 200.0, vizinho_seguinte_open=30.0, limiares=limiares),
                         "candle_isolado_vs_vizinhos")


if __name__ == "__main__":
    unittest.main()
