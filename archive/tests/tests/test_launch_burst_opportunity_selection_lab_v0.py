from __future__ import annotations

import unittest

from benchmarks.launch_burst_opportunity_lab_v0.analyze import (
    _auc_higher_in_positive,
    _feature_stat,
    _leave_one_positive_out_auc,
    _replication_across_runs,
    _single_gate_diagnostics,
)


class LaunchBurstOpportunitySelectionLabV0Tests(unittest.TestCase):
    def test_auc_detects_higher_feature_in_winners(self):
        self.assertEqual(_auc_higher_in_positive([3.0, 4.0], [1.0, 2.0]), 1.0)
        self.assertEqual(_auc_higher_in_positive([1.0, 2.0], [3.0, 4.0]), 0.0)
        self.assertEqual(_auc_higher_in_positive([1.0], [1.0]), 0.5)

    def test_leave_one_positive_out_requires_direction_stability(self):
        stable = _leave_one_positive_out_auc([8.0, 9.0, 10.0], [1.0, 2.0, 3.0, 4.0])
        self.assertTrue(stable["available"])
        self.assertTrue(stable["same_direction_all_folds"])
        fragile = _leave_one_positive_out_auc([0.0, 10.0, 11.0], [4.0, 5.0, 6.0])
        self.assertTrue(fragile["available"])
        self.assertFalse(fragile["same_direction_all_folds"])

    def test_feature_stat_never_emits_threshold_recommendation(self):
        rows = []
        for index, value in enumerate((8.0, 9.0, 10.0)):
            rows.append({"positive": True, "fixed_return_pct": 5.0 + index, "features": {"x": value}})
        for index, value in enumerate(range(1, 12)):
            rows.append({"positive": False, "fixed_return_pct": -1.0 - index, "features": {"x": float(value) / 10.0}})
        stat = _feature_stat("x", rows)
        self.assertEqual(stat["hypothesis_generation_status"], "RESEARCH_PRIORITY")
        self.assertEqual(stat["direction"], "HIGHER_IN_POSITIVE")
        self.assertIsNone(stat["threshold_recommendation"])

    def test_low_coverage_cannot_be_research_priority(self):
        rows = []
        for index in range(20):
            row = {"positive": index < 4, "fixed_return_pct": 1.0 if index < 4 else -1.0, "features": {}}
            if index < 10:
                row["features"]["x"] = float(index)
            rows.append(row)
        stat = _feature_stat("x", rows)
        self.assertEqual(stat["hypothesis_generation_status"], "INSUFFICIENT_SAMPLE_OR_COVERAGE")

    def test_single_gate_diagnostic_uses_preregistered_threshold_without_retuning(self):
        rows = [
            {"features": {"x": 10.0}, "fixed_pnl_usd": 5.0},
            {"features": {"x": 11.0}, "fixed_pnl_usd": 4.0},
            {"features": {"x": 1.0}, "fixed_pnl_usd": -5.0},
            {"features": {"x": 2.0}, "fixed_pnl_usd": -4.0},
        ]
        policy = {"primary_selector": {"predicates": [{"feature": "x", "op": ">=", "value": 5.0}]}}
        diagnostics = _single_gate_diagnostics(rows=rows, policy=policy, notional=25.0)
        self.assertEqual(len(diagnostics), 1)
        item = diagnostics[0]
        self.assertEqual(item["threshold"], 5.0)
        self.assertEqual(item["threshold_origin"], "PREREGISTERED_SNIPER_V1_BEFORE_SCREENING_OUTCOMES")
        self.assertTrue(item["aligned_with_original_gate_intent"])
        self.assertFalse(item["retuning_permitted_from_this_sample"])

    def test_cross_run_priority_requires_same_direction_and_robustness(self):
        def feature(auc, direction):
            return {
                "feature": "x",
                "auc_probability_higher_value_in_positive": auc,
                "direction": direction,
                "auc_separation_strength_0_to_1": 2.0 * abs(auc - 0.5),
                "leave_one_positive_out": {"same_direction_all_folds": True},
            }
        reports = [
            {"feature_separation": [feature(0.75, "HIGHER_IN_POSITIVE")]},
            {"feature_separation": [feature(0.70, "HIGHER_IN_POSITIVE")]},
        ]
        replicated = _replication_across_runs(reports)
        self.assertEqual(replicated[0]["cross_run_hypothesis_priority"], "REPLICATED_DIRECTION_PRIORITY")
        self.assertIsNone(replicated[0]["threshold_recommendation"])

    def test_cross_run_conflicting_direction_is_not_priority(self):
        reports = [
            {"feature_separation": [{
                "feature": "x", "auc_probability_higher_value_in_positive": 0.75,
                "direction": "HIGHER_IN_POSITIVE", "auc_separation_strength_0_to_1": 0.5,
                "leave_one_positive_out": {"same_direction_all_folds": True},
            }]},
            {"feature_separation": [{
                "feature": "x", "auc_probability_higher_value_in_positive": 0.25,
                "direction": "LOWER_IN_POSITIVE", "auc_separation_strength_0_to_1": 0.5,
                "leave_one_positive_out": {"same_direction_all_folds": True},
            }]},
        ]
        replicated = _replication_across_runs(reports)
        self.assertEqual(replicated[0]["cross_run_hypothesis_priority"], "NO_REPLICATED_PRIORITY")


if __name__ == "__main__":
    unittest.main()
