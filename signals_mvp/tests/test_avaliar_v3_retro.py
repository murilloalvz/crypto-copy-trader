"""PEDIDO 2026-11-03 (Passo 0e, item 4): smoke test do script offline `avaliar_v3_retro.py` --
confirma que roda sem rede/escrita sobre um banco vazio e sobre um banco com pool admitido +
congelamento (lote 1) parcial."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import avaliar_v3_retro as v3retro


class AvaliarV3RetroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="v3retro_"))
        storage = Storage(make_paths(self.tmp))
        self.db_path = storage.paths.db
        storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banco_vazio_nunca_crasha(self) -> None:
        texto = v3retro.executar(self.db_path)
        self.assertIn("avaliar_v3_retro", texto)
        self.assertIn(v3retro.AVISO, texto)
        self.assertNotIn("Traceback", texto)

    def test_pool_admitido_sem_historico_fica_explicito(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute("INSERT INTO pr_pools (pool, symbol, status) VALUES ('POOL1', 'CAT', 'ativo')")
        con.commit()
        con.close()
        texto = v3retro.executar(self.db_path)
        self.assertIn("pools: 1", texto)
        self.assertIn("com historico: 0", texto)

    def test_candidato_do_lote1_fora_do_alcance_offline_quando_nunca_admitido(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS pr_retro_candidatos (pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, "
            "launchpad TEXT, l_bc REAL, grad_ts REAL, criado_ts REAL, mc_found REAL, lista_hash TEXT NOT NULL, "
            "congelado_em REAL NOT NULL, supply REAL, side TEXT)"
        )
        con.execute(
            "INSERT INTO pr_retro_candidatos (pool, mint, symbol, launchpad, lista_hash, congelado_em) "
            "VALUES ('POOLX', 'MINTX', 'CAT', 'pumpfun', 'hash123', 0.0)"
        )
        con.execute("INSERT INTO pr_pools (pool, symbol, status) VALUES ('POOLX', 'CAT', 'rejeitado')")
        con.commit()
        con.close()
        texto = v3retro.executar(self.db_path)
        self.assertIn("fora do alcance offline: 1", texto)
        self.assertIn("candidatos avaliados: 0", texto)

    def test_hash_v3_aparece_no_relatorio_e_e_o_hash_congelado(self) -> None:
        texto = v3retro.executar(self.db_path)
        self.assertIn("56762db29cd6", texto)


if __name__ == "__main__":
    unittest.main()
