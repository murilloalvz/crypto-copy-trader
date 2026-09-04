import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import unified_market_latency_smoke_v13 as v13


class UnifiedMarketLatencySmokeV13Tests(unittest.TestCase):
    def test_enable_wal_mode_preserves_synchronous_policy(self):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        path = handle.name
        handle.close()

        @contextmanager
        def temp_connection():
            conn = sqlite3.connect(path)
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

        try:
            with sqlite3.connect(path) as conn:
                before_sync = int(conn.execute("PRAGMA synchronous").fetchone()[0])

            with patch.object(v13, "connection", temp_connection):
                mode, synchronous = v13._enable_wal_mode()

            self.assertEqual(mode, "wal")
            self.assertEqual(synchronous, before_sync)

            with sqlite3.connect(path) as conn:
                persisted_mode = str(
                    conn.execute("PRAGMA journal_mode").fetchone()[0]
                ).lower()
            self.assertEqual(persisted_mode, "wal")
        finally:
            for candidate in (path, f"{path}-wal", f"{path}-shm"):
                try:
                    os.remove(candidate)
                except FileNotFoundError:
                    pass


if __name__ == "__main__":
    unittest.main()
