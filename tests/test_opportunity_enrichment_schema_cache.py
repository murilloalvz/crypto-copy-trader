import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src import opportunity_enrichment_store as store


class OpportunityEnrichmentSchemaCacheTests(unittest.TestCase):
    def test_schema_setup_runs_once_per_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment-cache.db"
            cache_key = str(path.resolve())
            store._SCHEMA_READY_PATHS.discard(cache_key)
            calls = []
            original_connection = store.connection

            @contextmanager
            def counting_connection():
                calls.append(1)
                with original_connection() as conn:
                    yield conn

            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with patch.object(store, "connection", counting_connection):
                    store.ensure_opportunity_enrichment_schema()
                    store.ensure_opportunity_enrichment_schema()

            self.assertEqual(len(calls), 1)
            store._SCHEMA_READY_PATHS.discard(cache_key)


if __name__ == "__main__":
    unittest.main()
