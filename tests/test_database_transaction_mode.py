import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database


class DatabaseTransactionModeTests(unittest.TestCase):
    def test_connection_uses_immediate_and_keeps_selects_transaction_free(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection-mode.db"
            with sqlite3.connect(path) as raw:
                raw.execute("CREATE TABLE probe(id INTEGER PRIMARY KEY, value TEXT)")

            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with database.connection() as conn:
                    self.assertEqual(conn.isolation_level, "IMMEDIATE")
                    self.assertFalse(conn.in_transaction)
                    conn.execute("SELECT COUNT(*) FROM probe").fetchone()
                    self.assertFalse(conn.in_transaction)
                    conn.execute("INSERT INTO probe(value) VALUES ('ok')")
                    self.assertTrue(conn.in_transaction)
                    busy_timeout_ms = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

            self.assertEqual(busy_timeout_ms, 10_000)
            with sqlite3.connect(path) as raw:
                self.assertEqual(raw.execute("SELECT COUNT(*) FROM probe").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
