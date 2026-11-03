"""PEDIDO 2026-11-02 (POS-RUNNER-V3, Passo 1): "ideia pura: segunda corrida pos-queda". ZERO codigo
novo de deteccao -- `ParamsV3` (params_v3.py) e `ParamsV1` com 2 defaults proprios + hash proprio
(`POS_RUNNER_TAG="V3"`); o detector/simulador reusados sao os MESMOS de detector_v1.py/simulate_v1.py
(testados em test_pos_runner_v1.py). Aqui: (1) regressao -- ParamsV3 com os valores da V1 reproduz
EXATAMENTE os sinais da V1; zone_min_candles=4 gera mais sinais que 12 (mesma caixa curta); pool de
1 dia e aceito pela V3 mas rejeitado pela V1 (idade); fundo abaixo de L_bc e rejeitado pelas DUAS
(invariante compartilhado, nunca uma regra nova da V3); (2) covariaveis puras de `pos_runner_v3.py`.
"""

from __future__ import annotations

import dataclasses
import unittest

from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.params_v1 import ParamsV1
from ..pos_runner.params_v3 import ParamsV3, load_params_v3
from ..pos_runner.pos_runner_v3 import (
    calcular_covariaveis_v3,
    posicao_pct_supply,
    possivel_clone,
)
from .test_pos_runner_v1 import CREATED, GRAD, H, L_BC, Series, params, textbook_v1


def _eventos(det: DetectorV1) -> list[dict]:
    return [dataclasses.asdict(e) for e in det.events]


class ParamsV3HashTests(unittest.TestCase):
    def test_v3_has_its_own_hash_tag_even_with_the_exact_v1_values(self) -> None:
        """"Hash proprio": mesmo um ParamsV3 construido com os VALORES por-campo da V1 (as_dict()
        identico) tem um `version` DIFERENTE do da V1 -- a tag de identidade ("V3"), nao o conteudo
        dos parametros, e quem garante isso (ver params_v1.py: POS_RUNNER_TAG)."""
        p1 = ParamsV1()
        p3_valores_v1 = ParamsV3(zone_min_candles=12, age_window_days=(2.0, 7.0), drop_max=0.90)
        self.assertEqual(p3_valores_v1.as_dict(), p1.as_dict())
        self.assertNotEqual(p3_valores_v1.version, p1.version)

    def test_v1_and_v2_hashes_are_untouched_by_the_v3_refactor(self) -> None:
        from ..pos_runner.params_v2 import load_params_v2
        self.assertEqual(ParamsV1().version, "279b79ffa3f0")
        self.assertEqual(load_params_v2().version, "d57b4331d51d")

    def test_default_v3_config_has_no_age_floor_or_ceiling_and_zone_min_candles_4(self) -> None:
        p3 = load_params_v3()
        self.assertEqual(p3.zone_min_candles, 4)
        self.assertEqual(p3.age_window_days, (0.0, 36_500.0))
        self.assertEqual(p3.drop_min, 0.80)
        self.assertEqual(p3.drop_max, 0.96)
        # "demais limiares iguais aos da V1" -- confere ALGUNS dos nao-mexidos, nunca todos por extenso.
        self.assertEqual(p3.runner_min_mc, 300_000.0)
        self.assertEqual(p3.min_mc_usd, 100_000.0)
        self.assertEqual(p3.stop_below_wick_pct, 0.02)
        self.assertEqual(p3.l_bc_floor_usd, 5_000.0)


