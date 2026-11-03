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

    def test_eta_3d_usa_so_os_fechamentos_recentes_nunca_a_media_desde_sempre(self) -> None:
        now = time.time()
        # 1 fechamento antigo (ha 20 dias, fora da janela de 3d) + 3 fechamentos nos ultimos 3 dias
        # (1/dia) -- a media desde sempre daria uma taxa bem mais baixa que a taxa recente.
        self.storage.pr1_insert_signal({
            "chain": "solana", "pool": "ANTIGO", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
            "mint": "MINTX", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "status": "fechado", "entry_price": 100.0, "stop": 80.0,
            "closed_ts": now - 20 * DIA,
        })
        for i in range(3):
            self.storage.pr1_insert_signal({
                "chain": "solana", "pool": f"RECENTE{i}", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": i,
                "mint": f"MINTR{i}", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
                "hora_brt": "09:00", "status": "fechado", "entry_price": 100.0, "stop": 80.0,
                "closed_ts": now - (2 - i) * DIA,
            })
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            eta_acumulado = fd.eta_dias_30_fechados(con, now)
            eta_3d = fd.eta_dias_30_fechados_recente(con, now, ja_fechados=4)
        finally:
            con.close()
        self.assertIsNotNone(eta_3d)
        self.assertLess(eta_3d, eta_acumulado, "taxa recente (3/dia) chega mais rapido que a media desde sempre")

    def test_eta_3d_e_zero_quando_o_alvo_ja_foi_alcancado(self) -> None:
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            eta_3d = fd.eta_dias_30_fechados_recente(con, time.time(), ja_fechados=30)
        finally:
            con.close()
        self.assertEqual(eta_3d, 0.0)

    def test_eventos_pre_admissao_7d_abre_por_tipo_e_por_token_e_destaca_entrada_perdida(self) -> None:
        now = time.time()
        self.storage.pr_upsert_pool("POOLANT", status="verificado", symbol="ANT")
        self.storage.pr_upsert_pool("POOLCHICO", status="verificado", symbol="CHICO")
        self.storage.pr_evento_pre_admissao_insert(now - 1 * DIA, "v1", "POOLANT", "1h", "ENTRADA", now - 1 * DIA)
        self.storage.pr_evento_pre_admissao_insert(now - 2 * DIA, "v1", "POOLANT", "1h", "WATCHLIST", now - 2 * DIA)
        self.storage.pr_evento_pre_admissao_insert(now - 1 * DIA, "v1", "POOLCHICO", "1h", "WATCHLIST", now - 1 * DIA)
        self.storage.pr_evento_pre_admissao_insert(now - 10 * DIA, "v1", "POOLANT", "1h", "ENTRADA", now - 10 * DIA)   # fora de 7d
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            det = fd.eventos_pre_admissao_7d(con, now)
        finally:
            con.close()
        self.assertEqual(det["por_tipo"]["ENTRADA"], 1)   # so a dentro da janela de 7d
        self.assertEqual(det["por_tipo"]["WATCHLIST"], 2)
        self.assertEqual(det["por_token"]["ANT"]["ENTRADA"], 1)
        self.assertNotIn("ENTRADA", det["por_token"].get("CHICO", {}))

    def test_contagem_ativos_admitidos_conta_status_atual_e_historico(self) -> None:
        self.storage.pr_upsert_pool("ATIVO1", status="ativo", added_ts=1.0)
        self.storage.pr_upsert_pool("ATIVO2", status="ativo", added_ts=2.0)
        self.storage.pr_upsert_pool("ENCERRADO1", status="encerrado", added_ts=3.0)
        self.storage.pr_upsert_pool("VERIFICADO1", status="verificado")   # nunca admitido
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            contagem = fd.contagem_ativos_admitidos(con)
        finally:
            con.close()
        self.assertEqual(contagem["ativos"], 2)
        self.assertEqual(contagem["admitidos_total"], 3)

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
        # PATCH 2026-11-02 (3a rodada, Fix B): 429/h TAMBEM por finalidade, nao so agregado.
        self.assertAlmostEqual(uso["rate_limited_h_por_finalidade"]["poll_pool"], 1 / 24.0)

    def test_uso_api_24h_breaks_down_rate_limited_by_finalidade_when_more_than_one(self) -> None:
        now = time.time()
        self.storage.pr_api_uso_insert(now, "gt", "poll_pool", "POOL1", http_status=429, rate_limited=True)
        self.storage.pr_api_uso_insert(now, "rpc", "carteiras", "POOL2", http_status=429, rate_limited=True)
        self.storage.pr_api_uso_insert(now, "rpc", "verificacao_candidato", "POOL3")   # nao limitada -- nunca entra aqui
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            uso = fd.uso_api_24h(con, now)
        finally:
            con.close()
        self.assertAlmostEqual(uso["rate_limited_h"], 2 / 24.0)
        self.assertAlmostEqual(uso["rate_limited_h_por_finalidade"]["poll_pool"], 1 / 24.0)
        self.assertAlmostEqual(uso["rate_limited_h_por_finalidade"]["carteiras"], 1 / 24.0)
        self.assertNotIn("verificacao_candidato", uso["rate_limited_h_por_finalidade"])

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

    def test_latencia_candle_24h_breaks_down_by_tier_and_by_pool(self) -> None:
        now = time.time()
        self.storage.pr_candle_latencia_insert(now, "QUENTE1", "1h", 5.0, tier=0)
        self.storage.pr_candle_latencia_insert(now, "FRIO1", "1h", 50.0, tier=2)
        self.storage.pr_candle_latencia_insert(now, "FRIO1", "1h", 60.0, tier=2)
        con = fd._conectar_ro(self.storage.paths.db)   # noqa: SLF001
        try:
            lat_stats = fd.latencia_candle_24h(con, now)
        finally:
            con.close()
        self.assertEqual(lat_stats["por_tier"]["quente"]["n"], 1)
        self.assertEqual(lat_stats["por_tier"]["frio"]["n"], 2)
        self.assertEqual(lat_stats["por_pool"]["FRIO1"]["max"], 60.0)
        self.assertEqual(lat_stats["por_pool"]["QUENTE1"]["max"], 5.0)

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
