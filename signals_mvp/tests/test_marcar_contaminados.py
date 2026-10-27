"""PEDIDO 2026-10-27 (item 2, pos-auditoria McRib/yagi): `scripts/marcar_contaminados.py` -- marcacao
RETROATIVA e EXPLICITA (tag `contaminado_candle`), idempotente, com backup antes de qualquer escrita.
Nunca apaga/reescreve outros campos do sinal."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts.marcar_contaminados import marcar
from ..storage import Storage


class MarcarContaminadosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="marcar_"))
        self.paths = make_paths(self.tmp)
        storage = Storage(self.paths)
        try:
            self.signal_id_v1 = storage.pr1_insert_signal({
                "chain": "solana", "pool": "POOLX", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
                "mint": "MINTX", "symbol": "McRib", "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
                "hora_brt": "10:05", "status": "fechado", "entry_price": 440_500.0, "stop": 440_000.0,
                "result_net": 0.12, "reason": "stop",
            })
            self.signal_id_v2 = storage.pr2_insert_signal({
                "chain": "solana", "pool": "POOLY", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 2_000,
                "mint": "MINTY", "symbol": "ヤギ", "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v2": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
                "hora_brt": "12:07", "status": "fechado", "entry_price": 220_000.0, "stop": 200_000.0,
                "result_net": -0.05, "reason": "exit_full", "so_v2": 0,
            })
        finally:
            storage.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_marks_each_listed_trade_and_backs_up_first(self) -> None:
        linhas = marcar(self.paths.db, [("v1", self.signal_id_v1), ("v2", self.signal_id_v2)])
        self.assertTrue(any(l.startswith("backup:") for l in linhas))
        backup_path = Path(next(l for l in linhas if l.startswith("backup:")).split("backup: ", 1)[1])
        self.assertTrue(backup_path.exists(), "backup precisa existir ANTES de qualquer escrita")

        storage = Storage(self.paths)
        try:
            v1 = storage.pr1_signal(self.signal_id_v1)
            v2 = storage.pr2_signal(self.signal_id_v2)
            self.assertIn("contaminado_candle", json.loads(v1["tags"] or "[]"))
            self.assertIn("contaminado_candle", json.loads(v2["tags"] or "[]"))
            # nenhum outro campo foi tocado
            self.assertEqual(v1["status"], "fechado")
            self.assertAlmostEqual(v1["result_net"], 0.12)
            self.assertAlmostEqual(v1["entry_price"], 440_500.0)
        finally:
            storage.close()

    def test_marking_the_same_trade_twice_is_idempotent(self) -> None:
        marcar(self.paths.db, [("v1", self.signal_id_v1)])
        linhas = marcar(self.paths.db, [("v1", self.signal_id_v1)])
        self.assertIn("ja estava marcado", "\n".join(linhas))
        storage = Storage(self.paths)
        try:
            tags = json.loads(storage.pr1_signal(self.signal_id_v1)["tags"] or "[]")
            self.assertEqual(tags.count("contaminado_candle"), 1, "nunca duplica a tag")
        finally:
            storage.close()

    def test_an_unknown_trade_id_reports_not_found_without_raising(self) -> None:
        linhas = marcar(self.paths.db, [("v1", 999_999)])
        self.assertIn("NAO ENCONTRADO", "\n".join(linhas))


if __name__ == "__main__":
    unittest.main()
