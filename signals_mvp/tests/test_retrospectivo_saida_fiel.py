"""PEDIDO 2026-11-06 (autorizado, rodada 12, Parte 2): testes de `scripts/retrospectivo_saida_fiel.py`
-- loader `ao_vivo` novo (monta `SinalVarredura`, nunca `SinalAuditoria`), a classificacao em
pendente/sem_dado/horizonte vencido (com fracao de TP1), e o smoke end-to-end sobre um banco vazio
(zero sinais nas 3 origens, zero crash). EXPLORATORIO -- so confere a mecanica/wiring, nunca testa
edge economica."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from ..config import make_paths
from ..pos_runner.candles import Bar
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.params_v1 import load_params_v1
from ..storage import Storage
from ..scripts import retrospectivo_saida_fiel as rsf
from ..scripts import varredura_v3 as vv3
from .test_pos_runner_v1 import L_BC

STEP = 3_600
PARAMS = load_params_v1()
COSTS = CostModel()


def _bar(ts: float, o: float, h: float, l: float, c: float, v: float = 10.0) -> Bar:
    return Bar(ts=int(ts), open=o, high=h, low=l, close=c, volume=v, filled=False)


class CarregarAoVivoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rsf_aovivo_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_carrega_sinal_persistido_como_sinalvarredura(self) -> None:
        signal_id = self.storage.pr3_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v3": "abc123", "gatilho": json.dumps(["reacao_suporte"]), "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "aberto", "entry_price": 100.0,
            "stop": 90.0, "topo": 200.0, "s_suporte": 80.0, "r_resistencia": 95.0, "n_pavios": 2,
            "caixa_candles": 5, "caixa_horas": 5.0, "idade_dias": 3.0,
        })
        self.storage.pr_trajetoria_upsert("v3", signal_id, 0.0, chain="solana", pool="POOL1", tf="1h",
                                          mint="MINT1", symbol="CAT", t_entrada=3600.0, preco_entrada=100.0,
                                          risco_pct=10.0, r_unidade=10.0, fonte_candle="gt")
        bars = [_bar(i * 3600, 100, 101, 99, 100) for i in range(10)]
        self.storage.pr_append_bars("POOL1", "1h", [(b.ts, b.open, b.high, b.low, b.close, b.volume,
                                                     int(b.filled)) for b in bars])
        self.storage.pr_upsert_pool("POOL1", status="ativo", l_bc=L_BC,
                                    info=json.dumps({"criado_ts": -10_000.0}))
        sinais = rsf.carregar_ao_vivo(self.storage.paths.db)
        self.assertEqual(len(sinais), 1)
        s = sinais[0]
        self.assertEqual(s.origem, "ao_vivo")
        self.assertEqual(s.token, "CAT")
        self.assertEqual(s.pool, "POOL1")
        self.assertEqual(s.topo, 200.0)
        self.assertEqual(s.stop, 90.0)
        self.assertEqual(s.t_entrada, 3600.0)
        self.assertEqual(s.created_ts, -10_000.0)
        self.assertEqual(s.ev.data["TOPO"], 200.0)

    def test_sem_sinal_persistido_devolve_lista_vazia(self) -> None:
        self.assertEqual(rsf.carregar_ao_vivo(self.storage.paths.db), [])


class AgregarHorizonteTests(unittest.TestCase):
    def _sinal(self, bars: list[Bar], stop: float, topo: float) -> vv3.SinalVarredura:
        ev = EventV1(kind="ENTRADA", idx=0, ts=bars[0].ts, decision_ts=bars[0].ts,
                    data={"stop": stop, "TOPO": topo, "S": 0.0})
        s = vv3._montar_sinal(bars, ev, "desconhecido", None, "ao_vivo", "CAT", "MINT1", "POOL1", "1h",
                              None, None)
        self.assertIsNotNone(s)
        return s

    def test_resolvido_pelo_stop_conta_como_vencido_sem_tp1(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(STEP, 100, 102, 96, 101),      # entry=100
            _bar(2 * STEP, 101, 102, 70, 75),   # low=70 <= stop(80) -- fecha aqui, nunca viu TP1
            _bar(3 * STEP, 75, 80, 74, 78),
        ]
        s = self._sinal(bars, stop=80.0, topo=10_000.0)
        now = s.t_entrada + 73 * 3600   # passou das 72h (HORIZONTES_S["72h"])
        r = rsf.agregar_horizonte([s], "72h", now, PARAMS, COSTS)
        self.assertEqual(r.n_pendente, 0)
        self.assertEqual(r.n_sem_dado, 0)
        self.assertEqual(r.n_vencido, 1)
        self.assertEqual(r.n_tp1, 0)
        self.assertAlmostEqual(r.fracao_tp1_pct, 0.0)
        self.assertEqual(r.saida_fiel.n, 1)
        self.assertLess(r.saida_fiel.media, 0.0)

    def test_horizonte_nao_decorrido_conta_como_pendente(self) -> None:
        bars = [_bar(0, 100, 101, 99, 100), _bar(STEP, 100, 102, 96, 101)]
        s = self._sinal(bars, stop=80.0, topo=10_000.0)
        now = s.t_entrada + 1.0   # mal comecou -- 72h/7d nunca decorreram
        r = rsf.agregar_horizonte([s], "72h", now, PARAMS, COSTS)
        self.assertEqual(r.n_pendente, 1)
        self.assertEqual(r.n_vencido, 0)
        self.assertEqual(r.saida_fiel.n, 0)
        self.assertIsNone(r.fracao_tp1_pct)

    def test_tp1_via_topo_anterior_conta_na_fracao(self) -> None:
        bars = [
            _bar(0, 100, 101, 99, 100),
            _bar(STEP, 100, 102, 96, 101),       # entry=100
            _bar(2 * STEP, 101, 205, 100, 150),  # toca topo=200
            _bar(3 * STEP, 150, 156, 148, 152),  # TP1 executa (open=150)
            _bar(4 * STEP, 152, 153, 95, 97),    # breakeven
        ]
        s = self._sinal(bars, stop=80.0, topo=200.0)
        now = s.t_entrada + 73 * 3600   # passou das 72h (HORIZONTES_S["72h"])
        r = rsf.agregar_horizonte([s], "72h", now, PARAMS, COSTS)
        self.assertEqual(r.n_vencido, 1)
        self.assertEqual(r.n_tp1, 1)
        self.assertAlmostEqual(r.fracao_tp1_pct, 100.0)
        # sem created_ts -- nenhum controle/aleatorio elegivel, nunca inventa dado.
        self.assertEqual(r.controles_saida_fiel.n, 0)
        self.assertEqual(r.aleatorio_saida_fiel.n, 0)


class ExecutarSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rsf_smoke_"))
        self.storage = Storage(make_paths(self.tmp))
        self.db_path = self.storage.paths.db
        self.storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha_e_registra_o_hash(self) -> None:
        texto = rsf.executar(self.db_path, progresso=False)
        self.assertIn(rsf.AVISO, texto)
        self.assertIn("## ao_vivo", texto)
        self.assertIn("## retro_lote1", texto)
        self.assertIn("## replay_v3", texto)
        self.assertIn("sem sinais nesta origem", texto)
        self.assertNotIn("Traceback", texto)
        storage = Storage(make_paths(self.tmp))
        try:
            self.assertIsNotNone(storage.get_meta("saida_fiel_preregistro_hash"))
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
