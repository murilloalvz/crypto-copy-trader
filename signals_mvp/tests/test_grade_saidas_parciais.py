"""PEDIDO 2026-11-10 (autorizado, rodada 13): testes de `scripts/grade_saidas_parciais.py` -- a
decomposicao/estatisticas de UMA variante sobre uma lista pequena de sinais (reusando `vv3.
_montar_sinal`), o leave-one-token-out, e o smoke end-to-end sobre um banco vazio (zero sinais nas 3
origens, zero crash, hash registrado). EXPLORATORIO -- so confere a mecanica/wiring."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.saidas_parciais import REMAINDER_SEGURAR, TRIGGER_1R, VarianteSaidaParcial
from ..storage import Storage
from ..scripts import grade_saidas_parciais as gsp
from ..scripts import varredura_v3 as vv3
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.costs import CostModel

STEP = 3_600


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v, filled=False)


class LeaveOneTokenOutTests(unittest.TestCase):
    def test_pior_caso_remove_o_token_que_mais_puxa_a_media_pra_cima(self) -> None:
        valores = {"CAT": [10.0], "DOG": [-1.0], "FOX": [-1.0]}
        # removendo CAT (o unico positivo): media de DOG+FOX = -1.0 -- pior caso.
        self.assertAlmostEqual(gsp._leave_one_token_out_pior_caso(valores), -1.0)

    def test_menos_de_2_tokens_devolve_none(self) -> None:
        self.assertIsNone(gsp._leave_one_token_out_pior_caso({"CAT": [1.0]}))
        self.assertIsNone(gsp._leave_one_token_out_pior_caso({}))


class CalcularVarianteSobreSinaisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params = load_params_v3()
        self.costs = CostModel()

    def _sinal(self, bars: list[Bar], stop: float, created_ts: float = -1000.0) -> vv3.SinalVarredura:
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"stop": stop, "TOPO": 10_000.0, "R": 0.0, "S": 0.0})
        s = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", "MINT1", "POOL1", "1h",
                              created_ts, None)
        self.assertIsNotNone(s)
        return s

    def test_decomposicao_tp1_e_sem_tp1_corretas(self) -> None:
        bars_tp1 = [
            _bar(0, 100, 101, 99, 100), _bar(STEP, 100, 102, 96, 101),      # entry=100
            _bar(2 * STEP, 101, 125, 99, 120),                              # toca +1R(120)
            _bar(3 * STEP, 120, 121, 119, 120),                             # TP1 executa open=120
            _bar(4 * STEP, 120, 121, 85, 90),                               # low=85 > stop(80)
        ]
        s_tp1 = self._sinal(bars_tp1, stop=80.0)
        bars_stop = [
            _bar(0, 100, 101, 99, 100), _bar(STEP, 100, 102, 96, 101),
            _bar(2 * STEP, 101, 102, 70, 75),                               # nunca viu TP1
        ]
        s_stop = self._sinal(bars_stop, stop=80.0)
        s_stop = s_stop.__class__(**{**s_stop.__dict__, "token": "DOG"})
        now = s_tp1.t_entrada + 73 * STEP
        variante = VarianteSaidaParcial(TRIGGER_1R, 0.30, REMAINDER_SEGURAR)
        r = gsp._calcular_variante_sobre_sinais([s_tp1, s_stop], variante, 72.0 * 3600.0, now,
                                                self.params, self.costs)
        self.assertEqual(r.decomposicao.n_vencido, 2)
        self.assertEqual(r.decomposicao.n_tp1, 1)
        self.assertAlmostEqual(r.decomposicao.p_tp1_pct, 50.0)
        self.assertIsNotNone(r.decomposicao.r_leg1_medio)
        self.assertIsNotNone(r.decomposicao.r_medio_sem_tp1)
        self.assertLess(r.decomposicao.r_medio_sem_tp1, 0.0)
        self.assertEqual(r.saida.n, 2)
        # sensibilidade: custo 3x nunca melhora a media.
        self.assertGreaterEqual(r.saida.media, r.saida_slip3x.media)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gsp_smoke_"))
        self.storage = Storage(make_paths(self.tmp))
        self.db_path = self.storage.paths.db
        self.storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha_e_registra_o_hash(self) -> None:
        texto = gsp.executar(self.db_path, progresso=False)
        self.assertIn(gsp.AVISO, texto)
        self.assertIn("## ao_vivo", texto)
        self.assertIn("## retro_lote1", texto)
        self.assertIn("## replay_v3", texto)
        self.assertIn("sem sinais nesta origem", texto)
        self.assertNotIn("Traceback", texto)
        storage = Storage(make_paths(self.tmp))
        try:
            self.assertIsNotNone(storage.get_meta("saidas_parciais_preregistro_hash"))
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
