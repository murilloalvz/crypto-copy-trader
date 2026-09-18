from __future__ import annotations

import unittest

from benchmarks.early_buyer_prior_quality_replication_v0.run import (
    DEFAULT_PROTOCOL,
    FEATURE_ID,
    _decision,
    _read_json,
    _validate_protocol,
)


class EarlyBuyerPriorQualityReplicationV0Tests(unittest.TestCase):
    def test_protocol_hash_and_mature_history_contract_are_frozen(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        _validate_protocol(protocol)
        self.assertEqual(
            protocol["protocol_hash_sha256"],
            "655f6cd2c0ba1bad14bc6caa21e7f45fb644edc803f099dc4ce00c210088f796",
        )
        self.assertEqual(protocol["hypothesis"]["feature_id"], FEATURE_ID)
        self.assertIsNone(
            protocol["mature_history_contract"]["numeric_history_support_threshold"]
        )
        self.assertFalse(
            protocol["mature_history_contract"]["support_threshold_search_permitted"]
        )
        self.assertEqual(
            len(protocol["mature_history_contract"]["frozen_history_run_ids"]),
            4,
        )

    def test_preregistered_keep_requires_direction_robustness_incremental_value_and_median(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        decision, reasons, checks = _decision(
            protocol=protocol,
            primary={
                "usable_pair_count": 40,
                "spearman": 0.25,
                "spearman_without_best_trade": 0.22,
                "leave_one_out_sign_consistency_fraction": 1.0,
                "lower_or_equal_feature_half": {"median_outcome_pct": -20.0},
                "higher_feature_half": {"median_outcome_pct": -5.0},
            },
            incremental={
                "usable_pair_count": 40,
                "partial_spearman": 0.15,
            },
        )
        self.assertEqual(decision, "KEEP")
        self.assertEqual(
            reasons,
            ["all_preregistered_fresh_confirmation_keep_conditions_passed"],
        )
        self.assertTrue(checks["minimum_sample_met"])
        self.assertTrue(checks["higher_half_median_gross_gt_lower_half"])

    def test_preregistered_kill_requires_consistent_negative_confirmation(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        decision, reasons, checks = _decision(
            protocol=protocol,
            primary={
                "usable_pair_count": 40,
                "spearman": -0.25,
                "spearman_without_best_trade": -0.20,
                "leave_one_out_sign_consistency_fraction": 1.0,
                "lower_or_equal_feature_half": {"median_outcome_pct": -5.0},
                "higher_feature_half": {"median_outcome_pct": -20.0},
            },
            incremental={
                "usable_pair_count": 40,
                "partial_spearman": -0.12,
            },
        )
        self.assertEqual(decision, "KILL")
        self.assertEqual(
            reasons,
            ["all_preregistered_fresh_confirmation_kill_conditions_passed"],
        )
        self.assertTrue(checks["spearman_nonpositive"])
        self.assertTrue(checks["higher_half_median_gross_lte_lower_half"])

    def test_below_minimum_sample_is_iterate_without_retuning(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        decision, reasons, checks = _decision(
            protocol=protocol,
            primary={
                "usable_pair_count": 20,
                "spearman": 0.40,
                "spearman_without_best_trade": 0.35,
                "leave_one_out_sign_consistency_fraction": 1.0,
                "lower_or_equal_feature_half": {"median_outcome_pct": -20.0},
                "higher_feature_half": {"median_outcome_pct": 5.0},
            },
            incremental={"partial_spearman": 0.30},
        )
        self.assertEqual(decision, "ITERATE")
        self.assertIn(
            "fresh_primary_pair_count_below_preregistered_minimum",
            reasons,
        )
        self.assertFalse(checks["minimum_sample_met"])


if __name__ == "__main__":
    unittest.main()
