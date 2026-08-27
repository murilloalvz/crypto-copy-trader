import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import social as social_cli
from src import database
from src.database import initialize_database, rows
from src.social.models import SocialEvent
from src.social.parser import SocialEventType, parse_social_event
from src.social.service import backfill_social_event_parsing, collect_social_events
from src.social.x_api import XApiError, XRecentSearchClient, normalize_usernames


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FixedClient:
    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error

    def fetch(self, _usernames, *, lookback_minutes=None):
        self.lookback_minutes = lookback_minutes
        if self.error:
            raise self.error
        return list(self.events)


class SocialEventTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "social.db"
        self.settings_patch = patch.object(
            database, "settings", SimpleNamespace(database_path=self.path)
        )
        self.settings_patch.start()
        initialize_database()

    def tearDown(self):
        self.settings_patch.stop()
        self.directory.cleanup()

    def test_official_x_payload_is_normalized_with_detection_latency(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "data": [
                        {
                            "id": "1900000000000000001",
                            "author_id": "42",
                            "created_at": "2026-08-27T11:59:00.000Z",
                            "text": "Public event with a contract later",
                        }
                    ],
                    "includes": {"users": [{"id": "42", "username": "ExampleDev"}]},
                }
            )

        clock = iter((1_787_832_000.0, 1_787_832_000.5))
        client = XRecentSearchClient(
            "test-bearer",
            timeout_seconds=7,
            now=lambda: next(clock),
            opener=opener,
        )
        events = client.fetch(["@ExampleDev", "exampledev"], lookback_minutes=15)

        self.assertEqual(normalize_usernames(["@ExampleDev", "exampledev"]), ("ExampleDev",))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].author_username, "ExampleDev")
        self.assertEqual(events[0].published_at_ms, 1_787_831_940_000)
        self.assertEqual(events[0].detected_at_ms, 1_787_832_000_500)
        self.assertEqual(events[0].detection_latency_ms, 60_500)
        self.assertEqual(captured["timeout"], 7)
        request = captured["request"]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["query"], ["(from:ExampleDev) -is:retweet"])
        self.assertEqual(request.get_header("Authorization"), "Bearer test-bearer")

    def test_event_is_persisted_once_and_duplicate_is_ignored(self):
        event = SocialEvent(
            source="x",
            external_event_id="event-1",
            author_source_id="author-1",
            author_username="ExampleDev",
            published_at_ms=1_000,
            detected_at_ms=1_250,
            text="hello",
            url="https://x.com/ExampleDev/status/event-1",
            raw_json='{"id":"event-1"}',
        )
        client = FixedClient([event])

        first = collect_social_events(client, ["ExampleDev"], lookback_minutes=5)
        second = collect_social_events(client, ["ExampleDev"], lookback_minutes=5)
        stored = rows("SELECT * FROM social_events")
        account = rows("SELECT * FROM social_accounts")[0]

        self.assertEqual(first.inserted_events, 1)
        self.assertEqual(second.inserted_events, 0)
        self.assertEqual(second.duplicate_events, 1)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["detection_latency_ms"], 250)
        self.assertEqual(stored[0]["event_type"], "GENERAL_POST")
        self.assertEqual(account["tier"], "A")
        self.assertEqual(account["source_account_id"], "author-1")

    def test_source_failure_does_not_create_partial_event(self):
        client = FixedClient(error=XApiError("temporary failure"))

        with self.assertRaisesRegex(XApiError, "temporary"):
            collect_social_events(client, ["ExampleDev"])

        self.assertEqual(rows("SELECT COUNT(*) AS total FROM social_events")[0]["total"], 0)

    def test_removed_tier_a_account_is_disabled_by_current_configuration(self):
        collect_social_events(FixedClient([]), ["OldAccount"])
        collect_social_events(FixedClient([]), ["ExampleDev"])

        accounts = {
            item["username"]: item["enabled"]
            for item in rows("SELECT username, enabled FROM social_accounts")
        }

        self.assertEqual(accounts, {"OldAccount": 0, "ExampleDev": 1})

    def test_network_failure_is_wrapped_without_leaking_credentials(self):
        def opener(_request, timeout):
            raise URLError("offline")

        client = XRecentSearchClient("secret-token", opener=opener)
        with self.assertRaises(XApiError) as raised:
            client.fetch(["ExampleDev"])

        self.assertNotIn("secret-token", str(raised.exception))

    def test_cli_is_read_only_and_reports_inserted_events(self):
        event = SocialEvent(
            source="x",
            external_event_id="event-cli",
            author_source_id="author-cli",
            author_username="ExampleDev",
            published_at_ms=1_000,
            detected_at_ms=1_500,
            text="event for cli",
            url="https://x.com/ExampleDev/status/event-cli",
            raw_json='{"id":"event-cli"}',
        )
        output = io.StringIO()
        with (
            patch.object(
                social_cli,
                "settings",
                SimpleNamespace(social_tier_a_accounts=("ExampleDev",)),
            ),
            patch.object(
                social_cli,
                "XRecentSearchClient",
                return_value=FixedClient([event]),
            ),
            redirect_stdout(output),
        ):
            exit_code = social_cli.main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("READ ONLY", output.getvalue())
        self.assertIn("novos: 1", output.getvalue())
        self.assertIn("GENERAL_POST", output.getvalue())

    def test_parser_extracts_candidates_without_claiming_token_identity(self):
        mint = "Hxv4Pxyb6PYcxGy6S4zRuJtN2i8BhBkpoejG3xxrVKcv"
        raw_json = json.dumps(
            {
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/short",
                            "expanded_url": "https://project.example/launch",
                        }
                    ]
                }
            }
        )

        parsed = parse_social_event(
            f"We are launching $WAVE today. Mint: {mint} #Solana https://t.co/short",
            raw_json,
        )

        self.assertEqual(parsed.event_type, SocialEventType.LAUNCH)
        self.assertEqual(parsed.tickers, ("WAVE",))
        self.assertEqual(parsed.mint_candidates, (mint,))
        self.assertEqual(parsed.hashtags, ("solana",))
        self.assertEqual(
            parsed.urls,
            ("https://t.co/short", "https://project.example/launch"),
        )

    def test_parser_prioritizes_listing_and_ignores_dollar_amounts(self):
        parsed = parse_social_event("Now listed: spot fees start at $100")

        self.assertEqual(parsed.event_type, SocialEventType.LISTING)
        self.assertEqual(parsed.tickers, ())

    def test_parser_distinguishes_empty_plain_and_mint_posts(self):
        mint = "Db59KG1wviw47Sz5Fi3opVpM8rXE2VFwTWtAEvLrVMdK"

        self.assertEqual(parse_social_event("").event_type, SocialEventType.UNKNOWN)
        self.assertEqual(
            parse_social_event("gm builders").event_type,
            SocialEventType.GENERAL_POST,
        )
        self.assertEqual(
            parse_social_event(mint).event_type,
            SocialEventType.TOKEN_MENTION,
        )

    def test_event_persists_deterministic_classification_and_entities(self):
        mint = "Db59KG1wviw47Sz5Fi3opVpM8rXE2VFwTWtAEvLrVMdK"
        event = SocialEvent(
            source="x",
            external_event_id="event-parsed",
            author_source_id="author-1",
            author_username="ExampleDev",
            published_at_ms=1_000,
            detected_at_ms=1_250,
            text=f"Partnership for $HYPE {mint} #Solana",
            url="https://x.com/ExampleDev/status/event-parsed",
            raw_json='{"id":"event-parsed"}',
        )

        collect_social_events(FixedClient([event]), ["ExampleDev"])
        stored = rows("SELECT * FROM social_events")[0]

        self.assertEqual(stored["event_type"], "PARTNERSHIP")
        self.assertEqual(json.loads(stored["tickers_json"]), ["HYPE"])
        self.assertEqual(json.loads(stored["mint_candidates_json"]), [mint])
        self.assertEqual(json.loads(stored["hashtags_json"]), ["solana"])

    def test_backfill_classifies_event_1_rows_without_changing_raw_payload(self):
        raw_json = '{"id":"legacy-event"}'
        with database.connection() as conn:
            conn.execute(
                """INSERT INTO social_events
                (source, external_event_id, author_username, published_at_ms,
                 detected_at_ms, detection_latency_ms, text, url, event_type, raw_json)
                VALUES ('x', 'legacy-event', 'ExampleDev', 1000, 1250, 250,
                'We are announcing $WAVE', NULL, 'UNKNOWN', ?)""",
                (raw_json,),
            )

        self.assertEqual(backfill_social_event_parsing(), 1)
        stored = rows("SELECT * FROM social_events")[0]

        self.assertEqual(stored["event_type"], "PROJECT_ANNOUNCEMENT")
        self.assertEqual(json.loads(stored["tickers_json"]), ["WAVE"])
        self.assertEqual(stored["raw_json"], raw_json)
        self.assertEqual(backfill_social_event_parsing(), 0)


if __name__ == "__main__":
    unittest.main()
