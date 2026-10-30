"""PEDIDO 2026-10-27 (H9): Storage.pr_carteiras_snapshot_* -- idempotencia por chave, contagem por
dia/momento, consulta por sinal."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage


class PrCarteirasSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="carteiras_snapshot_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_insert_then_read_back_the_same_row(self) -> None:
        inseriu = self.storage.pr_carteiras_snapshot_insert(
            "entrada:v1:1", 1_000.0, "solana", "POOL1", "MINT1", "entrada",
            [("OwnerA", 2.0), ("OwnerB", 1.0)], n_carteiras_pro=1, n_pessoas_pro=1,
            grupos=["dani"], versao="v1", entry_id=1,
        )
        self.assertTrue(inseriu)
        rows = self.storage.pr_carteiras_snapshot_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chave"], "entrada:v1:1")
        self.assertEqual(rows[0]["n_pessoas_pro"], 1)

    def test_the_same_chave_never_inserts_twice(self) -> None:
        self.storage.pr_carteiras_snapshot_insert(
            "horaria:POOL1:100", 360_000.0, "solana", "POOL1", "MINT1", "horaria",
            [], n_carteiras_pro=0, n_pessoas_pro=0, grupos=[],
        )
        inseriu_de_novo = self.storage.pr_carteiras_snapshot_insert(
            "horaria:POOL1:100", 360_100.0, "solana", "POOL1", "MINT1", "horaria",
            [], n_carteiras_pro=5, n_pessoas_pro=5, grupos=["x"],
        )
        self.assertFalse(inseriu_de_novo)
        self.assertEqual(len(self.storage.pr_carteiras_snapshot_all()), 1)
        self.assertEqual(self.storage.pr_carteiras_snapshot_all()[0]["n_pessoas_pro"], 0, "nunca sobrescreve")

    def test_count_since_filters_by_momento_and_timestamp(self) -> None:
        self.storage.pr_carteiras_snapshot_insert("entrada:v1:1", 100.0, "solana", "P", "M", "entrada",
                                                   [], 0, 0, [])
        self.storage.pr_carteiras_snapshot_insert("horaria:P:0", 100.0, "solana", "P", "M", "horaria",
                                                   [], 0, 0, [])
        self.storage.pr_carteiras_snapshot_insert("horaria:P:1", 200.0, "solana", "P", "M", "horaria",
                                                   [], 0, 0, [])
        self.assertEqual(self.storage.pr_carteiras_snapshot_count_since(0.0, "horaria"), 2)
        self.assertEqual(self.storage.pr_carteiras_snapshot_count_since(150.0, "horaria"), 1)
        self.assertEqual(self.storage.pr_carteiras_snapshot_count_since(0.0), 3)

    def test_para_sinal_filters_by_versao_and_entry_id(self) -> None:
        self.storage.pr_carteiras_snapshot_insert("entrada:v1:1", 100.0, "solana", "P", "M", "entrada",
                                                   [], 1, 1, ["dani"], versao="v1", entry_id=1)
        self.storage.pr_carteiras_snapshot_insert("entrada:v2:1", 100.0, "solana", "P", "M", "entrada",
                                                   [], 2, 2, ["dani", "aloh"], versao="v2", entry_id=1)
        v1_rows = self.storage.pr_carteiras_snapshot_para_sinal("v1", 1)
        self.assertEqual(len(v1_rows), 1)
        self.assertEqual(v1_rows[0]["n_pessoas_pro"], 1)

    def test_existe_checks_presence_by_chave(self) -> None:
        self.assertFalse(self.storage.pr_carteiras_snapshot_existe("entrada:v1:1"))
        self.storage.pr_carteiras_snapshot_insert("entrada:v1:1", 100.0, "solana", "P", "M", "entrada",
                                                   [], 0, 0, [])
        self.assertTrue(self.storage.pr_carteiras_snapshot_existe("entrada:v1:1"))


if __name__ == "__main__":
    unittest.main()
