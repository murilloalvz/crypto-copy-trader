"""PEDIDO 2026-11-12 (autorizado, rodada 19, item 1): testes da sombra FORWARD "entrada no suporte"
ao vivo (`pos_runner/live.py: _sombra_suporte_v3`, gravando em `pr3_suporte_sombra`/
`pr3_suporte_sombra_saida`). PAPER/READ-ONLY -- nunca altera sinais/alertas/H1/criterio de sinal; so
o que o item 1 pediu. EXPLORATORIO -- so confere a mecanica/wiring (gravacao na 1a revisita,
idempotencia, acompanhamento por horizonte), nunca testa edge economica."""

from __future__ import annotations

import json
import unittest

from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.params_v3 import load_params_v3
from .test_entrada_suporte import CREATED, L_BC, T0, _bars_com_2_revisitas
from .test_pos_runner_live import LiveHarness
from .test_pos_runner_v3_live import _row

PARAMS = load_params_v3()


def _det_ate(idx_exclusivo: int) -> DetectorV1:
    """Reexecuta `DetectorV1` (MESMOS `ParamsV3`) sobre `_bars_com_2_revisitas()`, parando ANTES do
    candle `idx_exclusivo` (nunca processa esse candle) -- deixa o estado exatamente como estaria ao
    vivo naquele ponto."""
    bars = _bars_com_2_revisitas()
    det = DetectorV1(PARAMS, "1h", L_BC, None, CREATED)
    for b in bars[:idx_exclusivo]:
        det.update(b)
    return det


class SombraSuporteV3GravacaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_grava_na_1a_revisita_apos_caixa_formada_e_antes_do_gatilho(self) -> None:
        # idx20 e o gatilho real (ENTRADA) -- processa so 0..20 (21 candles, inclui o candle de
        # entrada j0=20 pra abrir a posicao hipotetica, mas o candle 20 TAMBEM e o gatilho oficial;
        # ambos cabem na mesma reexecucao, sem conflito -- ver docstring de `localizar_revisitas_suporte`.
        det = _det_ate(21)
        row = _row()
        self.h.live._sombra_suporte_v3(row, "1h", det, now=det.bars[20].ts + 1.0)
        suporte = self.h.storage.pr3_suporte_sombra_get("POOL1", "1h", zona=1)
        self.assertIsNotNone(suporte)
        self.assertEqual(suporte["ts_revisita"], det.bars[19].ts)
        self.assertEqual(suporte["t_entrada"], det.bars[20].ts)
        self.assertAlmostEqual(suporte["entry_price"], det.bars[20].open)
        self.assertAlmostEqual(suporte["stop"], 150_000.0 * (1.0 - PARAMS.stop_below_wick_pct))
        self.assertAlmostEqual(suporte["s_suporte"], 150_000.0)
        self.assertAlmostEqual(suporte["topo"], 1_000_000.0)
        self.assertGreater(suporte["risco_pct"], 0.0)

    def test_sem_candle_seguinte_ainda_nao_grava_nada(self) -> None:
        # So 0..19 (20 candles) -- a revisita (idx19) existe, mas o candle de ABERTURA da entrada
        # (idx20) ainda nao chegou -- causal, nunca inventa uma entrada sem o candle seguinte.
        det = _det_ate(20)
        row = _row()
        self.h.live._sombra_suporte_v3(row, "1h", det, now=det.bars[19].ts + 1.0)
        self.assertIsNone(self.h.storage.pr3_suporte_sombra_get("POOL1", "1h", zona=1))

    def test_segunda_chamada_e_idempotente_nunca_duplica(self) -> None:
        det = _det_ate(21)
        row = _row()
        self.h.live._sombra_suporte_v3(row, "1h", det, now=det.bars[20].ts + 1.0)
        self.h.live._sombra_suporte_v3(row, "1h", det, now=det.bars[20].ts + 2.0)
        linhas = self.h.storage.pr3_suporte_sombra_all(pool="POOL1", tf="1h")
        self.assertEqual(len(linhas), 1)

    def test_sem_suporte_sombra_nunca_grava(self) -> None:
        h2 = LiveHarness(sem_suporte_sombra=True)
        try:
            det = _det_ate(21)
            row = _row()
            h2.live._sombra_suporte_v3(row, "1h", det, now=det.bars[20].ts + 1.0)
            self.assertEqual(h2.storage.pr3_suporte_sombra_all(pool="POOL1", tf="1h"), [])
        finally:
            h2.close()


class SombraSuporteV3AcompanhamentoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_acompanha_72h_e_7d_e_grava_toque_e_controles(self) -> None:
        det = _det_ate(21)
        row = _row()
        t_entrada = det.bars[20].ts
        now = t_entrada + 73 * 3600.0
        self.h.live._sombra_suporte_v3(row, "1h", det, now=now)
        suporte = self.h.storage.pr3_suporte_sombra_get("POOL1", "1h", zona=1)
        self.assertIsNotNone(suporte)
        saida_72h = self.h.storage.pr3_suporte_sombra_saida_get(suporte["id"], "72h")
        self.assertIsNotNone(saida_72h)
        self.assertEqual(saida_72h["status"], "marcado")
        self.assertIsNotNone(saida_72h["r_mult"])
        self.assertIn(saida_72h["toque_2r"], (None, "alvo", "stop"))
        self.assertIsInstance(json.loads(saida_72h["controles_json"]), list)
        saida_7d = self.h.storage.pr3_suporte_sombra_saida_get(suporte["id"], "7d")
        self.assertIsNotNone(saida_7d)
        self.assertEqual(saida_7d["status"], "pendente")
        self.assertIsNone(saida_7d["r_mult"])

    def test_recomputa_todo_ciclo_idempotente_nunca_crasha(self) -> None:
        det = _det_ate(21)
        row = _row()
        t_entrada = det.bars[20].ts
        self.h.live._sombra_suporte_v3(row, "1h", det, now=t_entrada + 1.0)
        self.h.live._sombra_suporte_v3(row, "1h", det, now=t_entrada + 73 * 3600.0)
        suporte = self.h.storage.pr3_suporte_sombra_get("POOL1", "1h", zona=1)
        saidas = self.h.storage.pr3_suporte_sombra_saida_all(suporte["id"])
        self.assertEqual(len(saidas), 2)   # 72h + 7d, nunca duplicado


if __name__ == "__main__":
    unittest.main()
