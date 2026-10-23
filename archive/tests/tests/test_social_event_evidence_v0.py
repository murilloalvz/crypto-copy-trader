from __future__ import annotations

import unittest

from src.social_event_evidence_v0 import (
    make_social_event_evidence_key_v0,
    social_event_evidence_from_mapping_v0,
    social_event_evidence_to_dict_v0,
)


class SocialEventEvidenceV0Tests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "source_kind": "social_post",
            "source_key": "source:alice",
            "source_event_id": "post-123",
            "event_kind": "mention",
            "observed_wall_ns": 1_000,
            "published_at_ns": 900,
            "actor_key": "alice",
            "token_mint": "TOKEN",
            "token_mapping_observed_wall_ns": 1_200,
            "entity_keys": ["TOKEN", "alice", "TOKEN"],
            "content_fingerprint_sha256": "a" * 64,
        }
        row.update(overrides)
        return row

    def test_evidence_key_is_deterministic(self):
        first = make_social_event_evidence_key_v0(
            source_kind="social_post", source_key="source:alice", source_event_id="post-123"
        )
        second = make_social_event_evidence_key_v0(
            source_kind="social_post", source_key="source:alice", source_event_id="post-123"
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("sev0:"))

    def test_causal_available_clock_waits_for_token_mapping(self):
        item = social_event_evidence_from_mapping_v0(self._row())
        self.assertEqual(item.observed_wall_ns, 1_000)
        self.assertEqual(item.token_mapping_observed_wall_ns, 1_200)
        self.assertEqual(item.causal_available_wall_ns, 1_200)
        self.assertEqual(item.entity_keys, ("TOKEN", "alice"))

    def test_direct_token_specific_source_uses_ingress_as_mapping_clock(self):
        row = self._row(token_mapping_observed_wall_ns=None)
        item = social_event_evidence_from_mapping_v0(row)
        self.assertEqual(item.token_mapping_observed_wall_ns, item.observed_wall_ns)
        self.assertEqual(item.causal_available_wall_ns, item.observed_wall_ns)

    def test_wrong_supplied_evidence_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "evidence_key"):
            social_event_evidence_from_mapping_v0(self._row(evidence_key="sev0:wrong"))

    def test_nonpositive_observation_clock_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "observed_wall_ns"):
            social_event_evidence_from_mapping_v0(self._row(observed_wall_ns=0))

    def test_invalid_content_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "content_fingerprint"):
            social_event_evidence_from_mapping_v0(self._row(content_fingerprint_sha256="xyz"))

    def test_serialization_exposes_causal_available_clock(self):
        payload = social_event_evidence_to_dict_v0(social_event_evidence_from_mapping_v0(self._row()))
        self.assertEqual(payload["causal_available_wall_ns"], 1_200)
        self.assertEqual(payload["schema_version"], "social_event_evidence_v0")


if __name__ == "__main__":
    unittest.main()
