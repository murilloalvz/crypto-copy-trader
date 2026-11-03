"""POS-RUNNER-V1: gestao de banca hibrida (item 2.10) e o ledger (BankrollLedgerV1). Sem rede."""

from __future__ import annotations

import unittest

from ..pos_runner.bankroll_v1 import BankrollLedgerV1, BankrollStateV1, tamanho_posicao_usd
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.params_v1 import ParamsV1

H = 3600
T0 = 1_790_000_000 - (1_790_000_000 % H)


class TamanhoPosicaoTests(unittest.TestCase):
    def test_fixed_hand_below_the_limit(self):
        self.assertEqual(tamanho_posicao_usd(150.0, ParamsV1()), 10.0)

    def test_fraction_of_bankroll_at_or_above_the_limit(self):
        self.assertAlmostEqual(tamanho_posicao_usd(300.0, ParamsV1()), 30.0)

    def test_never_exceeds_the_bankroll_itself(self):
        self.assertAlmostEqual(tamanho_posicao_usd(5.0, ParamsV1()), 5.0)

    def test_zero_bankroll_sizes_to_zero(self):
        self.assertEqual(tamanho_posicao_usd(0.0, ParamsV1()), 0.0)


def _ev(idx: int = 0) -> EventV1:
    return EventV1("ENTRADA", idx, T0 + idx * H, T0 + (idx + 1) * H,
                   {"stop": 50.0, "TOPO": 300.0, "S": 100.0})


class BankrollLedgerV1Tests(unittest.TestCase):
    def setUp(self):
        self.params = ParamsV1()
        self.costs = CostModel(terminal_pct=0.0, network_sol=0.0, multiplier=1.0)
        self.ledger = BankrollLedgerV1(self.params, self.costs)

    def _bars(self):
        return [
            Bar(T0, 100, 100, 100, 100, 1),
            Bar(T0 + H, 110, 120, 105, 115, 1),
            Bar(T0 + 2 * H, 109, 112, 40, 42, 1),   # stop (abaixo de 50)
        ]

    def test_step_records_a_closed_trade_and_updates_the_bankroll(self):
        bars = self._bars()
        linha = self.ledger.step(bars, _ev(), "pumpswap", None, lambda ts: 150.0, {"token": "AAA", "tf": "1h"})
        self.assertIsNotNone(linha)
        self.assertEqual(linha["motivo_saida"], "stop")
        self.assertEqual(linha["tamanho_posicao_usd"], 10.0)   # banca inicial 100 < 200: mao fixa
        self.assertLess(linha["banca_depois_usd"], self.params.banca_inicial_usd)
        self.assertEqual(self.ledger.state.n_trades, 1)

    def test_skips_without_a_sol_usd_quote(self):
        bars = self._bars()
        linha = self.ledger.step(bars, _ev(), "pumpswap", None, lambda ts: None, {"token": "AAA", "tf": "1h"})
        self.assertEqual(linha["motivo_saida"], "sem dado: sol/usd")
        self.assertEqual(self.ledger.state.n_trades, 0)

    def test_daily_stop_pauses_after_enough_losing_trades(self):
        for i in range(self.params.stop_diario_perdas_seguidas):
            base = T0 + i * 3 * H
            bars = [Bar(base, 100, 100, 100, 100, 1), Bar(base + H, 110, 120, 105, 115, 1),
                   Bar(base + 2 * H, 109, 112, 40, 42, 1)]
            self.ledger.step(bars, _ev(0), "pumpswap", None, lambda ts: 150.0, {"token": "AAA", "tf": "1h"})
        self.assertTrue(self.ledger.state.dia_pausado)
        base = T0 + int(8.5 * H)   # mesmo dia UTC (poucas horas depois), ainda pausado
        bars = [Bar(base, 100, 100, 100, 100, 1), Bar(base + H, 110, 120, 105, 115, 1),
               Bar(base + 2 * H, 109, 112, 40, 42, 1)]
        linha = self.ledger.step(bars, _ev(0), "pumpswap", None, lambda ts: 150.0, {"token": "AAA", "tf": "1h"})
        self.assertEqual(linha["motivo_saida"], "pulado: stop diário")

    def test_state_roundtrips_through_json(self):
        bars = self._bars()
        self.ledger.step(bars, _ev(), "pumpswap", None, lambda ts: 150.0, {"token": "AAA", "tf": "1h"})
        restored = BankrollStateV1.from_json(self.ledger.state.to_json())
        self.assertEqual(restored.banca, self.ledger.state.banca)
        self.assertEqual(restored.n_trades, self.ledger.state.n_trades)


if __name__ == "__main__":
    unittest.main()
