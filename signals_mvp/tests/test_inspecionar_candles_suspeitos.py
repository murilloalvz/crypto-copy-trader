"""PEDIDO 2026-11-12 (autorizado, Rodada 18, item 1): testes de
`scripts/inspecionar_candles_suspeitos.py` -- o veredito plausivel/artefato por toque, a janela de
candles impressa em torno do candle decisivo, o filtro `--tokens`, e o smoke end-to-end sobre um
banco vazio. EXPLORATORIO -- so confere a mecanica/wiring, nunca testa edge economica."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.detector_v1 import EventV1
from ..scripts import inspecionar_candles_suspeitos as ics
from ..scripts import varredura_v3 as vv3
from ..storage import Storage
from .test_exit_lab import _bars_vol


class VereditoTests(unittest.TestCase):
    def test_sem_motivo_e_volume_positivo_e_plausivel(self) -> None:
        bar = _bars_vol([(100, 101, 99, 100, 10.0)])[0]
        self.assertIn("PLAUSIVEL", ics._veredito(bar, None))

    def test_motivo_presente_e_artefato(self) -> None:
        bar = _bars_vol([(100, 101, 99, 100, 10.0)])[0]
        self.assertIn("PROVAVEL ARTEFATO", ics._veredito(bar, "candle_isolado_vs_vizinhos"))
        self.assertIn("candle_isolado_vs_vizinhos", ics._veredito(bar, "candle_isolado_vs_vizinhos"))

    def test_volume_zero_sem_motivo_ainda_e_artefato(self) -> None:
        bar = _bars_vol([(100, 101, 99, 100, 0.0)])[0]
        self.assertIn("PROVAVEL ARTEFATO", ics._veredito(bar, None))
        self.assertIn("volume=0", ics._veredito(bar, None))


class ToqueDecisivoTests(unittest.TestCase):
    def test_devolve_status_e_indice_do_candle_que_decidiu(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),
            (101, 205, 100, 150, 10.0),
        ])
        resultado = ics._toque_decisivo(bars, 1, entry_price=100.0, stop=80.0, alvo_r=5.0,
                                        vetado_fn=lambda idx: False)
        self.assertEqual(resultado, ("alvo", 2))

    def test_candle_vetado_e_pulado_mesmo_decidindo_no_veto_simples(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 102, 96, 101, 10.0),
            (101, 102, 70, 75, 10.0),   # bateria o stop aqui, mas esta vetado -- pula
        ])
        # idx=2 esta na lista de vetados e e o UNICO candle que bateria o stop -- sem mais candles
        # depois dele, a funcao nunca decide (prova que o veto realmente pulou, nunca decidiu nele).
        resultado = ics._toque_decisivo(bars, 1, entry_price=100.0, stop=80.0, alvo_r=5.0,
                                        vetado_fn=lambda idx: idx == 2)
        self.assertIsNone(resultado)


class InspecionarSinalTests(unittest.TestCase):
    def _sinal(self) -> vv3.SinalVarredura:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0),    # idx0
            (100, 150, 96, 101, 10.0),    # idx1 -- entry=100
            (101, 1050, 70, 90, 10.0),    # idx2 -- spike isolado
            (100, 103, 98, 101, 10.0),    # idx3 -- nao confirma
        ])
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"stop": 80.0, "TOPO": 10_000.0, "S": 0.0})
        s = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", "MINT1", "POOL1", "1h",
                              None, None)
        self.assertIsNotNone(s)
        return s

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ics_sinal_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relatorio_marca_o_candle_isolado_como_artefato_nos_5_toques(self) -> None:
        sinal = self._sinal()
        out = ics.inspecionar_sinal(sinal, "ao_vivo", self.storage)
        texto = "\n".join(out)
        self.assertEqual(texto.count("PROVAVEL ARTEFATO (veto amplo: candle_isolado_vs_vizinhos)"), 5)
        self.assertIn("### candles no GAP", texto)
        self.assertIn("idx=2 ts=8200.0", texto)

    def test_divergencia_dexpaprika_aparece_na_janela_quando_existe(self) -> None:
        sinal = self._sinal()
        self.storage.pr1_dexpaprika_divergencia_insert(
            0.0, "solana", "POOL1", "MINT1", "CAT", "1h", candle_ts=8200, campo="high",
            valor_gt=1050.0, valor_dexpaprika=120.0, diff_pct=775.0, versao_config_v1=None)
        out = ics.inspecionar_sinal(sinal, "ao_vivo", self.storage)
        texto = "\n".join(out)
        self.assertIn("high:GT=1050 DexPaprika=120 diff=775.0%", texto)
        self.assertNotIn("sem dado DexPaprika", texto.split("idx=2 ts=8200")[1].split("\n")[0])


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ics_smoke_"))
        self.storage = Storage(make_paths(self.tmp))
        self.db_path = self.storage.paths.db

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = ics.executar(self.db_path, progresso=False)
        self.assertIn(ics.AVISO, texto)
        self.assertIn("nenhum sinal exposto", texto)
        self.assertNotIn("Traceback", texto)

    def _semear_sinal_exposto(self) -> None:
        bars = _bars_vol([
            (100, 101, 99, 100, 10.0), (100, 150, 96, 101, 10.0),
            (101, 1050, 70, 90, 10.0), (100, 103, 98, 101, 10.0),
        ])
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": json.dumps(["reacao_suporte"]), "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0,
            "stop": 80.0, "topo": 10_000.0, "s_suporte": 0.0, "r_resistencia": 95.0, "n_pavios": 2,
            "caixa_candles": 5, "caixa_horas": 5.0, "idade_dias": 3.0,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=bars[1].ts,
                                          preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
                                          fonte_candle="gt")
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        self.storage.pr_upsert_pool("POOL1", status="ativo", l_bc=50_000.0,
                                    info=json.dumps({"criado_ts": -10_000.0}))

    def test_sinal_exposto_e_inspecionado_por_padrao(self) -> None:
        self._semear_sinal_exposto()
        self.storage.close()
        texto = ics.executar(self.db_path, progresso=False)
        self.storage = Storage(make_paths(self.tmp))   # reabre pro tearDown fechar sem erro
        self.assertIn("1 sinal(is) inspecionado(s)", texto)
        self.assertIn("## ao_vivo -- CAT", texto)

    def test_filtro_tokens_restringe_a_lista(self) -> None:
        self._semear_sinal_exposto()
        self.storage.close()
        texto_fora = ics.executar(self.db_path, tokens=["OUTRO"], progresso=False)
        texto_dentro = ics.executar(self.db_path, tokens=["CAT"], progresso=False)
        self.storage = Storage(make_paths(self.tmp))
        self.assertIn("nenhum sinal exposto", texto_fora)
        self.assertIn("## ao_vivo -- CAT", texto_dentro)


if __name__ == "__main__":
    unittest.main()
