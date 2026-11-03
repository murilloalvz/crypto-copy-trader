"""PEDIDO 2026-10-27 (H8): scripts/carregar_carteiras_pro.py -- CLI que valida/registra a lista real
contra um banco temporario (o CSV de grupos e um efeito colateral sobre o arquivo real do repositorio
-- ja coberto por test_carteiras_pro.py; aqui so a integracao do script/CLI com `Storage`)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..pos_runner import carteiras_pro as cp
from ..scripts.carregar_carteiras_pro import executar


class CarregarCarteirasProScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="carteiras_script_"))
        self.db_path = self.tmp / "dados" / "estado.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reports_counts_and_groups_for_the_real_list(self) -> None:
        saida = executar(self.db_path)
        self.assertIn("n_carteiras_pro: 121", saida)
        self.assertIn("n_pessoas_pro: 79", saida)
        self.assertIn("aloh: 7", saida)
        self.assertIn("dani: 6", saida)
        self.assertNotIn("⚠️", saida, "121 e o esperado -- nunca deveria disparar o aviso de diferenca")

    def test_second_run_against_the_same_db_is_idempotent(self) -> None:
        primeira = executar(self.db_path)
        segunda = executar(self.db_path)
        self.assertEqual(primeira, segunda)


if __name__ == "__main__":
    unittest.main()
