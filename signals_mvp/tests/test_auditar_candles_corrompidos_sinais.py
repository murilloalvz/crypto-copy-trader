"""PEDIDO 2026-11-10 (autorizado, Rodada 17, item 1 parte 2): testes de
`scripts/auditar_candles_corrompidos_sinais.py` -- o gap entre o veto simples
(`candle_corrompido_provavel`, ja usado pela varredura/grade) e o veto amplo do caminho ao vivo
(`qualidade_candle.candle_confiavel_cb`), e o smoke end-to-end sobre um banco vazio. EXPLORATORIO --
so confere a mecanica/wiring, nunca testa edge economica."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.detector_v1 import EventV1
from ..scripts import auditar_candles_corrompidos_sinais as acs
from ..scripts import varredura_v3 as vv3
from ..storage import Storage
from .test_exit_lab import _bars_vol


class AuditarSinalTests(unittest.TestCase):
    """Fixture: candle isolado (idx2, high=1050) cujo salto e >10x o CLOSE do vizinho anterior (101)
    mas NAO e >10x o HIGH de nenhum dos dois vizinhos (600 e 103) -- por isso o veto SIMPLES (exige
    high>10x o HIGH de AMBOS os vizinhos) nunca o pega, mas o veto AMPLO (razao contra o close do
    vizinho anterior, sem confirmacao do candle seguinte) pega como `candle_isolado_vs_vizinhos`."""

    def _sinal(self) -> vv3.SinalVarredura:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),   # idx0 -- candle do evento (ev.idx=0)
            (100, 150, 96, 101, 10.0),   # idx1 -- entry=100 (open); high baixo o bastante pra nunca
                                         # tocar os alvos sozinho, mas alto o bastante (>=105) pra que
                                         # o veto SIMPLES do idx2 (precisa >10x o HIGH de AMBOS os
                                         # vizinhos) nunca dispare so por este lado.
            (101, 1050, 70, 90, 10.0),   # idx2 -- spike isolado: low=70<=stop(80)
            (100, 103, 98, 101, 10.0),   # idx3 -- nao confirma o nivel do spike
        ])
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"stop": 80.0, "TOPO": 10_000.0, "S": 50.0})
        s = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", "MINT1", "POOL1", "1h",
                              None, None)
        self.assertIsNotNone(s)
        return s

    def test_candle_isolado_entra_no_gap_mas_nunca_no_veto_simples(self) -> None:
        linha = acs.auditar_sinal(self._sinal(), "ao_vivo")
        self.assertEqual(linha.n_corrompidos_simples["72h"], 0)
        self.assertEqual(linha.n_corrompidos_pleno["72h"], 1)
        self.assertEqual(linha.n_corrompidos_simples["7d"], 0)
        self.assertEqual(linha.n_corrompidos_pleno["7d"], 1)
        # mesmo candle conta nas duas janelas (72h esta contida em 7d) -- 1 entrada de gap por horizonte.
        self.assertEqual(len(linha.gap_candles), 2)
        motivos = {m for _h, _ts, m in linha.gap_candles}
        self.assertEqual(motivos, {"candle_isolado_vs_vizinhos"})
        self.assertTrue(linha.exposto_grade)

    def test_toques_divergem_simples_bate_o_stop_no_spike_amplo_fica_sem_decisao(self) -> None:
        linha = acs.auditar_sinal(self._sinal(), "ao_vivo")
        self.assertEqual(len(linha.toques_divergentes), len(acs.ALVOS_TOQUE))
        for alvo, atual, pleno in linha.toques_divergentes:
            self.assertIn(alvo, acs.ALVOS_TOQUE)
            self.assertEqual(atual, "stop")
            self.assertIsNone(pleno)

    def test_to_dict_reporta_contagens_motivo_e_exposicao(self) -> None:
        linha = acs.auditar_sinal(self._sinal(), "ao_vivo")
        d = linha.to_dict()
        self.assertEqual(d["origem"], "ao_vivo")
        self.assertEqual(d["mint"], "MINT1")
        self.assertEqual(d["n_corrompidos_simples_72h"], 0)
        self.assertEqual(d["n_corrompidos_pleno_72h"], 1)
        self.assertIn("candle_isolado_vs_vizinhos", d["gap_candles_ts"])
        self.assertTrue(d["exposto_grade_24_variantes"])


class ToqueCausalVetoPlenoTests(unittest.TestCase):
    def test_sem_corrupcao_no_caminho_devolve_o_mesmo_toque_que_o_veto_simples(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),
            (100, 102, 96, 101, 10.0),    # entry=100
            (101, 205, 100, 150, 10.0),   # toca alvo (preco_alvo=200 pra alvo_r=5) sem nenhuma corrupcao
        ])
        atual = vv3._toque_causal(bars, 1, entry_price=100.0, stop=80.0, alvo_r=5.0)
        pleno = acs._toque_causal_veto_pleno(bars, 1, entry_price=100.0, stop=80.0, alvo_r=5.0,
                                             peak=10_000.0)
        self.assertEqual(atual, "alvo")
        self.assertEqual(atual, pleno)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="acs_smoke_"))
        self.storage = Storage(make_paths(self.tmp))
        self.db_path = self.storage.paths.db
        self.storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = acs.executar(self.db_path, progresso=False)
        self.assertIn(acs.AVISO, texto)
        self.assertIn("sinais auditados: 0", texto)
        self.assertNotIn("Traceback", texto)


if __name__ == "__main__":
    unittest.main()
