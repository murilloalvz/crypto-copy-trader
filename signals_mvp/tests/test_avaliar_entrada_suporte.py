"""PEDIDO 2026-11-12 (autorizado, rodada 18, item 3): testes de `scripts/avaliar_entrada_suporte.py`
-- `avaliar_sinal` (monta o sinal sintetico na 1a revisita, aplica a MESMA saida A, roda os
comparadores (a)/(b)/(c)), `agregar_origem_suporte` (pareamento por token) e o smoke end-to-end sobre
um banco vazio (zero sinais nas 3 origens, zero crash, hash registrado). EXPLORATORIO -- so confere a
mecanica/wiring, nunca testa edge economica."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.horizonte_fixo import HORIZONTES_S
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage
from ..scripts import avaliar_entrada_suporte as aes
from ..scripts import varredura_v3 as vv3
from .test_entrada_suporte import CREATED, L_BC, _bars_com_2_revisitas

PARAMS = load_params_v3()
COSTS = CostModel()


def _sinal_elegivel() -> vv3.SinalVarredura:
    bars = _bars_com_2_revisitas()
    det = DetectorV1(PARAMS, "1h", L_BC, None, CREATED)
    eventos = []
    for b in bars:
        eventos.extend(det.update(b))
    ev_entrada = next(e for e in eventos if e.kind == "ENTRADA")
    s = vv3._montar_sinal(bars, ev_entrada, "desconhecido", L_BC, "ao_vivo", "CAT", "MINT1", "POOL1",
                          "1h", CREATED, None)
    assert s is not None
    return s


class AvaliarSinalTests(unittest.TestCase):
    def test_sinal_com_revisita_e_elegivel_e_calcula_os_4_numeros(self) -> None:
        s = _sinal_elegivel()
        now = s.t_entrada + 73 * 3600
        r = aes.avaliar_sinal(s, PARAMS, COSTS, HORIZONTES_S["72h"], now, veto="simples")
        self.assertTrue(r.elegivel)
        self.assertIsNotNone(r.r_suporte)
        self.assertIsNotNone(r.r_v3)
        self.assertIsNotNone(r.risco_pct)
        self.assertGreater(r.risco_pct, 0.0)
        self.assertIn(2.0, r.toques)
        self.assertIn(5.0, r.toques)

    def test_sem_zona_nos_dados_do_evento_e_nao_elegivel(self) -> None:
        s = _sinal_elegivel()
        ev_sem_zona = s.ev.__class__(kind=s.ev.kind, idx=s.ev.idx, ts=s.ev.ts,
                                     decision_ts=s.ev.decision_ts,
                                     data={k: v for k, v in s.ev.data.items() if k != "zona"})
        s_sem_zona = s.__class__(**{**s.__dict__, "ev": ev_sem_zona})
        now = s.t_entrada + 73 * 3600
        r = aes.avaliar_sinal(s_sem_zona, PARAMS, COSTS, HORIZONTES_S["72h"], now, veto="simples")
        self.assertFalse(r.elegivel)


class AgregarOrigemSuporteTests(unittest.TestCase):
    def test_1_sinal_elegivel_conta_1_token_e_preenche_pareamentos(self) -> None:
        s = _sinal_elegivel()
        now = s.t_entrada + 73 * 3600
        r = aes.agregar_origem_suporte([s], "x", "72h", now, veto="simples")
        self.assertEqual(r.n_sinais, 1)
        self.assertEqual(r.n_elegiveis, 1)
        self.assertEqual(r.n_tokens_elegiveis, 1)
        self.assertEqual(r.suporte.n, 1)
        self.assertIsNotNone(r.risco_pct_medio)

    def test_lista_vazia_devolve_zeros_sem_crashar(self) -> None:
        r = aes.agregar_origem_suporte([], "x", "72h", 0.0, veto="simples")
        self.assertEqual(r.n_sinais, 0)
        self.assertEqual(r.n_elegiveis, 0)
        self.assertEqual(r.suporte.n, 0)
        self.assertIsNone(r.poder_mde_vs_v3)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="aes_smoke_"))
        self.storage = Storage(make_paths(self.tmp))
        self.db_path = self.storage.paths.db
        self.storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha_e_registra_o_hash(self) -> None:
        texto = aes.executar(self.db_path, progresso=False)
        self.assertIn(aes.AVISO, texto)
        self.assertIn("## ao_vivo", texto)
        self.assertIn("## retro_lote1", texto)
        self.assertIn("## replay_v3", texto)
        self.assertIn("nenhum sinal elegivel", texto)
        self.assertNotIn("Traceback", texto)
