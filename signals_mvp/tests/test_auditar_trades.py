"""PEDIDO 2026-10-27 (diagnostico McRib/yagi): `scripts/auditar_trades.py` -- SOMENTE LEITURA, nunca
escreve no banco (conecta em modo `mode=ro`). Monta um banco temporario com o shape REAL de
`storage.SCHEMA` (via `Storage`, depois fecha e reabre so leitura) para o teste nao depender do
schema escrito a mao."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts.auditar_trades import executar
from ..storage import Storage


class AuditarTradesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditoria_"))
        self.paths = make_paths(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _popular(self) -> None:
        storage = Storage(self.paths)
        try:
            # candles: 3 antes do gatilho (ts 0..2), gatilho em ts=3 (McRib-style: close >> vizinho/pico),
            # fill em ts=4 (o candle seguinte), 1 depois do EXIT em ts=6.
            bars = [
                (0, 1_000.0, 1_050.0, 980.0, 1_000.0, 1.0, 0),
                (3600, 1_000.0, 1_050.0, 980.0, 1_010.0, 1.0, 0),
                (7200, 1_010.0, 1_060.0, 990.0, 1_020.0, 1.0, 0),
                (10800, 1_020.0, 44_200_000.0, 1_000.0, 44_100_000.0, 1.0, 0),   # [3] gatilho suspeito
                (14400, 44_000_000.0, 44_100_000.0, 439_000.0, 440_500.0, 1.0, 0),  # [4] fill real
                (18000, 440_000.0, 441_000.0, 100_000.0, 110_000.0, 1.0, 0),      # [5] EXIT FULL (stop)
                (21600, 110_000.0, 112_000.0, 105_000.0, 108_000.0, 1.0, 0),      # [6] 1 depois da saida
            ]
            storage.pr_append_bars("POOLX", "1h", bars, fonte="gt")
            storage.pr1_insert_signal({
                "chain": "solana", "pool": "POOLX", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 10800,
                "mint": "MINTX", "symbol": "McRib", "launchpad": "pumpfun", "dex": "pumpswap",
                "versao_config_v1": "abc123", "gatilho": '["power_candle_rompimento"]', "tags": "[]",
                "janela_ouro": "janela_ouro", "hora_brt": "10:05", "status": "fechado",
                "entry_price": 440_500.0, "entry_price_alerta": 44_100_000.0, "stop": 440_000.0,
                "topo": 1_050.0, "exit_full_price": 440_000.0, "exit_full_ts": 18000,
                "event_json": '{"kind":"ENTRADA","idx":3,"ts":10800,"decision_ts":14400,'
                              '"data":{"TOPO":1050.0,"P_peak":1050.0}}',
                "fonte_candle": "gt",
            })
            storage.export_csvs(force=True)
        finally:
            storage.close()

    def test_a_suspicious_trigger_candle_is_flagged_suspeito_in_the_verdict(self) -> None:
        self._popular()
        saida = executar(self.paths.db, "v1", None)
        self.assertIn("McRib", saida)
        self.assertIn("VEREDITO v1", saida)
        self.assertIn("SUSPEITO(", saida)
        self.assertIn("[3]", saida)

    def test_filters_by_simbolo(self) -> None:
        self._popular()
        saida = executar(self.paths.db, "v1", "McRib")
        self.assertIn("McRib", saida)
        saida_vazia = executar(self.paths.db, "v1", "NaoExiste")
        self.assertIn("nenhum trade", saida_vazia)

    def test_never_writes_to_the_database_readonly_connection(self) -> None:
        self._popular()
        before = self.paths.db.stat().st_mtime_ns
        executar(self.paths.db, None, None)
        after = self.paths.db.stat().st_mtime_ns
        self.assertEqual(before, after, "auditoria SOMENTE LEITURA nunca altera o arquivo do banco")


if __name__ == "__main__":
    unittest.main()
