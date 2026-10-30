"""PEDIDO (PARTE 1 de 2): Storage.pr_trajetoria_*/pr_baseline_* (tabelas novas, medicao ao lado de V1/V2)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage


class PrTrajetoriaStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pr_trajetoria_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_insert_then_update_never_duplicates(self) -> None:
        self.storage.pr_trajetoria_upsert(
            "v1", 7, 1_000.0, chain="solana", pool="POOL1", tf="1h", mint="MINT1", symbol="CAT",
            t_entrada=1_000.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
        )
        self.storage.pr_trajetoria_upsert("v1", 7, 2_000.0, mfe_r=1.5, mfe_h=6.0)
        rows = self.storage.pr_trajetoria_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["preco_entrada"], 100.0)
        self.assertEqual(rows[0]["mfe_r"], 1.5)
        self.assertEqual(rows[0]["criado_ts"], 1_000.0)
        self.assertEqual(rows[0]["atualizado_ts"], 2_000.0)

    def test_versao_and_entry_id_are_independent_keys(self) -> None:
        self.storage.pr_trajetoria_upsert("v1", 1, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                          t_entrada=0.0, preco_entrada=1.0, risco_pct=10.0, r_unidade=0.1,
                                          fonte_candle="gt")
        self.storage.pr_trajetoria_upsert("v2", 1, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                          t_entrada=0.0, preco_entrada=2.0, risco_pct=10.0, r_unidade=0.2,
                                          fonte_candle="gt")
        rows = self.storage.pr_trajetoria_all()
        self.assertEqual(len(rows), 2, "mesmo entry_id, versao diferente -- 2 linhas distintas")

    def test_pr_trajetoria_abertas_only_lists_unclosed_rows(self) -> None:
        self.storage.pr_trajetoria_upsert("v1", 1, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                          t_entrada=0.0, preco_entrada=1.0, risco_pct=10.0, r_unidade=0.1,
                                          fonte_candle="gt", fechado=0)
        self.storage.pr_trajetoria_upsert("v1", 2, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                          t_entrada=0.0, preco_entrada=1.0, risco_pct=10.0, r_unidade=0.1,
                                          fonte_candle="gt", fechado=1)
        abertas = self.storage.pr_trajetoria_abertas("v1")
        self.assertEqual([r["entry_id"] for r in abertas], [1])

    def test_csv_export_writes_the_trajetoria_file(self) -> None:
        self.storage.pr_trajetoria_upsert("v1", 1, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="CAT",
                                          t_entrada=0.0, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0,
                                          fonte_candle="gt", mfe_r=1.2, ret_r_24h=0.5, fechado=1)
        written = self.storage.export_csvs(force=True)
        self.assertIn("pos_runner_v1_trajetoria.csv", written)
        content = self.storage.paths.pos_runner_v1_trajetoria_csv.read_text(encoding="utf-8")
        self.assertIn("CAT", content)
        self.assertIn("1.2", content)


class PrBaselineStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pr_baseline_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_insert_then_update_never_duplicates(self) -> None:
        self.storage.pr_baseline_upsert("v1", 5, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                        n_controles=10, controles_json="[]")
        self.storage.pr_baseline_upsert("v1", 5, 1.0, r_controle_medio=0.3, r_sinal=1.0, dif_pareada=0.7)
        rows = self.storage.pr_baseline_all("v1")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["dif_pareada"], 0.7)

    def test_pendentes_excludes_rows_with_dif_pareada_already_set(self) -> None:
        self.storage.pr_baseline_upsert("v1", 1, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                        n_controles=10, controles_json="[]")
        self.storage.pr_baseline_upsert("v1", 2, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                        n_controles=10, controles_json="[]", dif_pareada=0.1)
        pendentes = self.storage.pr_baseline_pendentes("v1")
        self.assertEqual([r["entry_id"] for r in pendentes], [1])

    def test_resolvidas_com_dif_only_lists_finished_rows(self) -> None:
        self.storage.pr_baseline_upsert("v1", 1, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                        n_controles=10, controles_json="[]")
        self.storage.pr_baseline_upsert("v1", 2, 0.0, chain="solana", pool="P", tf="1h", mint="M", symbol="S",
                                        n_controles=10, controles_json="[]", dif_pareada=0.5)
        resolvidas = self.storage.pr_baseline_resolvidas_com_dif("v1")
        self.assertEqual([r["entry_id"] for r in resolvidas], [2])


if __name__ == "__main__":
    unittest.main()
