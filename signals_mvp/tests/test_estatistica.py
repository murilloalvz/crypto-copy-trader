"""RODADA 22 (2026-11-17): `wilson_ci` -- testado por PROPRIEDADES (nunca so um valor memorizado),
ja que o calculo em si e so algebra simples e bem documentada (Wilson score interval)."""

from __future__ import annotations

import unittest

from ..pos_runner.estatistica import wilson_ci


class WilsonCiTests(unittest.TestCase):
    def test_sem_dado_devolve_intervalo_maximo(self) -> None:
        self.assertEqual(wilson_ci(0, 0), (0.0, 1.0))

    def test_limites_sempre_dentro_de_0_1(self) -> None:
        for sucessos, n in ((0, 10), (10, 10), (5, 10), (1, 1000), (999, 1000)):
            lo, hi = wilson_ci(sucessos, n)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)
            self.assertLess(lo, hi)

    def test_intervalo_contem_a_proporcao_observada(self) -> None:
        for sucessos, n in ((3, 20), (10, 100), (1, 7)):
            lo, hi = wilson_ci(sucessos, n)
            p = sucessos / n
            self.assertLessEqual(lo, p)
            self.assertGreaterEqual(hi, p)

    def test_intervalo_encolhe_conforme_n_cresce_mesma_proporcao(self) -> None:
        lo10, hi10 = wilson_ci(1, 10)
        lo100, hi100 = wilson_ci(10, 100)
        lo1000, hi1000 = wilson_ci(100, 1000)
        self.assertGreater(hi10 - lo10, hi100 - lo100)
        self.assertGreater(hi100 - lo100, hi1000 - lo1000)

    def test_sucesso_total_nunca_da_largura_zero_ao_contrario_do_normal_wald(self) -> None:
        lo, hi = wilson_ci(5, 5)
        self.assertLess(lo, 1.0)
        self.assertEqual(hi, 1.0)

    def test_zero_sucessos_nunca_da_largura_zero(self) -> None:
        lo, hi = wilson_ci(0, 5)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)

    def test_z_maior_alarga_o_intervalo(self) -> None:
        lo95, hi95 = wilson_ci(5, 20, z=1.96)
        lo99, hi99 = wilson_ci(5, 20, z=2.576)
        self.assertLessEqual(lo99, lo95)
        self.assertGreaterEqual(hi99, hi95)

    def test_sucessos_fora_da_faixa_levanta_valueerror(self) -> None:
        with self.assertRaises(ValueError):
            wilson_ci(11, 10)
        with self.assertRaises(ValueError):
            wilson_ci(-1, 10)


if __name__ == "__main__":
    unittest.main()
