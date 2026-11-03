"""PEDIDO ADICIONAL FASE 6, item 1: backup diario do estado.sqlite (API de backup nativa do SQLite,
agendamento 1x/intervalo e retencao configuravel)."""

from __future__ import annotations

import sqlite3
import time
import unittest

from .. import backup
from .helpers import Env


class BackupToTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()

    def tearDown(self) -> None:
        self.env.close()

    def test_backup_to_produces_a_fully_readable_copy(self) -> None:
        self.env.storage.set_meta("prova", "123")
        dest = self.env.paths.base / "backups" / "copia.sqlite"
        self.env.storage.backup_to(dest)
        self.assertTrue(dest.exists())
        conn = sqlite3.connect(str(dest))
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='prova'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "123")

    def test_backup_to_never_touches_the_live_database(self) -> None:
        self.env.storage.set_meta("antes", "1")
        dest = self.env.paths.base / "backups" / "copia.sqlite"
        self.env.storage.backup_to(dest)
        self.env.storage.set_meta("depois", "2")   # escrita APOS o backup: so pode aparecer no banco vivo
        self.assertEqual(self.env.storage.get_meta("depois"), "2")
        conn = sqlite3.connect(str(dest))
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='depois'").fetchone()
        finally:
            conn.close()
        self.assertIsNone(row, "o backup e uma copia PARADA no instante em que foi tirado")


class RunBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()

    def tearDown(self) -> None:
        self.env.close()

    def test_run_backup_writes_a_timestamped_file(self) -> None:
        now = 1_700_000_000.0
        dest = backup.run_backup(self.env.storage, self.env.paths.base / "backups", now)
        self.assertTrue(dest.exists())
        self.assertIn("estado-", dest.name)
        self.assertTrue(dest.name.endswith(".sqlite"))

    def test_run_backup_deletes_files_older_than_the_retention_window(self) -> None:
        backups_dir = self.env.paths.base / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        now = 1_700_000_000.0
        old = backups_dir / "estado-20200101T000000Z.sqlite"
        old.write_bytes(b"velho")
        old_mtime = now - 30 * 86400.0
        import os as _os
        _os.utime(old, (old_mtime, old_mtime))
        backup.run_backup(self.env.storage, backups_dir, now, retencao_dias=7)
        self.assertFalse(old.exists(), "backup mais velho que a retencao tem que ser apagado")

    def test_run_backup_keeps_files_within_the_retention_window(self) -> None:
        backups_dir = self.env.paths.base / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        now = 1_700_000_000.0
        recent = backups_dir / "estado-20261020T000000Z.sqlite"
        recent.write_bytes(b"recente")
        recent_mtime = now - 2 * 86400.0
        import os as _os
        _os.utime(recent, (recent_mtime, recent_mtime))
        backup.run_backup(self.env.storage, backups_dir, now, retencao_dias=7)
        self.assertTrue(recent.exists(), "backup dentro da retencao nunca pode ser apagado")


class MaybeRunBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()

    def tearDown(self) -> None:
        self.env.close()

    def test_first_call_always_backs_up(self) -> None:
        backups_dir = self.env.paths.base / "backups"
        dest = backup.maybe_run_backup(self.env.storage, backups_dir, 1_700_000_000.0, intervalo_s=86400.0)
        self.assertIsNotNone(dest)
        self.assertTrue(dest.exists())

    def test_a_second_call_soon_after_is_a_no_op(self) -> None:
        backups_dir = self.env.paths.base / "backups"
        backup.maybe_run_backup(self.env.storage, backups_dir, 1_700_000_000.0, intervalo_s=86400.0)
        n_files_before = len(list(backups_dir.glob("estado-*.sqlite")))
        dest = backup.maybe_run_backup(self.env.storage, backups_dir, 1_700_000_100.0, intervalo_s=86400.0)
        self.assertIsNone(dest)
        self.assertEqual(len(list(backups_dir.glob("estado-*.sqlite"))), n_files_before)

    def test_a_call_after_the_interval_backs_up_again(self) -> None:
        backups_dir = self.env.paths.base / "backups"
        backup.maybe_run_backup(self.env.storage, backups_dir, 1_700_000_000.0, intervalo_s=100.0)
        dest = backup.maybe_run_backup(self.env.storage, backups_dir, 1_700_000_200.0, intervalo_s=100.0)
        self.assertIsNotNone(dest)


if __name__ == "__main__":
    unittest.main()
