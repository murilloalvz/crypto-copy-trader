"""PEDIDO 2026-11-12 (autorizado, rodada 19, item 3): teste de `pos_runner/costs.py:
CostModel.custo_ida_e_volta_em_r` -- fracao de R que o custo modelado (fee+rede+slippage, ida+volta)
representa, usada pra decompor perdas maiores que -1R em stops curtos. EXPLORATORIO -- so confere a
mecanica aritmetica, nunca testa edge economica."""

from __future__ import annotations

import unittest

from ..pos_runner.costs import CostModel


class CustoIdaEVoltaEmRTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cm = CostModel()

    def test_pior_caso_sem_l_bc_nem_sol_usd_usa_os_tetos_conservadores(self) -> None:
        r = self.cm.custo_ida_e_volta_em_r("pumpswap", mc_usd=300_000.0, l_bc=None, sol_usd=None,
                                          risco_frac=0.127)
        # leg_pct pior caso = 1,25 (teto) + 1,0 (terminal) + 0,2 (rede) + 1,0 (slippage sem dado) = 3,45%
        # ida+volta = 6,9% -> em R (risco 12,7%) = 0,069/0,127
        self.assertAlmostEqual(r, 0.069 / 0.127, places=6)

    def test_liquidez_robusta_custa_menos_em_r_que_liquidez_desconhecida(self) -> None:
        pior = self.cm.custo_ida_e_volta_em_r("pumpswap", mc_usd=300_000.0, l_bc=None, sol_usd=None,
                                             risco_frac=0.127)
        robusto = self.cm.custo_ida_e_volta_em_r("pumpswap", mc_usd=5_000_000.0, l_bc=5_000_000.0,
                                                sol_usd=150.0, risco_frac=0.127)
        self.assertLess(robusto, pior)

    def test_risco_menor_aumenta_o_custo_em_r_mesmo_custo_pct(self) -> None:
        """Stop MAIS CURTO (risco_frac menor) -> o MESMO custo em % pesa MAIS em R -- e exatamente o
        ponto do item 3 (stops curtos sofrem mais do custo relativo)."""
        r_largo = self.cm.custo_ida_e_volta_em_r("pumpswap", mc_usd=300_000.0, l_bc=5_000_000.0,
                                                 sol_usd=150.0, risco_frac=0.30)
        r_curto = self.cm.custo_ida_e_volta_em_r("pumpswap", mc_usd=300_000.0, l_bc=5_000_000.0,
                                                 sol_usd=150.0, risco_frac=0.127)
        self.assertGreater(r_curto, r_largo)

    def test_multiplicador_2x_dobra_o_custo_em_r(self) -> None:
        cm2x = CostModel(multiplier=2.0)
        r1x = self.cm.custo_ida_e_volta_em_r("pumpswap", mc_usd=300_000.0, l_bc=None, sol_usd=None,
                                            risco_frac=0.127)
        r2x = cm2x.custo_ida_e_volta_em_r("pumpswap", mc_usd=300_000.0, l_bc=None, sol_usd=None,
                                         risco_frac=0.127)
        self.assertAlmostEqual(r2x, 2.0 * r1x, places=6)


if __name__ == "__main__":
    unittest.main()
