import unittest

from src.social_intelligence import SocialEvent, build_social_context, causal_event_snapshots


class SocialIntelligenceTests(unittest.TestCase):
    def test_future_observation_is_excluded_even_if_post_was_created_earlier(self):
        events = [
            SocialEvent(
                source="x",
                event_id="1",
                author_id="alice",
                created_at=100,
                observed_at=500,
                token_mint="TOKEN",
            )
        ]

        before = causal_event_snapshots(events, as_of=400, token_mint="TOKEN")
        after = causal_event_snapshots(events, as_of=500, token_mint="TOKEN")

        self.assertEqual(before, [])
        self.assertEqual(len(after), 1)

    def test_later_engagement_snapshot_does_not_leak_into_earlier_context(self):
        events = [
            SocialEvent(
                source="x",
                event_id="1",
                author_id="alice",
                created_at=100,
                observed_at=120,
                token_mint="TOKEN",
                like_count=5,
            ),
            SocialEvent(
                source="x",
                event_id="1",
                author_id="alice",
                created_at=100,
                observed_at=180,
                token_mint="TOKEN",
                like_count=50,
            ),
        ]

        early = build_social_context(
            events,
            as_of=150,
            token_mint="TOKEN",
            windows=(300,),
        )
        later = build_social_context(
            events,
            as_of=200,
            token_mint="TOKEN",
            windows=(300,),
        )

        self.assertEqual(early.windows[300].like_count, 5)
        self.assertEqual(later.windows[300].like_count, 50)
        self.assertEqual(later.windows[300].event_count, 1)

    def test_counts_mentions_and_unique_authors_in_causal_windows(self):
        events = [
            SocialEvent("x", "1", "alice", 800, 810, token_mint="TOKEN"),
            SocialEvent("x", "2", "alice", 880, 890, token_mint="TOKEN"),
            SocialEvent("x", "3", "bob", 940, 950, token_mint="TOKEN"),
            SocialEvent("x", "4", "carol", 100, 200, token_mint="OTHER"),
        ]

        context = build_social_context(
            events,
            as_of=1_000,
            token_mint="TOKEN",
            windows=(120, 300),
        )

        self.assertEqual(context.windows[120].event_count, 2)
        self.assertEqual(context.windows[120].unique_author_count, 2)
        self.assertEqual(context.windows[300].event_count, 3)
        self.assertEqual(context.windows[300].unique_author_count, 2)

    def test_requires_token_identity_for_context(self):
        with self.assertRaises(ValueError):
            build_social_context([], as_of=100)

    def test_rejects_impossible_observation_timestamp(self):
        events = [
            SocialEvent(
                source="x",
                event_id="bad",
                author_id="alice",
                created_at=200,
                observed_at=100,
                token_mint="TOKEN",
            )
        ]

        with self.assertRaises(ValueError):
            causal_event_snapshots(events, as_of=300, token_mint="TOKEN")


if __name__ == "__main__":
    unittest.main()