class RegressaoDetectorCompartilhadoTests(unittest.TestCase):
    """ZERO codigo novo de deteccao: estes 4 testes confirmam que `ParamsV3` so muda VALORES de
    parametro, nunca a mecanica do `DetectorV1` em si."""

    def test_params_v3_with_v1_values_reproduces_the_exact_v1_signals(self) -> None:
        bars = textbook_v1().bars
        p1 = ParamsV1()
        p3_valores_v1 = ParamsV3(zone_min_candles=12, age_window_days=(2.0, 7.0), drop_max=0.90)
        det1 = DetectorV1(p1, "1h", L_BC, GRAD, CREATED)
        det3 = DetectorV1(p3_valores_v1, "1h", L_BC, GRAD, CREATED)
        for b in bars:
            det1.update(b)
            det3.update(b)
        self.assertGreaterEqual(len([e for e in det1.events if e.kind == "ENTRADA"]), 1)
        self.assertEqual(_eventos(det1), _eventos(det3))

    def test_zone_min_candles_4_generates_a_signal_that_12_never_would_on_the_same_short_box(self) -> None:
        """Caixa curta (comprimento 4, 1 pavio) armada pela V3 (zone_min_candles=4) MAS NUNCA pela V1
        (zone_min_candles=12) -- MESMOS candles, MESMO resto dos parametros, a UNICA diferenca e esse
        piso estrutural."""
        s = Series()
        s.flat(60_000, 2)                                          # 0-1
        for p in (150_000, 300_000, 600_000, 900_000):              # 2-5
            s.add(p * 0.9, p * 1.02, p * 0.88, p)
        s.add(900_000, 1_000_000, 880_000, 950_000)                 # 6: pico (P_peak=1.000.000)
        for p in (800_000, 600_000, 400_000, 250_000):              # 7-10
            s.add(p * 1.1, p * 1.12, p * 0.97, p)
        s.add(250_000, 255_000, 155_000, 165_000)                   # 11: queda 84,5% -> FASE2/fundo (S=155k)
        s.add(165_000, 300_000, 160_000, 280_000)                   # 12: recupera -> ancora (R=300k)
        s.add(280_000, 285_000, 160_000, 270_000)                   # 13: pavio (dip no teste de suporte)
        s.add(270_000, 290_000, 200_000, 280_000)                   # 14: recupera o teste -> length=4, n_testes=1
        s.add(280_000, 350_000, 275_000, 340_000, v=10_000.0)       # 15: rompimento (volume 10x a media da caixa)
        bars = s.bars
        p1, p3 = ParamsV1(), ParamsV3()
        det1 = DetectorV1(p1, "1h", L_BC, GRAD, CREATED)
        det3 = DetectorV1(p3, "1h", L_BC, GRAD, CREATED)
        for b in bars:
            det1.update(b)
            det3.update(b)
        self.assertNotIn("WATCHLIST", [e.kind for e in det1.events], "V1 (12 candles) nunca deveria armar aqui")
        self.assertNotIn("ENTRADA", [e.kind for e in det1.events])
        self.assertIn("WATCHLIST", [e.kind for e in det3.events], "V3 (4 candles) precisa armar com essa caixa curta")
        self.assertIn("ENTRADA", [e.kind for e in det3.events])

    def test_a_1_day_old_pool_is_accepted_by_v3_but_rejected_by_v1_on_age(self) -> None:
        bars = textbook_v1().bars
        created_ts = GRAD   # idade na entrada (~idx25, ~25h depois da graduacao) fica em ~1,08 dia
        p1, p3 = ParamsV1(), ParamsV3()
        det1 = DetectorV1(p1, "1h", L_BC, GRAD, created_ts)
        det3 = DetectorV1(p3, "1h", L_BC, GRAD, created_ts)
        for b in bars:
            det1.update(b)
            det3.update(b)
        kinds1 = {e.kind for e in det1.events if e.kind in ("ENTRADA", "FORA_DA_IDADE")}
        kinds3 = {e.kind for e in det3.events if e.kind in ("ENTRADA", "FORA_DA_IDADE")}
        self.assertEqual(kinds1, {"FORA_DA_IDADE"})
        self.assertEqual(kinds3, {"ENTRADA"})

    def test_a_box_bottom_below_l_bc_is_rejected_by_both_v1_and_v3(self) -> None:
        """Invariante COMPARTILHADO (detector_v1.py: `_kills_wave`) -- a V3 nunca precisa de uma regra
        nova pra isso, so herda."""
        bars = textbook_v1().bars
        l_bc_alto = 200_000.0   # acima do fundo real (~155k) -- fura o nivel de graduacao
        p1, p3 = ParamsV1(), ParamsV3()
        det1 = DetectorV1(p1, "1h", l_bc_alto, GRAD, CREATED)
        det3 = DetectorV1(p3, "1h", l_bc_alto, GRAD, CREATED)
        for b in bars:
            det1.update(b)
            det3.update(b)
        for det in (det1, det3):
            kinds = [e.kind for e in det.events]
            self.assertIn("ONDA_INVALIDA", kinds)
            self.assertNotIn("ENTRADA", kinds)


