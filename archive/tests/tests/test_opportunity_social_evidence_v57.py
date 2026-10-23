from __future__ import annotations

import unittest

from src.opportunity_social_evidence_v57 import build_opportunity_social_evidence_v57
from src.social_intelligence import SocialEvent


def event(
    *,
    event_id: str,
    created_at: int,
    observed_at: int,
    mint: str = "TOKEN",
    author: str = "author-1",
    likes: int = 0,
    original: bool = True,
) -> SocialEvent:
    return SocialEvent(
        source="synthetic",
        event_id=event_id,
        author_id=author,
        created_at=created_at,
        observed_at=observed_at,
        token_mint=mint,
        event_type="mention",
        is_original=original,
        like_count=likes,
    )


class OpportunitySocialEvidenceV57Tests(unittest.TestCase):
    def test_late_discovered_old_post_is_not_causal_before_observation(self):
        evidence = build_opportunity_social_evidence_v57(
            events=(event(event_id="p1", created_at=100, observed_at=200),),
            token_mint="TOKEN",
            as_of=150,
        )
        self.assertEqual(evidence.status, "NO_CAUSAL_EVENTS")
        self.assertEqual(evidence.causal_post_count, 0)

    def test_latest_known_engagement_snapshot_does_not_create_duplicate_post(self):
        evidence = build_opportunity_social_evidence_v57(
            events=(
                event(event_id="p1", created_at=100, observed_at=110, likes=1),
                event(event_id="p1", created_at=100, observed_at=120, likes=7),
            ),
            token_mint="TOKEN",
            as_of=130,
        )
        self.assertEqual(evidence.status, "AVAILABLE")
        self.assertEqual(evidence.causal_post_count, 1)
        self.assertEqual(evidence.current_event_count, 1)
        self.assertEqual(evidence.current_total_engagement, 7)

    def test_future_engagement_refresh_is_not_visible(self):
        evidence = build_opportunity_social_evidence_v57(
            events=(
                event(event_id="p1", created_at=100, observed_at=110, likes=1),
                event(event_id="p1", created_at=100, observed_at=140, likes=99),
            ),
            token_mint="TOKEN",
            as_of=130,
        )
        self.assertEqual(evidence.current_total_engagement, 1)

    def test_token_mint_join_does_not_mix_same_symbol_or_other_token(self):
        evidence = build_opportunity_social_evidence_v57(
            events=(
                event(event_id="p1", created_at=100, observed_at=110, mint="TOKEN"),
                event(event_id="p2", created_at=100, observed_at=111, mint="OTHER"),
            ),
            token_mint="TOKEN",
            as_of=130,
        )
        self.assertEqual(evidence.causal_post_count, 1)

    def test_zero_prior_baseline_is_explicit_not_infinite_acceleration(self):
        evidence = build_opportunity_social_evidence_v57(
            events=(event(event_id="p1", created_at=100, observed_at=110),),
            token_mint="TOKEN",
            as_of=130,
        )
        self.assertIsNone(evidence.event_rate_acceleration_ratio)
        self.assertIn("zero_prior_baseline_event_count", evidence.data_quality_flags)
        self.assertIn("social_acceleration_ratio_unavailable", evidence.data_quality_flags)

    def test_blank_token_mint_rejected(self):
        with self.assertRaisesRegex(ValueError, "token_mint"):
            build_opportunity_social_evidence_v57(events=(), token_mint=" ", as_of=1)


if __name__ == "__main__":
    unittest.main()
