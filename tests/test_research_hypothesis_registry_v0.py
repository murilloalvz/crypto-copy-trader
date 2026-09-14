import unittest

from src.research_hypothesis_registry_v0 import (
    ResearchHypothesisRecordV0,
    STAGE_PREREGISTERED,
    STAGE_PROSPECTIVE_CLOSED,
    TRACK_CONVERGENCE,
    TRACK_MARKET_FIRST,
    TRACK_SOCIAL_EVENT_FIRST,
    VERDICT_REJECTED,
    VERDICT_SUPPORTED,
    research_hypothesis_registry_digest_v0,
    validate_research_hypothesis_registry_v0,
)

H1 = "1" * 64
H2 = "2" * 64


class ResearchHypothesisRegistryV0Tests(unittest.TestCase):
    def _closed(self, hypothesis_id, track, verdict, frozen_at):
        return ResearchHypothesisRecordV0(
            hypothesis_id=hypothesis_id,
            track=track,
            stage=STAGE_PROSPECTIVE_CLOSED,
            frozen_at=frozen_at,
            statement=f"{track} hypothesis",
            feature_contract_sha256=H1,
            outcome_contract_sha256=H2,
            outcomes_opened=True,
            evidence_verdict=verdict,
        )

    def test_convergence_requires_supported_independent_parents(self):
        market = self._closed("m1", TRACK_MARKET_FIRST, VERDICT_SUPPORTED, 100)
        social = self._closed("s1", TRACK_SOCIAL_EVENT_FIRST, VERDICT_SUPPORTED, 110)
        convergence = ResearchHypothesisRecordV0(
            hypothesis_id="c1",
            track=TRACK_CONVERGENCE,
            stage=STAGE_PREREGISTERED,
            frozen_at=120,
            statement="joint evidence hypothesis",
            feature_contract_sha256=H1,
            parent_hypothesis_ids=("m1", "s1"),
        )
        validated = validate_research_hypothesis_registry_v0(
            [convergence, social, market]
        )
        self.assertEqual([item.hypothesis_id for item in validated], ["c1", "m1", "s1"])

    def test_rejected_social_parent_blocks_convergence(self):
        market = self._closed("m1", TRACK_MARKET_FIRST, VERDICT_SUPPORTED, 100)
        social = self._closed("s1", TRACK_SOCIAL_EVENT_FIRST, VERDICT_REJECTED, 110)
        convergence = ResearchHypothesisRecordV0(
            hypothesis_id="c1",
            track=TRACK_CONVERGENCE,
            stage=STAGE_PREREGISTERED,
            frozen_at=120,
            statement="joint evidence hypothesis",
            feature_contract_sha256=H1,
            parent_hypothesis_ids=("m1", "s1"),
        )
        with self.assertRaises(ValueError):
            validate_research_hypothesis_registry_v0([market, social, convergence])

    def test_opening_outcomes_requires_frozen_outcome_contract(self):
        with self.assertRaises(ValueError):
            ResearchHypothesisRecordV0(
                hypothesis_id="m1",
                track=TRACK_MARKET_FIRST,
                stage="PROSPECTIVE_OPEN",
                frozen_at=100,
                statement="market hypothesis",
                feature_contract_sha256=H1,
                outcomes_opened=True,
            )

    def test_non_convergence_track_cannot_reference_cross_track_parents(self):
        with self.assertRaises(ValueError):
            ResearchHypothesisRecordV0(
                hypothesis_id="m2",
                track=TRACK_MARKET_FIRST,
                stage=STAGE_PREREGISTERED,
                frozen_at=100,
                statement="market revision",
                feature_contract_sha256=H1,
                parent_hypothesis_ids=("s1",),
            )

    def test_digest_is_order_independent_after_validation_sort(self):
        market = self._closed("m1", TRACK_MARKET_FIRST, VERDICT_SUPPORTED, 100)
        social = self._closed("s1", TRACK_SOCIAL_EVENT_FIRST, VERDICT_SUPPORTED, 110)
        self.assertEqual(
            research_hypothesis_registry_digest_v0([market, social]),
            research_hypothesis_registry_digest_v0([social, market]),
        )


if __name__ == "__main__":
    unittest.main()