class CovariaveisV3Tests(unittest.TestCase):
    def _entrada_textbook(self) -> tuple[list[Bar], object]:
        bars = textbook_v1().bars
        p3 = ParamsV3()
        det = DetectorV1(p3, "1h", L_BC, GRAD, CREATED)
        ev_entrada = None
        for b in bars:
            for ev in det.update(b):
                if ev.kind == "ENTRADA":
                    ev_entrada = ev
        assert ev_entrada is not None
        return bars, ev_entrada

    def test_covariaveis_read_straight_off_the_entrada_event_data(self) -> None:
        bars, ev = self._entrada_textbook()
        cov = calcular_covariaveis_v3(bars, ev, H, L_BC)
        self.assertEqual(cov.caixa_candles, ev.data["box_len"])
        self.assertAlmostEqual(cov.caixa_horas, ev.data["box_len"] * H / 3600.0)
        self.assertEqual(cov.idade_dias, ev.data["idade_dias"])
        self.assertEqual(cov.queda_pico_pct, ev.data["queda_pct"])
        self.assertEqual(cov.mc_pico, ev.data["P_peak"])
        self.assertEqual(cov.mc_base, ev.data["S"])
        self.assertEqual(cov.n_pavios, ev.data["n_testes"])
        self.assertAlmostEqual(cov.razao_base_l_bc, ev.data["S"] / L_BC)
        self.assertAlmostEqual(cov.tempo_desde_pico_h, (ev.decision_ts - ev.data["peak_ts"]) / 3600.0)
        self.assertIn(cov.gatilho_tag, ("reacao_suporte", "rompimento", "reacao_suporte+rompimento"))
        self.assertFalse(cov.possivel_clone)   # sem outros_pools passado -- nunca adivinha

    def test_razao_base_l_bc_is_none_without_l_bc(self) -> None:
        bars, ev = self._entrada_textbook()
        cov = calcular_covariaveis_v3(bars, ev, H, None)
        self.assertIsNone(cov.razao_base_l_bc)

    def test_gatilho_tag_combines_both_when_the_same_candle_fires_two_triggers(self) -> None:
        from ..pos_runner.detector_v1 import EventV1
        ev = EventV1("ENTRADA", 0, 0, H, {"gatilho": ["reacao_suporte", "power_candle_rompimento"],
                                          "box_len": 1, "S": 100.0, "P_peak": 200.0, "R": 150.0,
                                          "atr": 1.0, "peak_ts": 0, "n_testes": 1, "testes": [],
                                          "idade_dias": None, "queda_pct": None})
        bars = [Bar(0, 1.0, 2.0, 0.5, 1.5, 10.0)]
        cov = calcular_covariaveis_v3(bars, ev, H, None)
        self.assertEqual(cov.gatilho_tag, "reacao_suporte+rompimento")

    def test_descomunal_ratio_is_none_when_the_box_ceiling_never_cleared_the_peak(self) -> None:
        from ..pos_runner.detector_v1 import EventV1
        ev = EventV1("ENTRADA", 0, 0, H, {"gatilho": [], "box_len": 1, "S": 100.0, "P_peak": 150.0,
                                          "R": 150.0, "atr": 1.0, "peak_ts": 0, "n_testes": 0,
                                          "testes": [], "idade_dias": None, "queda_pct": None})
        bars = [Bar(0, 1.0, 2.0, 0.5, 1.5, 10.0)]
        cov = calcular_covariaveis_v3(bars, ev, H, None)
        self.assertIsNone(cov.razao_corpo_descomunal)


class PossivelCloneTests(unittest.TestCase):
    def test_true_when_another_discovered_pool_shares_the_symbol_and_launched_earlier(self) -> None:
        self.assertTrue(possivel_clone("MOON", 2_000.0, [("moon", 1_000.0), ("OTHER", 1_500.0)]))

    def test_false_when_the_earlier_namesake_does_not_exist(self) -> None:
        self.assertFalse(possivel_clone("MOON", 1_000.0, [("MOON", 2_000.0), ("OTHER", 500.0)]))

    def test_false_without_symbol_or_found_ts_never_guessed(self) -> None:
        self.assertFalse(possivel_clone(None, 1_000.0, [("MOON", 500.0)]))
        self.assertFalse(possivel_clone("MOON", None, [("MOON", 500.0)]))


class PosicaoPctSupplyTests(unittest.TestCase):
    def test_uses_mao_fixa_below_the_bankroll_threshold(self) -> None:
        p = ParamsV3()   # mao_fixa_usd=10, banca_fixa_limite_usd=200
        pct = posicao_pct_supply(entry_price=0.001, supply=1_000_000_000.0, banca_usd=100.0, params=p)
        # posicao_usd=10 -> tokens=10/0.001=10000 -> pct=100*10000/1e9=0.001%
        self.assertAlmostEqual(pct, 0.001)

    def test_uses_posicao_frac_above_the_bankroll_threshold_and_flags_over_1_5_pct(self) -> None:
        p = ParamsV3()   # posicao_frac=0.10
        pct = posicao_pct_supply(entry_price=0.0001, supply=1_000_000.0, banca_usd=1_000.0, params=p)
        # posicao_usd=100 -> tokens=100/0.0001=1_000_000 -> pct=100*1e6/1e6=100% (supply pequeno de proposito)
        self.assertGreater(pct, 1.5)

    def test_none_without_supply_or_entry_price(self) -> None:
        p = ParamsV3()
        self.assertIsNone(posicao_pct_supply(1.0, None, 100.0, p))
        self.assertIsNone(posicao_pct_supply(0.0, 1_000.0, 100.0, p))


if __name__ == "__main__":
    unittest.main()
