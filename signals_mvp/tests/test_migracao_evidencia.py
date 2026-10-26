"""PEDIDO (PARTE 1 de 2), regra 5: migracoes idempotentes sobre um banco ANTIGO (shape anterior a esta
revisao -- sem `carteiras_pro_presentes`, sem `pr_trajetoria`/`pr_baseline`). Nunca no banco real (banco
temporario, apagado no tearDown); backup automatico (FASE 6, `Storage.backup_to`) antes de abrir."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..storage import Storage

# Shape da pr1_signals/pr2_signals ANTES desta revisao (sem carteiras_pro_presentes) -- o suficiente
# pra provar a migracao, nao o schema inteiro (ver storage.SCHEMA para o schema real/atual).
_OLD_PR1_SIGNALS = """
CREATE TABLE pr1_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chain TEXT NOT NULL, pool TEXT NOT NULL, tf TEXT NOT NULL,
  evento TEXT NOT NULL DEFAULT 'ENTRADA', ts_fechamento INTEGER NOT NULL,
  mint TEXT, symbol TEXT, launchpad TEXT, dex TEXT, versao_config_v1 TEXT NOT NULL,
  gatilho TEXT, tags TEXT, janela_ouro TEXT, hora_brt TEXT, origem TEXT, teste_vol_ratio REAL,
  event_json TEXT, status TEXT NOT NULL DEFAULT 'aberto',
  entry_price REAL, stop REAL, topo REAL, s_suporte REAL, r_resistencia REAL,
  tp1_price REAL, tp1_ts REAL, exit_full_price REAL, exit_full_ts REAL,
  result_net REAL, reason TEXT, tempo_h REAL,
  holders_tag TEXT, mint_authority TEXT, freeze_authority TEXT, liquidez_usd REAL,
  tg_message_id INTEGER, alert_ts REAL, closed_ts REAL,
  ts_fechamento_candle INTEGER, ts_alerta REAL, ts_envio_telegram REAL, retorno_sol_dia REAL,
  token_signal_seq INTEGER, fonte_candle TEXT NOT NULL DEFAULT 'gt',
  UNIQUE (chain, pool, tf, evento, ts_fechamento)
);
"""
_OLD_PR2_SIGNALS = _OLD_PR1_SIGNALS.replace("pr1_signals", "pr2_signals").replace(
    "versao_config_v1", "versao_config_v2").replace(
    "UNIQUE (chain, pool, tf, evento, ts_fechamento)",
    "so_v2 INTEGER NOT NULL DEFAULT 1, UNIQUE (chain, pool, tf, evento, ts_fechamento)",
)
_OLD_PR_BARS = """
CREATE TABLE pr_bars (
  pool TEXT NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL, o REAL, h REAL, l REAL, c REAL, v REAL,
  filled INTEGER, fonte TEXT NOT NULL DEFAULT 'gt', PRIMARY KEY (pool, tf, ts)
);
"""


def _build_old_db(db_path: Path) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript("PRAGMA journal_mode=WAL;" + _OLD_PR1_SIGNALS + _OLD_PR2_SIGNALS + _OLD_PR_BARS
                           + "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
        con.execute(
            "INSERT INTO pr1_signals (chain,pool,tf,evento,ts_fechamento,mint,symbol,launchpad,dex,"
            "versao_config_v1,gatilho,tags,janela_ouro,hora_brt,status,entry_price,stop,topo,s_suporte,"
            "result_net,reason,tempo_h,fonte_candle) VALUES "
            "('solana','POOLOLD','1h','ENTRADA',1000,'MINTOLD','OLD','pumpfun','pumpswap','abc123',"
            "'[]','[]','janela_ouro','09:00','fechado',100.0,80.0,200.0,90.0,0.25,'tp1',5.0,'gt')"
        )
        con.commit()
    finally:
        con.close()


class MigracaoSobreBancoAntigoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="migracao_evidencia_"))
        self.paths = make_paths(self.tmp)
        self.paths.dados.mkdir(parents=True, exist_ok=True)
        _build_old_db(self.paths.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_opening_an_old_database_never_raises_and_preserves_existing_rows(self) -> None:
        storage = Storage(self.paths)
        try:
            row = storage.pr1_signal_by_key("solana", "POOLOLD", "1h", "ENTRADA", 1000)
            self.assertIsNotNone(row)
            self.assertEqual(row["symbol"], "OLD")
            self.assertEqual(row["result_net"], 0.25)
            # a coluna nova existe e comeca NULL (nunca inventa um valor pro dado antigo)
            self.assertIsNone(row["carteiras_pro_presentes"])
            # as tabelas novas existem e estao vazias (nunca populadas por conta propria)
            self.assertEqual(storage.pr_trajetoria_all(), [])
            self.assertEqual(storage.pr_baseline_all(), [])
        finally:
            storage.close()

    def test_new_tables_are_fully_usable_after_migrating_an_old_database(self) -> None:
        storage = Storage(self.paths)
        try:
            storage.pr_trajetoria_upsert("v1", 1, 0.0, chain="solana", pool="POOLOLD", tf="1h",
                                        mint="MINTOLD", symbol="OLD", t_entrada=1000.0, preco_entrada=100.0,
                                        risco_pct=20.0, r_unidade=20.0, fonte_candle="gt")
            self.assertEqual(len(storage.pr_trajetoria_all()), 1)
        finally:
            storage.close()

    def test_reopening_the_already_migrated_database_is_idempotent(self) -> None:
        s1 = Storage(self.paths)
        s1.close()
        s2 = Storage(self.paths)  # reabre (restart do bot) -- nunca falha, nunca duplica coluna/tabela
        try:
            row = s2.pr1_signal_by_key("solana", "POOLOLD", "1h", "ENTRADA", 1000)
            self.assertIsNotNone(row)
            self.assertEqual(row["symbol"], "OLD")
        finally:
            s2.close()

    def test_backup_still_works_on_a_freshly_migrated_database(self) -> None:
        storage = Storage(self.paths)
        try:
            dest = self.tmp / "backups" / "copia.sqlite"
            storage.backup_to(dest)
            self.assertTrue(dest.exists())
            con = sqlite3.connect(str(dest))
            try:
                row = con.execute("SELECT symbol FROM pr1_signals WHERE pool='POOLOLD'").fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "OLD")
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
