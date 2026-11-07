"""PEDIDO 2026-11-06 (autorizado, rodada 12, Parte 1): testes de `pos_runner/saida_fiel.py` -- os 4
desfechos (pendente/resolvido/marcado/sem_dado), os 2 gatilhos do TP1 (power candle OU topo anterior,
OR nao AND), a prioridade do breakeven sobre o fechamento vermelho no MESMO candle, o fallback
pivo-unico/reta-de-2-pontos de `_nivel_tendencia_ou_fundo`, candle corrompido nunca decide, zero
lookahead no corte do horizonte, e o congelamento do pre-registro por hash. EXPLORATORIO -- apenas
confere a implementacao contra o algoritmo exato do pre-registro, nunca testa edge economica."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.saida_fiel import (
    PreregistroAlteradoError,
    calcular_r_saida_fiel,
    garantir_saida_fiel_registrada,
    hash_do_preregistro,
    _nivel_tendencia_ou_fundo,
    _pivo_confirmado,
)
from ..storage import Storage
from .test_exit_lab import _bars_vol

STEP = 3_600
PARAMS = load_params_v1()
COSTS = CostModel()


def _evento(idx: int, ts: int, stop: float, topo: float) -> EventV1:
    return EventV1(kind="ENTRADA", idx=idx, ts=ts, decision_ts=ts, data={"stop": stop, "TOPO": topo, "S": 0.0})


class PivoConfirmadoTests(unittest.TestCase):
    def test_minima_menor_que_as_4_vizinhas_e_pivo(self) -> None:
        bars = _bars_vol([(0, 0, 150, 0, 0), (0, 0, 140, 0, 0), (0, 0, 130, 0, 0),
                          (0, 0, 135, 0, 0), (0, 0, 145, 0, 0)])
        self.assertTrue(_pivo_confirmado(bars, 2))

    def test_minima_nao_menor_que_alguma_vizinha_nunca_e_pivo(self) -> None:
        bars = _bars_vol([(0, 0, 150, 0, 0), (0, 0, 120, 0, 0), (0, 0, 130, 0, 0),
                          (0, 0, 135, 0, 0), (0, 0, 145, 0, 0)])
        self.assertFalse(_pivo_confirmado(bars, 2))   # vizinho i-1(120) < candidato(130)

    def test_sem_as_2_vizinhas_de_cada_lado_nunca_e_pivo(self) -> None:
        bars = _bars_vol([(0, 0, 150, 0, 0), (0, 0, 130, 0, 0), (0, 0, 145, 0, 0)])
        self.assertFalse(_pivo_confirmado(bars, 1))   # i-2 nao existe
        self.assertFalse(_pivo_confirmado(bars, 0))
        self.assertFalse(_pivo_confirmado(bars, 2))   # i+2 nao existe


class NivelTendenciaOuFundoTests(unittest.TestCase):
    def test_2_pivos_ascendentes_dao_a_reta_extrapolada(self) -> None:
        nivel = _nivel_tendencia_ou_fundo([(5, 130.0), (8, 140.0)], 11)
        self.assertAlmostEqual(nivel, 150.0)   # slope=10/3, 140+10/3*3=150

    def test_2_pivos_nao_ascendentes_usa_o_ultimo_fundo_unico(self) -> None:
        nivel = _nivel_tendencia_ou_fundo([(5, 140.0), (8, 130.0)], 11)
        self.assertAlmostEqual(nivel, 130.0)

    def test_so_1_pivo_usa_o_ultimo_fundo_unico(self) -> None:
        self.assertAlmostEqual(_nivel_tendencia_ou_fundo([(5, 130.0)], 11), 130.0)

    def test_nenhum_pivo_nunca_inventa_nivel(self) -> None:
        self.assertIsNone(_nivel_tendencia_ou_fundo([], 11))


class SemDadoPendenteTests(unittest.TestCase):
    def test_entrada_fora_do_stop_topo_fica_sem_dado(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (70, 101, 69, 100, 10.0)])   # open(70) <= stop(80)
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=STEP, now=bars[1].ts + 5 * STEP)
        self.assertEqual(r.status, "sem_dado")

    def test_sem_candle_de_entrada_disponivel_fica_pendente(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0)])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[0].ts,
                                  horizonte_s=STEP, now=bars[0].ts + 5 * STEP)
        self.assertEqual(r.status, "pendente")

    def test_horizonte_ainda_nao_decorrido_fica_pendente(self) -> None:
        bars = _bars_vol([(100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0)])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=2 * STEP, now=bars[1].ts + STEP)
        self.assertEqual(r.status, "pendente")
        self.assertIsNone(r.r_mult)


class ResolvidoPeloStopAntesDoTp1Tests(unittest.TestCase):
    def test_stop_original_tem_prioridade_antes_do_tp1(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),
            (100, 102, 96, 101, 10.0),    # entry=100
            (101, 102, 70, 75, 10.0),     # low=70 <= stop(80) -- fecha aqui, nunca viu TP1
            (75, 80, 74, 78, 10.0),
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=10_000.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP)
        self.assertEqual(r.status, "resolvido")
        self.assertFalse(r.tp1_realizado)
        self.assertIsNotNone(r.r_mult)
        self.assertLess(r.r_mult, 0.0)


class Tp1PorTopoAnteriorTests(unittest.TestCase):
    def test_toque_no_topo_dispara_tp1_mesmo_sem_power_candle(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),
            (100, 102, 96, 101, 10.0),     # idx1 -- entry=100
            (101, 205, 100, 150, 10.0),    # idx2 -- high>=topo(200) -- NUNCA e power candle (sem ATR)
            (150, 156, 148, 152, 10.0),    # idx3 -- TP1 executa no open=150
            (152, 153, 95, 97, 10.0),      # idx4 -- breakeven (low<=entry)
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=200.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP)
        self.assertEqual(r.status, "resolvido")
        self.assertTrue(r.tp1_realizado)

    def test_candle_corrompido_toca_o_topo_mas_nunca_decide(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),
            (100, 102, 96, 101, 10.0),     # idx1 -- entry=100
            (101, 250, 100, 150, 0.0),     # idx2 -- volume=0 (corrompido) -- toca topo mas e ignorado
            (150, 151, 149, 150, 10.0),    # idx3 -- limpo, high(151) < topo(200) -- ainda nao disparou
            (150, 205, 149, 160, 10.0),    # idx4 -- limpo, toca topo de verdade
            (160, 165, 158, 162, 10.0),    # idx5 -- TP1 executa no open=160
            (162, 163, 95, 97, 10.0),      # idx6 -- breakeven
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=200.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP)
        self.assertEqual(r.status, "resolvido")
        self.assertTrue(r.tp1_realizado)


class Tp1PorPowerCandleTests(unittest.TestCase):
    def test_power_candle_dispara_tp1_sem_tocar_o_topo(self) -> None:
        flat = [(100, 101, 99, 100, 10.0)] * 20               # idx0..19 -- ATR baixo
        power = [(100, 110, 99, 105, 10.0)]                   # idx20 -- range=11 >= 3*ATR(~2)
        exec_bar = [(105, 107, 103, 106, 10.0)]                # idx21 -- TP1 executa no open=105
        breakeven = [(106, 108, 95, 98, 10.0)]                 # idx22 -- breakeven
        bars = _bars_vol(flat + power + exec_bar + breakeven)
        ev = _evento(0, bars[0].ts, stop=80.0, topo=100_000.0)   # topo inalcancavel -- so o power decide
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP)
        self.assertEqual(r.status, "resolvido")
        self.assertTrue(r.tp1_realizado)


class BreakevenPrioridadeTests(unittest.TestCase):
    def test_breakeven_tem_prioridade_sobre_fechamento_vermelho_no_mesmo_candle(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),
            (100, 102, 96, 101, 10.0),     # idx1 -- entry=100
            (101, 205, 100, 150, 10.0),    # idx2 -- toca topo
            (150, 156, 148, 152, 10.0),    # idx3 -- TP1 executa
            # idx4: low<=entry (breakeven) E close<open (vermelho) no MESMO candle -- breakeven decide.
            (152, 153, 95, 96, 10.0),
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=200.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP)
        self.assertEqual(r.status, "resolvido")
        self.assertTrue(r.tp1_realizado)
        # saida = max(entry, low) = max(100, 95) = 100 -- preco de saida e o ENTRY, nunca o close(96).


class SaidaPorTendenciaDoisPivosAscendentesTests(unittest.TestCase):
    def test_fechamento_vermelho_abaixo_da_reta_de_2_pivos_ascendentes_fecha_o_resto(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),     # idx0
            (100, 102, 96, 101, 10.0),     # idx1 -- entry=100
            (101, 205, 100, 150, 10.0),    # idx2 -- toca topo=200
            (150, 156, 148, 152, 10.0),    # idx3 -- TP1 executa (open=150); low=148 > entry
            (152, 157, 150, 155, 10.0),    # idx4
            (155, 158, 130, 135, 10.0),    # idx5 -- pivo P1 (low=130)
            (160, 165, 160, 163, 10.0),    # idx6
            (163, 168, 165, 166, 10.0),    # idx7 -- P1 confirmado aqui
            (166, 170, 140, 145, 10.0),    # idx8 -- pivo P2 (low=140, ascendente vs P1)
            (145, 150, 142, 148, 10.0),    # idx9
            (148, 155, 150, 152, 10.0),    # idx10 -- P2 confirmado aqui; reta P1->P2 extrapolada=150 no idx11
            (150, 152, 120, 105, 10.0),    # idx11 -- vermelho, close(105) < nivel(150), low(120) > entry
        ])
        ev = _evento(0, bars[0].ts, stop=80.0, topo=200.0)
        r = calcular_r_saida_fiel(bars, ev, PARAMS, COSTS, "desconhecido", None, t_entrada=bars[1].ts,
                                  horizonte_s=50 * STEP, now=bars[1].ts + 50 * STEP)
        self.assertEqual(r.status, "resolvido")
        self.assertTrue(r.tp1_realizado)
        self.assertGreater(r.r_mult, 0.0)   # entry=100, legs em 150 e 105 -- os dois acima da entrada


class MarcadoNoCorteSemLookaheadTests(unittest.TestCase):
    def test_marcado_sem_tp1_nunca_olha_candle_apos_o_corte(self) -> None:
        spec_com = [
            (100, 101, 99, 100, 10.0),
            (100, 102, 98, 101, 10.0),     # idx1 -- entry=100
            (101, 103, 99, 102, 10.0),     # idx2 -- ultimo candle limpo ANTES do corte
            (102, 104, 60, 61, 10.0),      # idx3 -- DEPOIS do corte: bateria o stop, nunca pode contar
        ]
        bars_com = _bars_vol(spec_com)
        bars_sem = _bars_vol(spec_com[:3])
        ev = _evento(0, bars_com[0].ts, stop=80.0, topo=100_000.0)
        t_entrada = bars_com[1].ts
        kwargs = dict(t_entrada=t_entrada, horizonte_s=STEP, now=t_entrada + STEP)
        r_com = calcular_r_saida_fiel(bars_com, ev, PARAMS, COSTS, "desconhecido", None, **kwargs)
        r_sem = calcular_r_saida_fiel(bars_sem, ev, PARAMS, COSTS, "desconhecido", None, **kwargs)
        self.assertEqual(r_com.status, "marcado")
        self.assertFalse(r_com.tp1_realizado)
        self.assertEqual(r_com, r_sem)   # identico com/sem o candle pos-corte -- zero lookahead

    def test_marcado_apos_tp1_sem_fechar_o_resto_nunca_olha_candle_apos_o_corte(self) -> None:
        spec_com = [
            (100, 101, 99, 100, 10.0),
            (100, 102, 96, 101, 10.0),     # idx1 -- entry=100
            (101, 205, 100, 150, 10.0),    # idx2 -- toca topo=200
            (150, 156, 148, 152, 10.0),    # idx3 -- TP1 executa (open=150); ultimo candle ANTES do corte
            (152, 300, 40, 41, 10.0),      # idx4 -- DEPOIS do corte: nunca pode contar
        ]
        bars_com = _bars_vol(spec_com)
        bars_sem = _bars_vol(spec_com[:4])
        ev = _evento(0, bars_com[0].ts, stop=80.0, topo=200.0)
        t_entrada = bars_com[1].ts
        corte = bars_com[3].ts
        kwargs = dict(t_entrada=t_entrada, horizonte_s=corte - t_entrada, now=t_entrada + 50 * STEP)
        r_com = calcular_r_saida_fiel(bars_com, ev, PARAMS, COSTS, "desconhecido", None, **kwargs)
        r_sem = calcular_r_saida_fiel(bars_sem, ev, PARAMS, COSTS, "desconhecido", None, **kwargs)
        self.assertEqual(r_com.status, "marcado")
        self.assertTrue(r_com.tp1_realizado)
        self.assertGreater(r_com.r_mult, 0.0)   # restante marcado no mesmo preco (150) do TP1 -- conservador
        self.assertEqual(r_com, r_sem)


class PreregistroHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="saida_fiel_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1a_chamada_registra_e_as_seguintes_sao_idempotentes(self) -> None:
        h1 = garantir_saida_fiel_registrada(self.storage)
        h2 = garantir_saida_fiel_registrada(self.storage)
        self.assertEqual(h1, h2)
        self.assertEqual(h1, hash_do_preregistro())

    def test_texto_alterado_depois_do_registro_recusa(self) -> None:
        garantir_saida_fiel_registrada(self.storage)
        self.storage.set_meta("saida_fiel_preregistro_hash", "0" * 12)
        with self.assertRaises(PreregistroAlteradoError):
            garantir_saida_fiel_registrada(self.storage)


if __name__ == "__main__":
    unittest.main()
