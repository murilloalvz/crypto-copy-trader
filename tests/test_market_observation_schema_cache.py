import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src import market_observation_store as store


class MarketObservationSchemaCacheTests(unittest.TestCase):
    def setUp(self):
        with store._SCHEMA_READY_LOCK:
            store._SCHEMA_READY_PATHS.clear()

    def test_cache_is_scoped_by_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.db"
            second = Path(directory) / "second.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=first)):
                store.ensure_market_observation_schema()
                store.ensure_market_observation_schema()
                self.assertTrue(first.exists())
            with patch.object(database, "settings", SimpleNamespace(database_path=second)):
                store.ensure_market_observation_schema()
                self.assertTrue(second.exists())
                with database.connection() as conn:
                    names = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                self.assertIn("market_trade_observations", names)
                self.assertIn("market_lifecycle_observations", names)

    def test_concurrent_first_use_initializes_once_without_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            errors = []
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                def initialize():
                    try:
                        store.ensure_market_observation_schema()
                    except Exception as exc:  # pragma: no cover - assertion path
                        errors.append(exc)

                threads = [threading.Thread(target=initialize) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

                self.assertEqual(errors, [])
                self.assertEqual(len(store._SCHEMA_READY_PATHS), 1)


if __name__ == "__main__":
    unittest.main()
