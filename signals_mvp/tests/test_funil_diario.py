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

    def test_montar_funil_counts_aposentados_and_readmitidos_per_day(self) -> None:
        """PEDIDO 2026-11-02 (FASE 1e)."""
        base = 1_000.0 * DIA
        self.storage.pr_dormente_insert("POOL1", "MINT1", "POOL1", "rotacao", 50_000.0, base + H)
        d = self.storage._all("SELECT id FROM pr_dormentes WHERE pool='POOL1'")[0]["id"]   # noqa: SLF001
        self.storage.pr_dormente_update(d, status="readmitido", ts_readmitido=base + 5 * H)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            funil = fd.montar_funil(con)
        finally:
            con.close()
        dia = fd._dia_utc(base)   # noqa: SLF001
        self.assertEqual(funil[dia]["aposentados"], 1)
        self.assertEqual(funil[dia]["readmitidos"], 1)

    def test_pct_runner_7d_uses_only_recently_admitted_pools(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("RECENTE_RUNNER", status="ativo", added_ts=now - 2 * DIA)
        self.storage.pr_funil_marco_insert("RECENTE_RUNNER", "v1", "runner", now - 1 * DIA)
        self.storage.pr_upsert_pool("RECENTE_SEM_RUNNER", status="ativo", added_ts=now - 1 * DIA)
        self.storage.pr_upsert_pool("ANTIGO_FORA_DA_JANELA", status="ativo", added_ts=now - 30 * DIA)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            pct = fd.pct_runner_7d(con, now)
        finally:
            con.close()
        self.assertAlmostEqual(pct, 50.0)   # 1 de 2 admitidos na janela de 7d chegou a runner

    def test_pct_runner_7d_is_none_with_no_pool_admitted_in_the_window(self) -> None:
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            pct = fd.pct_runner_7d(con, time.time())
        finally:
            con.close()
        self.assertIsNone(pct)

    def test_uso_api_24h_reports_calls_per_hour_by_finalidade_and_rate_limited(self) -> None:
        now = time.time()
        for _ in range(24):   # 24 chamadas em 24h = 1/h
            self.storage.pr_api_uso_insert(now, "gt", "poll_pool", "POOL1", http_status=200)
        self.storage.pr_api_uso_insert(now, "gt", "poll_pool", "POOL2", http_status=429, rate_limited=True)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            uso = fd.uso_api_24h(con, now)
        finally:
            con.close()
        self.assertAlmostEqual(uso["chamadas_h"]["poll_pool"], 25 / 24.0)
        self.assertAlmostEqual(uso["rate_limited_h"], 1 / 24.0)

    def test_latencia_candle_24h_computes_percentiles_and_near_limiar_count(self) -> None:
        now = time.time()
        for lat in (10.0, 20.0, 30.0, 3000.0):   # 3000s esta >= 80% de 3600s (limiar)
            self.storage.pr_candle_latencia_insert(now, "POOL1", "1h", lat)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            lat_stats = fd.latencia_candle_24h(con, now)
        finally:
            con.close()
        self.assertEqual(lat_stats["n"], 4)
        self.assertEqual(lat_stats["max"], 3000.0)
        self.assertEqual(lat_stats["n_perto_do_limiar"], 1)

    def test_latencia_candle_24h_is_sd_with_no_candle_processed(self) -> None:
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            lat_stats = fd.latencia_candle_24h(con, time.time())
        finally:
            con.close()
        self.assertEqual(lat_stats["n"], 0)
        self.assertIsNone(lat_stats["p50"])

    def test_capacidade_rss_24h_computes_average_and_worst_per_pool_and_extra_pools(self) -> None:
        now = time.time()
        self.storage.pr_rss_amostra_insert(now, 200 * 1024, 2)    # 100MB/pool
        self.storage.pr_rss_amostra_insert(now, 400 * 1024, 2)    # 200MB/pool (pior)
        self.storage.pr_rss_amostra_insert(now, 999, 0)           # 0 pools: ignorado (divisao indefinida)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            cap = fd.capacidade_rss_24h(con, now)
        finally:
            con.close()
        self.assertEqual(cap["n"], 2)
        self.assertAlmostEqual(cap["medio_kb"], 150 * 1024)
        self.assertAlmostEqual(cap["pior_kb"], 200 * 1024)
        self.assertEqual(cap["pools_extras_com_folga"], (200 * 1024) // (150 * 1024))

    def test_capacidade_rss_24h_is_sd_with_no_sample(self) -> None:
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            cap = fd.capacidade_rss_24h(con, time.time())
        finally:
            con.close()
        self.assertEqual(cap["n"], 0)
        self.assertIsNone(cap["medio_kb"])

    def test_executar_includes_the_new_fase1_sections(self) -> None:
        now = time.time()
        self.storage.pr_api_uso_insert(now, "gt", "poll_pool", "POOL1", http_status=200)
        self.storage.pr_candle_latencia_insert(now, "POOL1", "1h", 42.0)
        self.storage.pr_rss_amostra_insert(now, 300 * 1024, 3)
        texto = fd.executar(self.storage.paths.db)
        self.assertIn("% runner (admitidos nos ultimos 7d)", texto)
        self.assertIn("## Uso de API (24h)", texto)
        self.assertIn("poll_pool=", texto)
        self.assertIn("## Latencia do candle (24h)", texto)
        self.assertIn("p50=42s", texto)
        self.assertIn("## Capacidade (RSS)", texto)
        self.assertIn("pools extras com", texto)

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
