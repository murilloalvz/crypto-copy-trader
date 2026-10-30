"""PEDIDO 2026-10-30 (FASE 1c): `scripts/auditar_atraso_entradas.py` -- tagueia `entrada_atrasada`
em ENTRADAs V1/V2 ja existentes cujo alerta saiu depois do limiar (`_late`, mesmo de
`live.py: _entry_v1`/`_entry_v2`), e estima `atraso_candles` quando ainda NULL. So leitura de
rede/`pr_bars`; nunca apaga nada."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ..config import make_paths
from ..scripts import auditar_atraso_entradas as aud
from ..storage import Storage

H = 3600


def _sinal_v1(**over) -> dict:
    base = {
        "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
        "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
        "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]",
        "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
        "entry_price": 100.0, "stop": 80.0,
    }
    base.update(over)
    return base


class AuditarAtrasoEntradasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditar_atraso_"))
        self.storage = Storage(make_paths(self.tmp))

    def tearDown(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_signal_alerted_past_the_threshold_is_tagged_and_atraso_candles_is_estimated(self) -> None:
        sid = self.storage.pr1_insert_signal(_sinal_v1(alert_ts=1_000 + 2_000.0))   # atraso 2000s > 1800s (1h/2)
        linhas = aud.executar(self.storage.paths.db)
        self.assertTrue(any(f"V1: 1 ENTRADA" in l for l in linhas), linhas)
        sinal = self.storage.pr1_signal(sid)
        self.assertIn("entrada_atrasada", json.loads(sinal["tags"]))
        self.assertAlmostEqual(sinal["atraso_candles"], 2_000.0 / H)

    def test_a_signal_alerted_within_the_threshold_is_never_tagged_but_atraso_candles_is_still_filled(self) -> None:
        sid = self.storage.pr1_insert_signal(_sinal_v1(alert_ts=1_000 + 100.0))   # atraso 100s < 1800s
        aud.executar(self.storage.paths.db)
        sinal = self.storage.pr1_signal(sid)
        self.assertNotIn("entrada_atrasada", json.loads(sinal["tags"]))
        self.assertAlmostEqual(sinal["atraso_candles"], 100.0 / H)

    def test_falls_back_to_ts_alerta_when_alert_ts_is_missing(self) -> None:
        sid = self.storage.pr1_insert_signal(_sinal_v1(ts_alerta=1_000 + 5_000.0))
        aud.executar(self.storage.paths.db)
        sinal = self.storage.pr1_signal(sid)
        self.assertIn("entrada_atrasada", json.loads(sinal["tags"]))

    def test_a_signal_never_alerted_is_sem_dado_never_tagged_never_estimated(self) -> None:
        sid = self.storage.pr1_insert_signal(_sinal_v1())
        linhas = aud.executar(self.storage.paths.db)
        self.assertTrue(any("sem_dado (nunca alertado): 1" in l for l in linhas), linhas)
        sinal = self.storage.pr1_signal(sid)
        self.assertEqual(json.loads(sinal["tags"]), [])
        self.assertIsNone(sinal["atraso_candles"])

    def test_already_tagged_and_filled_signals_are_never_touched_again(self) -> None:
        sid = self.storage.pr1_insert_signal(_sinal_v1(alert_ts=1_000 + 2_000.0, atraso_candles=99.0,
                                                       tags='["entrada_atrasada"]'))
        aud.executar(self.storage.paths.db)
        sinal = self.storage.pr1_signal(sid)
        self.assertEqual(json.loads(sinal["tags"]), ["entrada_atrasada"])
        self.assertEqual(sinal["atraso_candles"], 99.0, "nunca sobrescreve um valor ja gravado ao vivo")

    def test_running_twice_never_duplicates_the_tag(self) -> None:
        self.storage.pr1_insert_signal(_sinal_v1(alert_ts=1_000 + 2_000.0))
        aud.executar(self.storage.paths.db)
        aud.executar(self.storage.paths.db)
        sinal = self.storage.pr1_signals()[0]
        self.assertEqual(json.loads(sinal["tags"]), ["entrada_atrasada"])

    def test_v2_signals_are_audited_the_same_way(self) -> None:
        sid = self.storage.pr2_insert_signal({
            "chain": "solana", "pool": "POOL1", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "MINT1", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v2": "def456", "gatilho": "[]", "tags": "[]",
            "janela_ouro": "janela_ouro", "hora_brt": "09:00", "status": "fechado",
            "entry_price": 100.0, "stop": 80.0, "alert_ts": 1_000 + 2_000.0,
        })
        aud.executar(self.storage.paths.db)
        sinal = self.storage.pr2_signal(sid)
        self.assertIn("entrada_atrasada", json.loads(sinal["tags"]))

    def test_backs_up_the_database_before_writing_anything(self) -> None:
        self.storage.pr1_insert_signal(_sinal_v1(alert_ts=1_000 + 2_000.0))
        linhas = aud.executar(self.storage.paths.db)
        backup_path = Path(linhas[0].split("backup: ")[1])
        self.assertTrue(backup_path.exists())


if __name__ == "__main__":
    unittest.main()
