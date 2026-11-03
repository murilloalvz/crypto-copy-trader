"""PEDIDO (PARTE 2A) FASE 4: colunas de contexto/execucao na ENTRADA (V1 e V2) -- so dado JA
disponivel no momento da decisao (zero chamada nova de GT/DexPaprika/RPC); nunca lidas por regra/
filtro/tamanho/saida (R oficial `result_net` nunca muda). Sem rede."""

from __future__ import annotations

import json
import unittest

from .test_pos_runner import textbook
from .test_pos_runner_live import LiveHarness, start_tracking


class ContextoExecucaoV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_entry_populates_the_new_columns_from_data_already_available_at_decision_time(self) -> None:
        start_tracking(self.h)
        pool_row = self.h.storage.pr_pool("POOL1")
        info = json.loads(pool_row["info"] or "{}")
        # simula o que `offer()` ja teria congelado na descoberta (GT devolve isso no MESMO payload
        # de pools) -- so pra provar ticket_medio_usd/volume_24h/n_txs_24h sem reconstruir o JSON
        # completo do GeckoTerminal no fixture de teste.
        info.update({"vol_h24_usd": 500_000.0, "n_txs_h24": 2_000})
        self.h.storage.pr_upsert_pool("POOL1", info=json.dumps(info))
        self.h.run_hours(17)
        sinal = self.h.storage.pr1_signals()[0]
        self.assertIn(sinal["dia_semana"], ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"))
        self.assertIsNotNone(sinal["idade_dias"])
        self.assertAlmostEqual(sinal["mc_na_entrada"], sinal["entry_price_alerta"], places=6)
        self.assertEqual(sinal["volume_24h"], 500_000.0)
        self.assertEqual(sinal["n_txs_24h"], 2_000)
        self.assertAlmostEqual(sinal["ticket_medio_usd"], 500_000.0 / 2_000, places=6)
        self.assertIsNotNone(sinal["caixa_candles"])
        self.assertIsNone(sinal["holders_count"], "nunca inventa uma contagem agregada de holders")
        if sinal["liquidez_usd"]:
            esperado = 100.0 * 10.0 / sinal["liquidez_usd"]
            self.assertAlmostEqual(sinal["slippage_estimado_pct"], esperado, places=9)
        # MESMO cenario tambem fecha uma ENTRADA da V2 (mesmo candle, ver test_pos_runner_v2_live.py)
        # -- as MESMAS colunas precisam estar preenchidas la tambem.
        sinal_v2 = self.h.storage.pr2_signals()[0]
        self.assertEqual(sinal_v2["volume_24h"], 500_000.0)
        self.assertEqual(sinal_v2["n_txs_24h"], 2_000)
        self.assertIsNotNone(sinal_v2["dia_semana"])

    def test_r_liquido_estimado_uses_the_simple_slippage_model_never_the_official_cost_model(self) -> None:
        from ..pos_runner.candles import Bar
        s_bars = textbook(start_flat=0)
        H = 3600
        t = s_bars.bars[-1].ts + H
        extra = [
            Bar(t, 400_000, 420_000, 395_000, 410_000, 1_000.0),
            Bar(t + H, 405_000, 1_050_000, 400_000, 620_000, 1_000.0),
            Bar(t + 2 * H, 700_000, 710_000, 690_000, 705_000, 1_000.0),
            Bar(t + 3 * H, 705_000, 710_000, 151_000, 152_000, 1_000.0),
        ]
        self.h.world.add_series("POOL1", "1h", s_bars.bars + extra)
        self.h.list_pool()
        self.h.tick()
        self.h.verifier.step()
        self.h.tick()
        self.h.storage.pr_upsert_pool("POOL1", info=json.dumps({
            **json.loads((self.h.storage.pr_pool("POOL1")["info"] or "{}")), "liq_usd": 100_000.0,
        }))
        for _ in range(27):
            self.h.clock.advance(H)
            self.h.tick()
        sinal = self.h.storage.pr1_signals()[0]
        self.assertEqual(sinal["status"], "fechado")
        self.assertIsNotNone(sinal["slippage_estimado_pct"])
        self.assertIsNotNone(sinal["r_liquido_estimado"])
        self.assertNotEqual(sinal["r_liquido_estimado"], sinal["result_net"],
                            "modelo simples tem que divergir do CostModel oficial (senao o teste nao prova nada)")


class ContextoExecucaoSombraTests(unittest.TestCase):
    """As MESMAS colunas de contexto/execucao tambem saem preenchidas nos sinais sombra (FASE 3) --
    so sem `holder_top1_pct` (a sombra nunca chama `adapter.holders()` so pra isso, zero chamada
    extra)."""

    def test_sombra_row_gets_the_same_context_columns_except_holder_top1_pct(self) -> None:
        from .test_sombra import _mc_baixo_bars
        h = LiveHarness()
        try:
            h.world.add_series("POOL1", "1h", _mc_baixo_bars())
            h.list_pool()
            h.tick()
            h.verifier.step()
            h.tick()
            h.run_hours(30)
            sombra = h.storage.pr_sombra_signals(versao="sombra:filtrado_mc_baixo")
            self.assertEqual(len(sombra), 1, h.texts())
            row = sombra[0]
            self.assertIsNotNone(row["dia_semana"])
            self.assertIsNotNone(row["idade_dias"])
            self.assertIsNotNone(row["caixa_candles"])
            self.assertIsNone(row["holder_top1_pct"], "sombra nunca chama adapter.holders() so pra isto")
            self.assertIsNone(row["holders_count"])
        finally:
            h.close()


class ContextoExecucaoMigrationTests(unittest.TestCase):
    def test_opening_a_pre_existing_database_backfills_the_new_columns_as_null(self) -> None:
        """Migracao idempotente: abre um banco de uma copia "antiga" (sem as colunas da FASE 4) e
        confirma que elas aparecem, NULL, sem perder nenhum dado existente."""
        import sqlite3
        import tempfile
        from pathlib import Path

        from ..config import make_paths
        from ..storage import Storage

        tmp = Path(tempfile.mkdtemp(prefix="pr_migracao_"))
        paths = make_paths(tmp)
        paths.dados.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(paths.db))
        con.execute(
            "CREATE TABLE pr1_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, chain TEXT NOT NULL, "
            "pool TEXT NOT NULL, tf TEXT NOT NULL, evento TEXT NOT NULL DEFAULT 'ENTRADA', "
            "ts_fechamento INTEGER NOT NULL, versao_config_v1 TEXT NOT NULL, status TEXT NOT NULL "
            "DEFAULT 'aberto', fonte_candle TEXT NOT NULL DEFAULT 'gt', "
            "UNIQUE (chain, pool, tf, evento, ts_fechamento))"
        )
        con.execute(
            "INSERT INTO pr1_signals (chain, pool, tf, ts_fechamento, versao_config_v1) "
            "VALUES ('solana', 'POOLANTIGO', '1h', 1000, 'versaoantiga')"
        )
        con.commit()
        con.close()
        storage = Storage(paths)
        try:
            row = storage.pr1_signal_by_key("solana", "POOLANTIGO", "1h", "ENTRADA", 1000)
            self.assertIsNotNone(row, "a migracao nunca pode perder uma linha ja existente")
            for coluna in ("dia_semana", "idade_dias", "mc_na_entrada", "volume_24h", "caixa_candles",
                          "holder_top1_pct", "slippage_estimado_pct", "r_liquido_estimado", "n_txs_24h",
                          "ticket_medio_usd", "holders_count"):
                self.assertIsNone(row[coluna], f"{coluna} precisa ser NULL em sinal anterior a FASE 4")
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
