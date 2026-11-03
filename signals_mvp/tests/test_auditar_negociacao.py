"""PEDIDO 2026-11-03 (continuacao -- rotacao/capacidade): testes de `scripts/auditar_negociacao.py`
-- SOMENTE LEITURA, nenhum limiar/criterio decidido aqui, so medicao."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import auditar_negociacao as auditar


class AuditarNegociacaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_negociacao_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _inserir_pool(self, con: sqlite3.Connection, pool: str, symbol: str, status: str,
                      sem_fase_desde: float | None, info: dict) -> None:
        con.execute(
            "INSERT INTO pr_pools (pool, symbol, status, sem_fase_desde, info) VALUES (?,?,?,?,?)",
            (pool, symbol, status, sem_fase_desde, json.dumps(info)),
        )

    def test_conta_candles_de_volume_zero_nas_ultimas_24h_e_soma_volume_24h_72h(self) -> None:
        now = 1_000_000.0
        con = sqlite3.connect(str(self.db_path))
        self._inserir_pool(con, "POOLANT", "ANT", "ativo", now - 30 * 3600.0, {"criado_ts": now - 10 * 86400.0})
        bars = []
        for h_atras in range(80, -1, -1):   # candles de -80h a 0h (81 candles, cobre 24h e 72h)
            ts = now - h_atras * 3600.0
            if h_atras < 24:
                vol = 0.0 if h_atras % 2 == 0 else 500.0   # ultimas 24h: metade com volume zero
            elif h_atras < 72:
                vol = 100.0   # entre 24h e 72h: volume baixo mas nao-zero
            else:
                vol = 1_000.0   # fora da janela de 72h -- nunca deveria contar em vol_72h
            bars.append((ts, 100.0, 100.0, 100.0, 100.0, vol, 0))
        con.executemany("INSERT INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled) VALUES ('POOLANT','1h',?,?,?,?,?,?,?)", bars)
        con.commit()
        con.close()
        linhas = auditar.medir(self.db_path, now=now)
        self.assertEqual(len(linhas), 1)
        l = linhas[0]
        self.assertEqual(l["symbol"], "ANT")
        self.assertTrue(l["destaque"])   # ANT esta na lista de destaque explicita
        self.assertGreater(l["vol_72h_usd"], l["vol_24h_usd"])
        self.assertGreater(l["n_vol_zero_24h"], 0)
        self.assertAlmostEqual(l["horas_sem_fase"], 30.0, delta=1.0)

    def test_dormente_e_destaque_mesmo_sem_simbolo_ant_chico(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        self._inserir_pool(con, "POOLX", "OUTRO", "dormente", None, {})
        con.commit()
        con.close()
        linhas = auditar.medir(self.db_path, now=1_000_000.0)
        self.assertTrue(linhas[0]["destaque"])
        self.assertIsNone(linhas[0]["horas_sem_fase"])   # sem_fase_desde None (runner/pullback OU nao preenchido)

    def test_pool_rejeitado_nunca_entra_no_relatorio(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        self._inserir_pool(con, "POOLY", "LIXO", "rejeitado", None, {})
        con.commit()
        con.close()
        self.assertEqual(auditar.medir(self.db_path, now=1_000_000.0), [])

    def test_liquidez_ausente_fica_s_d_nunca_zero(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        self._inserir_pool(con, "POOLZ", "ZZZ", "ativo", None, {})
        con.commit()
        con.close()
        linha = auditar.medir(self.db_path, now=1_000_000.0)[0]
        self.assertIsNone(linha["liq_usd"])
        texto = auditar.executar(self.db_path)
        self.assertIn("s/d", texto)

    def test_executar_nunca_crasha_com_banco_vazio(self) -> None:
        texto = auditar.executar(self.db_path)
        self.assertIn("auditar_negociacao", texto)
        self.assertNotIn("Traceback", texto)


if __name__ == "__main__":
    unittest.main()
