import unittest

from src.social_features import build_social_burst_features
from src.social_intelligence import SocialEvent


class SocialBurstFeatureTests(unittest.TestCase):
    def test_compares_current_rate_with_non_overlapping_prior_baseline(self):
        events = [
            SocialEvent("x", "old-1", "a", 100, 100, token_mint="T"),
            SocialEvent("x", "old-2", "b", 200, 200, token_mint="T"),
            SocialEvent("x", "new-1", "c", 3_800, 3_800, token_mint="T"),
            SocialEvent("x", "new-2", "d", 3_850, 3_850, token_mint="T"),
            SocialEvent("x", "new-3", "e", 3_900, 3_900, token_mint="T"),
        ]

        result = build_social_burst_features(
            events,
            as_of=4_000,
            token_mint="T",
            current_window_seconds=300,
            baseline_window_seconds=3_600,
        )

        self.assertEqual(result.current_event_count, 3)
        self.assertEqual(result.prior_baseline_event_count, 2)
        self.assertAlmostEqual(result.current_event_rate_per_minute, 0.6)
        self.assertAlmostEqual(result.prior_baseline_event_rate_per_minute, 2 / 55)
        self.assertGreater(result.event_rate_acceleration_ratio, 10)
        self.assertEqual(result.current_author_diversity_pct, 100.0)

    def test_later_engagement_refresh_does_not_create_false_current_burst(self):
        events = [
            SocialEvent(
                "x", "old", "a", 100, 120, token_mint="T", like_count=1
            ),
            SocialEvent(
                "x", "old", "a", 100, 3_990, token_mint="T", like_count=500
            ),
            SocialEvent(
                "x", "new", "b", 3_900, 3_910, token_mint="T", like_count=3
            ),
        ]

        result = build_social_burst_features(events, as_of=4_000, token_mint="T")

        self.assertEqual(result.current_event_count, 1)
        self.assertEqual(result.current_total_engagement, 3)

    def test_zero_prior_rate_stays_unknown_instead_of_infinite(self):
        result = build_social_burst_features(
            [SocialEvent("x", "new", "a", 950, 960, token_mint="T")],
            as_of=1_000,
            token_mint="T",
        )

        self.assertEqual(result.prior_baseline_event_count, 0)
        self.assertIsNone(result.event_rate_acceleration_ratio)

    def test_rejects_overlapping_baseline_definition(self):
        with self.assertRaises(ValueError):
            build_social_burst_features(
                [],
                as_of=1_000,
                token_mint="T",
                current_window_seconds=300,
                baseline_window_seconds=300,
            )


if __name__ == "__main__":
    unittest.main()
