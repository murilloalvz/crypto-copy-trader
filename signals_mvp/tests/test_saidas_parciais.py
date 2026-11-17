"""PEDIDO 2026-11-10 (autorizado, rodada 13): testes de `pos_runner/saidas_parciais.py` -- a grade
fechada de 24 variantes, os 5 gatilhos de TP1, os 3 restantes (segurar/breakeven/trailing), a
sensibilidade de custo (slippage de saida 2x/3x), e o congelamento do pre-registro por hash.
EXPLORATORIO -- apenas confere a implementacao contra o algoritmo exato do pre-registro."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.saidas_parciais import (
    GRADE_24,
    PreregistroAlteradoError,
    REMAINDER_BREAKEVEN,
    REMAINDER_SEGURAR,
    REMAINDER_TRAILING,
    TRIGGER_1R,
    TRIGGER_2R,
    TRIGGER_3R,
    TRIGGER_MEIO_TOPO_ANTERIOR,
    TRIGGER_TOPO_CAIXA,
    VarianteSaidaParcial,
    calcular_r_variante,
    garantir_saidas_parciais_registrada,
    hash_do_preregistro,
    _preco_alvo_tp1,
    _ultimo_fundo_ascendente,
)
from ..storage import Storage
from .test_exit_lab import _bars_vol

STEP = 3_600
COSTS = CostModel()


def _evento(idx: int, ts: int, stop: float, topo: float = 0.0, r_caixa: float = 0.0) -> EventV1:
    return EventV1(kind="ENTRADA", idx=idx, ts=ts, decision_ts=ts,
                  data={"stop": stop, "TOPO": topo, "R": r_caixa})


class VetoAmploOptInTests(unittest.TestCase):
    """RODADA 18 item 2: `veto='amplo'` (opt-in, default continua 'simples') usa o MESMO veto do
    caminho ao vivo -- candle isolado cujo salto e >10x o CLOSE do vizinho anterior mas NUNCA >10x o
    HIGH de ambos os vizinhos (o simples exige os 2)."""

    def test_simples_padrao_bate_o_stop_amplo_opt_in_marca_no_candle_limpo(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),    # idx0
            (100, 150, 96, 101, 10.0),    # idx1 -- entry=100
            (101, 1050, 70, 90, 10.0),    # idx2 -- spike isolado: low=70<=stop(80)
            (100, 103, 98, 101, 10.0),    # idx3 -- nao confirma o nivel do spike
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        r_simples = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                        horizonte_s=2 * STEP, now=bars[1].ts + 10 * STEP,
                                        variante=variante)
        r_amplo = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                      horizonte_s=2 * STEP, now=bars[1].ts + 10 * STEP,
                                      variante=variante, veto="amplo")
        self.assertEqual(r_simples.status, "resolvido")
        self.assertLess(r_simples.r_mult, -0.9, "veto simples (padrao) bate o stop no spike")
        self.assertEqual(r_amplo.status, "marcado")
        self.assertGreater(r_amplo.r_mult, r_simples.r_mult)


class GradeTests(unittest.TestCase):
    def test_grade_fechada_tem_exatamente_24_variantes_unicas(self) -> None:
        self.assertEqual(len(GRADE_24), 24)
        self.assertEqual(len({v.nome for v in GRADE_24}), 24)

    def test_fracao_50_so_nos_3_gatilhos_mais_distantes(self) -> None:
        gatilhos_50 = {v.tp1_trigger for v in GRADE_24 if v.tp1_frac == 0.50}
        self.assertEqual(gatilhos_50, {TRIGGER_1R, TRIGGER_3R, TRIGGER_MEIO_TOPO_ANTERIOR})

    def test_todos_os_5_gatilhos_tem_fracao_30(self) -> None:
        gatilhos_30 = {v.tp1_trigger for v in GRADE_24 if v.tp1_frac == 0.30}
        self.assertEqual(gatilhos_30, {TRIGGER_1R, TRIGGER_2R, TRIGGER_3R, TRIGGER_TOPO_CAIXA,
                                       TRIGGER_MEIO_TOPO_ANTERIOR})


class PrecoAlvoTp1Tests(unittest.TestCase):
    def test_alvos_em_r_fixo(self) -> None:
        ev = _evento(0, 0, stop=80.0)
        self.assertAlmostEqual(_preco_alvo_tp1(TRIGGER_1R, 100.0, ev), 120.0)
        self.assertAlmostEqual(_preco_alvo_tp1(TRIGGER_2R, 100.0, ev), 140.0)
        self.assertAlmostEqual(_preco_alvo_tp1(TRIGGER_3R, 100.0, ev), 160.0)

    def test_topo_caixa_usa_r_e_falta_r_e_sem_dado(self) -> None:
        ev = _evento(0, 0, stop=80.0, r_caixa=130.0)
        self.assertAlmostEqual(_preco_alvo_tp1(TRIGGER_TOPO_CAIXA, 100.0, ev), 130.0)
        ev_sem_r = EventV1(kind="ENTRADA", idx=0, ts=0, decision_ts=0, data={"stop": 80.0})
        self.assertIsNone(_preco_alvo_tp1(TRIGGER_TOPO_CAIXA, 100.0, ev_sem_r))

    def test_meio_topo_anterior_usa_metade_da_distancia_ao_topo(self) -> None:
        ev = _evento(0, 0, stop=80.0, topo=200.0)
        self.assertAlmostEqual(_preco_alvo_tp1(TRIGGER_MEIO_TOPO_ANTERIOR, 100.0, ev), 150.0)


class UltimoFundoAscendenteTests(unittest.TestCase):
    def test_2_pivos_ascendentes_devolve_o_mais_recente(self) -> None:
        self.assertAlmostEqual(_ultimo_fundo_ascendente([(5, 130.0), (8, 140.0)]), 140.0)

    def test_2_pivos_nao_ascendentes_devolve_none(self) -> None:
        self.assertIsNone(_ultimo_fundo_ascendente([(5, 140.0), (8, 130.0)]))

    def test_menos_de_2_pivos_devolve_none(self) -> None:
        self.assertIsNone(_ultimo_fundo_ascendente([(5, 130.0)]))
        self.assertIsNone(_ultimo_fundo_ascendente([]))


class CalcularRVarianteTests(unittest.TestCase):
    def test_entrada_fora_do_stop_fica_sem_dado(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (70, 101, 69, 100, 10.0)])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        r = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                horizonte_s=STEP, now=bars[1].ts + 5 * STEP, variante=variante)
        self.assertEqual(r.status, "sem_dado")

    def test_horizonte_nao_decorrido_fica_pendente(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        r = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                horizonte_s=2 * STEP, now=bars[1].ts + STEP, variante=variante)
        self.assertEqual(r.status, "pendente")

    def test_stop_original_bate_antes_do_tp1(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),    # idx1 -- entry=100
            (101, 102, 70, 75, 10.0),                                # idx2 -- low<=stop(80)
        ])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        r = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP, variante=variante)
        self.assertEqual(r.status, "resolvido")
        self.assertFalse(r.tp1_realizado)
        self.assertLess(r.r_mult, 0.0)

    def test_tp1_e_segurar_nunca_move_o_stop(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),    # idx1 -- entry=100
            (101, 125, 99, 120, 10.0),                               # idx2 -- toca +1R(120)
            (120, 121, 119, 120, 10.0),                              # idx3 -- TP1 executa open=120
            (120, 121, 85, 90, 10.0),                                # idx4 -- low=85 > stop(80), > entry(100)? nao
        ])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        r = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP, variante=variante)
        self.assertEqual(r.status, "marcado")   # nunca bateu o stop(80) nem o horizonte fechou por regra
        self.assertTrue(r.tp1_realizado)

    def test_tp1_e_breakeven_fecha_no_entry_quando_low_toca_entry(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),    # idx1 -- entry=100
            (101, 125, 99, 120, 10.0),                               # idx2 -- toca +1R(120)
            (120, 121, 119, 120, 10.0),                              # idx3 -- TP1 executa open=120
            (120, 121, 95, 98, 10.0),                                # idx4 -- low=95 <= entry(100)
        ])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_BREAKEVEN)
        r = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP, variante=variante)
        self.assertEqual(r.status, "resolvido")
        self.assertTrue(r.tp1_realizado)
        self.assertAlmostEqual(r.r_leg2, 0.0)   # saida no breakeven = entry -- r_leg2 = 0 pre-custo

    def test_trailing_nunca_breakeven_so_stop_original_mais_fechamento_vermelho(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),      # idx0
            (100, 102, 96, 101, 10.0),      # idx1 -- entry=100
            (101, 125, 99, 120, 10.0),      # idx2 -- toca +1R(120)
            (120, 121, 119, 120, 10.0),     # idx3 -- TP1 executa open=120
            (120, 125, 95, 98, 10.0),       # idx4 -- low=95 <= entry(100) MAS > stop(80) -- trailing
                                            # nunca usa breakeven, so o stop ORIGINAL -- nunca fecha aqui.
            (98, 99, 97, 98, 10.0),         # idx5
        ])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_TRAILING)
        r = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP, variante=variante)
        self.assertEqual(r.status, "marcado")   # nunca fechou por regra -- nem stop original, nem pivo
        self.assertTrue(r.tp1_realizado)

    def test_sensibilidade_de_custo_2x_nunca_melhora_o_resultado(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),
            (101, 125, 99, 120, 10.0), (120, 121, 119, 120, 10.0),
            (120, 121, 85, 90, 10.0),
        ])
        ev = _evento(0, bars[0].ts, stop=80.0)
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        kwargs = dict(t_entrada=bars[1].ts, horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP,
                     variante=variante)
        r1 = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, **kwargs, slippage_saida_mult=1.0)
        r2 = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, **kwargs, slippage_saida_mult=2.0)
        r3 = calcular_r_variante(bars, ev, COSTS, "desconhecido", None, **kwargs, slippage_saida_mult=3.0)
        self.assertGreaterEqual(r1.r_mult, r2.r_mult)
        self.assertGreaterEqual(r2.r_mult, r3.r_mult)


class PreregistroHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="saidas_parciais_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1a_chamada_registra_e_as_seguintes_sao_idempotentes(self) -> None:
        h1 = garantir_saidas_parciais_registrada(self.storage)
        h2 = garantir_saidas_parciais_registrada(self.storage)
        self.assertEqual(h1, h2)
        self.assertEqual(h1, hash_do_preregistro())

    def test_texto_alterado_depois_do_registro_recusa(self) -> None:
        garantir_saidas_parciais_registrada(self.storage)
        self.storage.set_meta("saidas_parciais_preregistro_hash", "0" * 12)
        with self.assertRaises(PreregistroAlteradoError):
            garantir_saidas_parciais_registrada(self.storage)


if __name__ == "__main__":
    unittest.main()
