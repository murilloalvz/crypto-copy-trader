"""PEDIDO 2026-10-30 (FASE 2, item 1): `scripts/funil_diario.py` -- so leitura, zero rede."""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import funil_diario as fd
from ..storage import Storage

H = 3600
DIA = 86_400


class FunilDiarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="funil_diario_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_montar_funil_counts_distinct_pools_per_utc_day_for_each_stage(self) -> None:
        base = 1_000.0 * DIA   # dia UTC redondo, facil de verificar
        self.storage.pr_upsert_pool("POOL1", status="ativo", found_ts=base, added_ts=base + H)
        self.storage.pr_upsert_pool("POOL2", status="ativo", found_ts=base, added_ts=base + H)
        self.storage.pr_funil_marco_insert("POOL1", "v1", "runner", base + 2 * H)
        self.storage.pr_funil_marco_insert("POOL1", "v2", "runner", base + 2 * H)   # mesmo pool, MESMO dia -- 1 so
        self.storage.pr_funil_marco_insert("POOL1", "v1", "caixa", base + 3 * H)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            funil = fd.montar_funil(con)
        finally:
            con.close()
        dia = fd._dia_utc(base)   # noqa: SLF001
        self.assertEqual(funil[dia]["descobertos"], 2)
        self.assertEqual(funil[dia]["admitidos"], 2)
        self.assertEqual(funil[dia]["runner"], 1, "mesmo pool em V1 e V2 conta so 1x no funil")
        self.assertEqual(funil[dia]["caixa"], 1)

    def test_eta_is_none_with_no_closed_tokens_yet(self) -> None:
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            eta = fd.eta_dias_30_fechados(con, time.time())
        finally:
            con.close()
        self.assertIsNone(eta)

    def test_eta_is_zero_once_the_target_is_already_reached(self) -> None:
        now = time.time()
        for i in range(30):
            self.storage.pr1_insert_signal({
                "chain": "solana", "pool": f"POOL{i}", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000 + i,
                "mint": f"MINT{i}", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
                "hora_brt": "09:00", "status": "fechado", "entry_price": 100.0, "stop": 80.0, "closed_ts": now - DIA,
            })
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            eta = fd.eta_dias_30_fechados(con, now)
        finally:
            con.close()
        self.assertEqual(eta, 0.0)

    def test_eta_projects_linearly_from_the_average_closing_rate(self) -> None:
        now = time.time()
        # 10 tokens fechados, igualmente espalhados nos ultimos 10 dias -- taxa de 1/dia, faltam 20
        # pra chegar a 30 -- ETA ~20 dias.
        for i in range(10):
            self.storage.pr1_insert_signal({
                "chain": "solana", "pool": f"POOL{i}", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000 + i,
                "mint": f"MINT{i}", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
                "hora_brt": "09:00", "status": "fechado", "entry_price": 100.0, "stop": 80.0,
                "closed_ts": now - (10 - i) * DIA,
            })
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            eta = fd.eta_dias_30_fechados(con, now)
        finally:
            con.close()
        self.assertIsNotNone(eta)
        self.assertAlmostEqual(eta, 20.0, delta=1.0)

    def test_executar_never_writes_and_includes_fase1_counters(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("POOL1", status="ativo", found_ts=now)
        self.storage.pr_entrada_atrasada_insert(now, "v1", "POOL1", "1h", now - 5_000.0, 5_000.0)
        antes_pools = self.storage._all("SELECT * FROM pr_pools")   # noqa: SLF001
        texto = fd.executar(self.storage.paths.db)
        depois_pools = self.storage._all("SELECT * FROM pr_pools")   # noqa: SLF001
        self.assertEqual([dict(r) for r in antes_pools], [dict(r) for r in depois_pools])
        self.assertIn("# Funil diario", texto)
        self.assertIn("entradas_atrasadas", texto)
        self.assertIn("ETA at 30 tokens", texto)


if __name__ == "__main__":
    unittest.main()
