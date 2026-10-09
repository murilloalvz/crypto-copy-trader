from __future__ import annotations

from dataclasses import replace
import unittest

from benchmarks.social_event_first_v0.snapshot import build_social_event_snapshot_v0
from src.social_event_evidence_v0 import social_event_evidence_from_mapping_v0


class SocialEventSnapshotV0Tests(unittest.TestCase):
    def _item(self, event_id: str, **overrides):
        row = {
            "source_kind": "social_post",
            "source_key": "source:alpha",
            "source_event_id": event_id,
            "event_kind": "mention",
            "observed_wall_ns": 1_100,
            "published_at_ns": 1_000,
            "actor_key": "actor-a",
            "token_mint": "TOKEN",
            "token_mapping_observed_wall_ns": 1_100,
        }
        row.update(overrides)
        return social_event_evidence_from_mapping_v0(row)

    def test_mapping_after_cutoff_prevents_backdated_inclusion(self):
        item = self._item(
            "late-map",
            observed_wall_ns=1_050,
            published_at_ns=900,
            token_mapping_observed_wall_ns=1_600,
        )
        snapshot = build_social_event_snapshot_v0(
            evidence=[item], token_mint="TOKEN", lookback_start_wall_ns=500,
            market_anchor_wall_ns=1_000, decision_cutoff_wall_ns=1_500,
        )
        self.assertEqual(snapshot["features"]["observed_event_count"], 0)

    def test_source_observed_after_cutoff_is_excluded_even_if_published_earlier(self):
        item = self._item(
            "late-source",
            observed_wall_ns=1_600,
            published_at_ns=700,
            token_mapping_observed_wall_ns=1_600,
        )
        snapshot = build_social_event_snapshot_v0(
            evidence=[item], token_mint="TOKEN", lookback_start_wall_ns=500,
            market_anchor_wall_ns=1_000, decision_cutoff_wall_ns=1_500,
        )
        self.assertEqual(snapshot["features"]["observed_event_count"], 0)

    def test_publication_timestamp_never_replaces_causal_observation_clock(self):
        item = self._item(
            "future-published-metadata",
            observed_wall_ns=1_100,
            published_at_ns=9_999,
            token_mapping_observed_wall_ns=1_100,
        )
        snapshot = build_social_event_snapshot_v0(
            evidence=[item], token_mint="TOKEN", lookback_start_wall_ns=500,
            market_anchor_wall_ns=1_000, decision_cutoff_wall_ns=1_500,
        )
        self.assertEqual(snapshot["features"]["observed_event_count"], 1)
        self.assertTrue(snapshot["guardrails"]["published_at_is_metadata_not_causal_clock"])

    def test_token_and_lookback_filters_are_exact(self):
        included = self._item("included", observed_wall_ns=1_100, token_mapping_observed_wall_ns=1_100)
        wrong_token = self._item("wrong", token_mint="OTHER", observed_wall_ns=1_100, token_mapping_observed_wall_ns=1_100)
        too_old = self._item("old", observed_wall_ns=400, token_mapping_observed_wall_ns=400)
        snapshot = build_social_event_snapshot_v0(
            evidence=[included, wrong_token, too_old], token_mint="TOKEN", lookback_start_wall_ns=500,
            market_anchor_wall_ns=1_000, decision_cutoff_wall_ns=1_500,
        )
        self.assertEqual(snapshot["features"]["observed_event_count"], 1)
        self.assertEqual(snapshot["evidence_keys"], [included.evidence_key])

    def test_conflicting_duplicate_evidence_key_is_rejected(self):
        item = self._item("dup")
        conflicting = replace(item, actor_key="different")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            build_social_event_snapshot_v0(
                evidence=[item, conflicting], token_mint="TOKEN", lookback_start_wall_ns=500,
                market_anchor_wall_ns=1_000, decision_cutoff_wall_ns=1_500,
            )

    def test_snapshot_reports_source_actor_and_anchor_features(self):
        pre = self._item(
            "pre", source_key="source:one", actor_key="a", observed_wall_ns=900,
            token_mapping_observed_wall_ns=900,
        )
        post_a = self._item(
            "post-a", source_key="source:one", actor_key="a", observed_wall_ns=1_100,
            token_mapping_observed_wall_ns=1_100,
        )
        post_b = self._item(
            "post-b", source_key="source:two", actor_key="b", observed_wall_ns=1_200,
            token_mapping_observed_wall_ns=1_200,
        )
        snapshot = build_social_event_snapshot_v0(
            evidence=[pre, post_a, post_b], token_mint="TOKEN", lookback_start_wall_ns=500,
            market_anchor_wall_ns=1_000, decision_cutoff_wall_ns=1_500,
        )
        features = snapshot["features"]
        self.assertEqual(features["observed_event_count"], 3)
        self.assertEqual(features["unique_source_count"], 2)
        self.assertEqual(features["unique_actor_count"], 2)
        self.assertEqual(features["pre_anchor_event_count"], 1)
        self.assertEqual(features["post_anchor_event_count"], 2)
        self.assertAlmostEqual(features["top_source_event_share_pct"], 200.0 / 3.0)
        self.assertEqual(features["actor_identity_coverage_pct"], 100.0)
        self.assertEqual(features["first_available_delay_ms_from_anchor"], -0.0001)


if __name__ == "__main__":
    unittest.main()
