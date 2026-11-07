import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from social_ingest import load_jsonl, main


class SocialIngestCliTests(unittest.TestCase):
    def test_load_jsonl_builds_social_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "source": "x",
                        "event_id": "1",
                        "author_id": "alice",
                        "created_at": 100,
                        "observed_at": 120,
                        "token_mint": "T",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            events = load_jsonl(path)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "1")
        self.assertEqual(events[0].token_mint, "T")

    def test_dry_run_validates_without_persisting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "source": "x",
                        "event_id": "1",
                        "author_id": "alice",
                        "created_at": 100,
                        "observed_at": 120,
                        "symbol": "BONK",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                patch("social_ingest.initialize_database") as initialize,
                patch("social_ingest.record_social_event_snapshot") as record,
                redirect_stdout(output),
            ):
                exit_code = main([str(path), "--dry-run"])

        self.assertEqual(exit_code, 0)
        initialize.assert_not_called()
        record.assert_not_called()
        self.assertIn("JSONL válido: 1 snapshot", output.getvalue())

    def test_invalid_json_reports_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("{invalid}\n", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                exit_code = main([str(path), "--dry-run"])

        self.assertEqual(exit_code, 2)
        self.assertIn("linha 1 inválida", errors.getvalue())

    def test_persistence_counts_inserted_and_duplicate_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = [
                {
                    "source": "x",
                    "event_id": "1",
                    "author_id": "alice",
                    "created_at": 100,
                    "observed_at": 120,
                    "token_mint": "T",
                },
                {
                    "source": "x",
                    "event_id": "1",
                    "author_id": "alice",
                    "created_at": 100,
                    "observed_at": 120,
                    "token_mint": "T",
                },
            ]
            path.write_text(
                "\n".join(json.dumps(item) for item in rows) + "\n",
                encoding="utf-8",
            )
            recorder = Mock(side_effect=[True, False])
            output = io.StringIO()
            with (
                patch("social_ingest.initialize_database"),
                patch("social_ingest.record_social_event_snapshot", recorder),
                redirect_stdout(output),
            ):
                exit_code = main([str(path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(recorder.call_count, 2)
        self.assertIn("inseridos: 1", output.getvalue())
        self.assertIn("duplicados: 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
