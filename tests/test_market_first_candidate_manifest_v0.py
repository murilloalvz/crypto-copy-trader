from __future__ import annotations

import unittest

from benchmarks.launch_burst_opportunity_lab_v0.candidate_manifest import build_candidate_manifest


class MarketFirstCandidateManifestV0Tests(unittest.TestCase):
    def _base_report(self) -> dict:
        return {
            "type": "launch_burst_opportunity_selection_lab_report",
            "version": "launch_burst_opportunity_selection_lab_v0",
            "classification": "PASS_LAUNCH_BURST_OPPORTUNITY_SELECTION_LAB_V0",
            "inference_role": "OFFLINE_HYPOTHESIS_GENERATION_ONLY",
            "run_count": 2,
            "replicated_direction_priority_features": [],
            "next_protocol_constraints": {
                "do_not_change_frozen_momentum_v0": True,
                "do_not_select_new_thresholds_from_these_outcomes": True,
                "candidate_features_must_be_preregistered_before_future_validation": True,
            },
        }

    def _candidate(self, feature: str = "flow.unique_buyers") -> dict:
        return {
            "feature": feature,
            "run_count": 2,
            "directions": ["HIGHER_IN_POSITIVE", "HIGHER_IN_POSITIVE"],
            "same_direction_across_runs": True,
            "min_auc_separation_strength": 0.22,
            "max_auc_separation_strength": 0.41,
            "leave_one_positive_out_direction_stable_in_every_run": True,
            "cross_run_hypothesis_priority": "REPLICATED_DIRECTION_PRIORITY",
            "threshold_recommendation": None,
        }

    def test_builds_direction_only_candidates_without_runtime_policy(self) -> None:
        report = self._base_report()
        report["replicated_direction_priority_features"] = [
            self._candidate("z_feature"),
            self._candidate("a_feature"),
        ]

        manifest = build_candidate_manifest(report=report, source_report_sha256="abc")

        self.assertEqual(manifest["classification"], "PASS_MARKET_FIRST_CANDIDATE_MANIFEST_V0")
        self.assertEqual(manifest["status"], "CANDIDATES_AVAILABLE_FOR_PREREGISTRATION_DESIGN")
        self.assertEqual([row["feature"] for row in manifest["candidates"]], ["a_feature", "z_feature"])
        for row in manifest["candidates"]:
            self.assertIsNone(row["threshold"])
            self.assertIsNone(row["weight"])
            self.assertFalse(row["runtime_selector_eligible"])
            self.assertTrue(row["requires_independent_future_validation"])
        self.assertEqual(manifest["ordering"], "ALPHABETICAL_NOT_ECONOMIC_RANKING")
        self.assertFalse(manifest["protocol"]["same_sample_threshold_search_permitted"])
        self.assertFalse(manifest["protocol"]["runtime_selector_creation_permitted"])
        self.assertEqual(manifest["source"]["report_sha256"], "abc")
        self.assertEqual(len(manifest["manifest_hash_sha256"]), 64)

    def test_rejects_same_sample_threshold_recommendation(self) -> None:
        report = self._base_report()
        candidate = self._candidate()
        candidate["threshold_recommendation"] = 42.0
        report["replicated_direction_priority_features"] = [candidate]

        with self.assertRaisesRegex(ValueError, "threshold recommendation is forbidden"):
            build_candidate_manifest(report=report)

    def test_rejects_non_hypothesis_generation_source(self) -> None:
        report = self._base_report()
        report["inference_role"] = "VALIDATION"

        with self.assertRaisesRegex(ValueError, "hypothesis-generation-only"):
            build_candidate_manifest(report=report)

    def test_no_replicated_candidates_is_a_valid_non_edge_result(self) -> None:
        manifest = build_candidate_manifest(report=self._base_report())

        self.assertEqual(manifest["candidate_count"], 0)
        self.assertEqual(manifest["status"], "NO_REPLICATED_DIRECTION_CANDIDATES_YET")
        self.assertEqual(manifest["candidates"], [])

    def test_rejects_direction_instability(self) -> None:
        report = self._base_report()
        candidate = self._candidate()
        candidate["directions"] = ["HIGHER_IN_POSITIVE", "LOWER_IN_POSITIVE"]
        report["replicated_direction_priority_features"] = [candidate]

        with self.assertRaisesRegex(ValueError, "one replicated non-zero direction"):
            build_candidate_manifest(report=report)


if __name__ == "__main__":
    unittest.main()
