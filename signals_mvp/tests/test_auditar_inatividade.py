"""PEDIDO 2026-11-05 (PARTE 4): testes de `scripts/auditar_inatividade.py` -- SOMENTE LEITURA,
nenhum criterio de rotacao decidido aqui, so medicao."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage
from ..scripts import auditar_inatividade as inat


def _inserir_pool(db_path: Path, pool: str, symbol: str, added_ts: float) -> None:
    con = sqlite3.connect(str(db_path))
    con.execute("INSERT INTO pr_pools (pool, symbol, status, added_ts) VALUES (?,?,?,?)",
               (pool, symbol, "ativo", added_ts))
    con.commit()
    con.close()


class MedirPoolAtivoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_inatividade_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_conta_candles_de_volume_positivo_separado_de_candles_totais(self) -> None:
        now = 1_000_000.0
        _inserir_pool(self.storage.paths.db, "POOL1", "CAT", now - 50 * 3600.0)
        rows = []
        for h_atras in range(50, -1, -1):
            ts = now - h_atras * 3600.0
            vol = 0.0 if h_atras % 3 == 0 else 100.0   # um a cada 3 candles tem volume=0
            rows.append((ts, 100.0, 100.0, 100.0, 100.0, vol, 0))
        self.storage.pr_append_bars("POOL1", "1h", rows)
        row = self.storage.pr_pool("POOL1")
        linha = inat.medir_pool_ativo(self.storage, row, now)
        self.assertEqual(linha["symbol"], "CAT")
        self.assertLess(linha["n_vol_pos_24h"], linha["n_candles_24h"])
        self.assertAlmostEqual(linha["horas_desde_ultimo_vol_pos"], 0.0, delta=1.0)
        self.assertAlmostEqual(linha["horas_na_vaga"], 50.0, delta=1.0)

    def test_pool_sem_nenhum_candle_1h_fica_explicito_nunca_confundido_com_atrasado(self) -> None:
        now = 1_000_000.0
        _inserir_pool(self.storage.paths.db, "POOL2", "NOVO", now - 3600.0)
        row = self.storage.pr_pool("POOL2")
        linha = inat.medir_pool_ativo(self.storage, row, now)
        self.assertEqual(linha["n_candles_totais"], 0)
        self.assertIsNone(linha["horas_desde_ultimo_vol_pos"])
        texto = inat.formatar([linha], {})
        self.assertIn("sem nenhum candle 1h ainda", texto)

    def test_motivo_s_d_mostra_http_status_bruto_em_vez_de_ficar_opaco(self) -> None:
        now = 1_000_000.0
        _inserir_pool(self.storage.paths.db, "POOL3", "WASTED", now - 10 * 3600.0)
        self.storage.pr_append_bars("POOL3", "1h", [(now - 5 * 3600.0, 100.0, 100.0, 100.0, 100.0, 50.0, 0)])
        # status 404 -- fora das categorias conhecidas de _motivo_atraso_candle (429/5xx/200) => "s/d"
        self.storage.pr_api_uso_insert(now - 3 * 3600.0, "gt", "poll_pool", pool="POOL3", http_status=404, rate_limited=0)
        row = self.storage.pr_pool("POOL3")
        linha = inat.medir_pool_ativo(self.storage, row, now)
        self.assertEqual(linha["motivo"], "s/d")
        self.assertIsNotNone(linha["detalhe_bruto_quando_s_d"])
        self.assertIn("404", linha["detalhe_bruto_quando_s_d"])


class AtividadePreEntradaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_inatividade_pre_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_media_por_token_nunca_pesa_2x_so_por_ter_2_sinais(self) -> None:
        # PEAK tem 2 sinais (8 e 12 candles com vol>0 nas 24h antes -- media=10); DOG tem 1 (4).
        # Quartis sobre os valores POR TOKEN (10, 4), nunca sobre os 3 sinais brutos (8,12,4).
        for pool, entry_ts, n_vol_pos, symbol in (
            ("P1", 100_000.0, 8, "PEAK"), ("P2", 200_000.0, 12, "PEAK"), ("P3", 300_000.0, 4, "DOG"),
        ):
            signal_id = self.storage.pr1_insert_signal({
                "chain": "solana", "pool": pool, "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 0,
                "mint": f"MINT_{pool}", "symbol": symbol, "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]",
                "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
                "entry_price": 100.0, "stop": 80.0, "reason": "stop", "closed_ts": entry_ts + 3_600.0,
            })
            self.storage.pr_trajetoria_upsert(
                "v1", signal_id, 0.0, chain="solana", pool=pool, tf="1h", mint=f"MINT_{pool}", symbol=symbol,
                t_entrada=entry_ts, preco_entrada=100.0, risco_pct=20.0, r_unidade=20.0, fonte_candle="gt",
            )
            rows = []
            for h_atras in range(24, 0, -1):
                ts = entry_ts - h_atras * 3600.0
                vol = 100.0 if h_atras <= n_vol_pos else 0.0
                rows.append((ts, 100.0, 100.0, 100.0, 100.0, vol, 0))
            rows.append((entry_ts, 100.0, 105.0, 95.0, 102.0, 50.0, 0))
            self.storage.pr_append_bars(pool, "1h", rows)
        atividade = inat.atividade_pre_entrada_por_token(self.storage, self.storage.paths.db)
        self.assertIn("ao_vivo", atividade)
        self.assertEqual(atividade["ao_vivo"]["n_tokens_distintos"], 2)
        q = atividade["ao_vivo"]["quartis"]
        self.assertAlmostEqual(q["mediana"], 7.0, delta=0.01)   # mediana de (10, 4)


class ExecutarSmokeTests(unittest.TestCase):
    def test_executar_nunca_crasha_com_banco_vazio(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="auditar_inatividade_vazio_"))
        try:
            storage = Storage(make_paths(tmp))
            db_path = storage.paths.db
            storage.close()
            texto = inat.executar(db_path)
            self.assertIn("auditar_inatividade", texto)
            self.assertNotIn("Traceback", texto)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
