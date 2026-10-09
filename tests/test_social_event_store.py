import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.social_event_store import load_social_events, record_social_event_snapshot
from src.social_intelligence import SocialEvent


class SocialEventStoreTests(unittest.TestCase):
    def test_keeps_multiple_observed_snapshots_without_duplicate_same_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "social.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = SocialEvent(
                    "x", "post-1", "alice", 100, 120,
                    token_mint="T", like_count=2,
                )
                later = SocialEvent(
                    "x", "post-1", "alice", 100, 180,
                    token_mint="T", like_count=20,
                )

                self.assertTrue(record_social_event_snapshot(first))
                self.assertFalse(record_social_event_snapshot(first))
                self.assertTrue(record_social_event_snapshot(later))
                early = load_social_events(token_mint="T", as_of=150)
                all_rows = load_social_events(token_mint="T")

        self.assertEqual(len(early), 1)
        self.assertEqual(early[0].like_count, 2)
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(all_rows[-1].like_count, 20)

    def test_symbol_lookup_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "social.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_social_event_snapshot(
                    SocialEvent("x", "p", "a", 100, 120, symbol="Bonk")
                )
                result = load_social_events(symbol="bonk")

        self.assertEqual(len(result), 1)

    def test_rejects_invalid_time_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "social.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    record_social_event_snapshot(
                        SocialEvent("x", "bad", "a", 200, 100, token_mint="T")
                    )


if __name__ == "__main__":
    unittest.main()
