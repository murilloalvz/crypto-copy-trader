import unittest

from src.social_event_evidence_v0 import (
    ATTRIBUTION_LINK_RESOLVED,
    ATTRIBUTION_MINT_DIRECT,
    ATTRIBUTION_SYMBOL_ONLY_AMBIGUOUS,
    SocialEventObservationV0,
    build_social_event_evidence_snapshot_v0,
)


class SocialEventEvidenceV0Tests(unittest.TestCase):
    def test_local_observed_at_is_the_causal_gate_not_source_created_at(self):
        rows = [
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=90,
                evidence_key="seen-now",
                source="social-a",
                source_event_id="1",
                event_type="post",
                attribution_kind=ATTRIBUTION_MINT_DIRECT,
                source_created_at=120,
                author_id="alice",
            ),
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=110,
                evidence_key="seen-later",
                source="social-a",
                source_event_id="2",
                event_type="post",
                attribution_kind=ATTRIBUTION_MINT_DIRECT,
                source_created_at=50,
                author_id="bob",
            ),
        ]
        snapshot = build_social_event_evidence_snapshot_v0(
            token_mint="MINT",
            as_of=100,
            window_seconds=60,
            observations=rows,
        )
        self.assertEqual(snapshot.attributed_event_count, 1)
        self.assertEqual(snapshot.provenance_keys, ("seen-now",))
        self.assertIn(
            "source_created_at_after_local_observation_clock",
            snapshot.data_quality_flags,
        )

    def test_duplicate_source_event_uses_first_local_sighting_once(self):
        rows = [
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=80,
                evidence_key="first",
                source="news",
                source_event_id="same",
                event_type="article",
                attribution_kind=ATTRIBUTION_LINK_RESOLVED,
            ),
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=90,
                evidence_key="repeat",
                source="news",
                source_event_id="same",
                event_type="article",
                attribution_kind=ATTRIBUTION_LINK_RESOLVED,
            ),
        ]
        snapshot = build_social_event_evidence_snapshot_v0(
            token_mint="MINT", as_of=100, observations=rows
        )
        self.assertEqual(snapshot.deduped_event_count, 1)
        self.assertEqual(snapshot.attributed_event_count, 1)
        self.assertEqual(snapshot.first_observed_at, 80)
        self.assertEqual(snapshot.provenance_keys, ("first",))

    def test_symbol_only_attribution_is_preserved_but_not_counted_as_strong_evidence(self):
        rows = [
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=95,
                evidence_key="ambiguous",
                source="social-a",
                source_event_id="x",
                event_type="mention",
                attribution_kind=ATTRIBUTION_SYMBOL_ONLY_AMBIGUOUS,
                author_id="alice",
            )
        ]
        snapshot = build_social_event_evidence_snapshot_v0(
            token_mint="MINT", as_of=100, observations=rows
        )
        self.assertEqual(snapshot.deduped_event_count, 1)
        self.assertEqual(snapshot.attributed_event_count, 0)
        self.assertEqual(snapshot.ambiguous_event_count, 1)
        self.assertEqual(snapshot.unique_author_count, 0)
        self.assertIn(
            "ambiguous_symbol_only_attribution_present",
            snapshot.data_quality_flags,
        )

    def test_window_uses_local_observation_clock(self):
        rows = [
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=40,
                evidence_key="old",
                source="social-a",
                source_event_id="old",
                event_type="post",
                attribution_kind=ATTRIBUTION_MINT_DIRECT,
            ),
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=80,
                evidence_key="new",
                source="social-b",
                source_event_id="new",
                event_type="post",
                attribution_kind=ATTRIBUTION_MINT_DIRECT,
            ),
        ]
        snapshot = build_social_event_evidence_snapshot_v0(
            token_mint="MINT", as_of=100, window_seconds=30, observations=rows
        )
        self.assertEqual(snapshot.attributed_event_count, 1)
        self.assertEqual(snapshot.source_counts, (("social-b", 1),))

    def test_counts_are_score_free_and_source_separated(self):
        rows = [
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=90,
                evidence_key="a",
                source="social-a",
                source_event_id="1",
                event_type="post",
                attribution_kind=ATTRIBUTION_MINT_DIRECT,
                author_id="alice",
            ),
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=91,
                evidence_key="b",
                source="news-b",
                source_event_id="2",
                event_type="article",
                attribution_kind=ATTRIBUTION_LINK_RESOLVED,
                author_id="bob",
            ),
        ]
        snapshot = build_social_event_evidence_snapshot_v0(
            token_mint="MINT", as_of=100, observations=rows
        )
        self.assertEqual(snapshot.attributed_event_count, 2)
        self.assertEqual(snapshot.unique_author_count, 2)
        self.assertEqual(snapshot.source_counts, (("news-b", 1), ("social-a", 1)))
        self.assertEqual(snapshot.event_type_counts, (("article", 1), ("post", 1)))
        self.assertFalse(hasattr(snapshot, "sentiment"))
        self.assertFalse(hasattr(snapshot, "score"))
        self.assertFalse(hasattr(snapshot, "recommendation"))

    def test_invalid_attribution_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            SocialEventObservationV0(
                token_mint="MINT",
                observed_at=1,
                evidence_key="e",
                source="social-a",
                source_event_id="1",
                event_type="post",
                attribution_kind="SYMBOL_MAGIC_GUESS",
            )


if __name__ == "__main__":
    unittest.main()
