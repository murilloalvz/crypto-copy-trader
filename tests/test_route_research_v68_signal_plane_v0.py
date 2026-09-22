from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0 as sp_v68


class V68SignalPlaneProspectiveV0Tests(unittest.TestCase):
    def test_strict_freshness_rejects_any_existing_run_key_residue(self):
        with patch.object(
            sp_v68.promotion,
            "validate_promotion_report",
            return_value=(True, "ok"),
        ), patch.object(
            sp_v68,
            "_strict_run_keys_fresh",
            return_value=(False, "base-A:some_table:1"),
        ):
            report = sp_v68.run_signal_plane_v68_v0(
                base_run_key="base",
                bootstrap_report=Path("bootstrap.json"),
                promotion_report=Path("promotion.json"),
                acquisition_duration_seconds=1,
            )
        self.assertEqual(
            report["classification"],
            "FAIL_V68_SIGNAL_PLANE_RUN_KEY_NOT_FRESH",
        )

    def test_failed_subcohort_stops_before_economic_dataset(self):
        failed = SimpleNamespace(
            run_key="base-A",
            bridge_classification="FAIL",
            decision_count=0,
            scheduled_count=0,
            exact_three_horizons_per_decision=False,
            forward_classification="FAIL",
            target_lateness_p95_seconds=None,
            lineage_violations=0,
            descriptive_ready_horizons=0,
            passed=False,
        )
        with patch.object(
            sp_v68.promotion,
            "validate_promotion_report",
            return_value=(True, "ok"),
        ), patch.object(
            sp_v68,
            "_strict_run_keys_fresh",
            return_value=(True, "none"),
        ), patch.object(
            sp_v68,
            "run_signal_plane_forward_cohort_v0",
            return_value=failed,
        ), patch.object(
            sp_v68,
            "build_early_opportunity_dataset_v55",
            side_effect=AssertionError("economic dataset must not run"),
        ):
            report = sp_v68.run_signal_plane_v68_v0(
                base_run_key="base",
                bootstrap_report=Path("bootstrap.json"),
                promotion_report=Path("promotion.json"),
                acquisition_duration_seconds=1,
            )
        self.assertEqual(
            report["classification"],
            "FAIL_V68_SIGNAL_PLANE_SUBCOHORT",
        )

    def test_frozen_primary_gate_is_used_without_threshold_recalculation(self):
        passed_a = SimpleNamespace(
            run_key="base-A",
            bridge_classification="PASS",
            decision_count=40,
            scheduled_count=120,
            exact_three_horizons_per_decision=True,
            forward_classification="PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE",
            target_lateness_p95_seconds=1,
            lineage_violations=0,
            descriptive_ready_horizons=3,
            passed=True,
        )
        passed_b = SimpleNamespace(**{**passed_a.__dict__, "run_key": "base-B"})
        rows = [
            SimpleNamespace(cohort="A"),
            SimpleNamespace(cohort="B"),
        ] * sp_v68.V55_MIN_ROWS_PER_SUBCOHORT
        base = SimpleNamespace(
            lineage_violations=0,
            missing_decisions=0,
            missing_episodes=0,
            missing_hazard_attempts=0,
            missing_entry_quotes=0,
            official_decision_mutations=0,
        )
        dataset = SimpleNamespace(
            rows=rows,
            base=base,
            augmentation_failures=0,
            feature_clock_violations=0,
        )
        gate = SimpleNamespace(
            classification=(
                "PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS"
            ),
            feature_known=len(rows),
            feature_total=len(rows),
            feature_coverage_pct=100.0,
            support_ok=True,
            same_direction_ok=True,
            favorable_positive_median_both=True,
            favorable_pf_gt_one_both=True,
            aggregate_favorable_pf_gt_one=True,
            aggregate_favorable_mean_without_best_positive=True,
        )

        with patch.object(
            sp_v68.promotion,
            "validate_promotion_report",
            return_value=(True, "ok"),
        ), patch.object(
            sp_v68,
            "_strict_run_keys_fresh",
            return_value=(True, "none"),
        ), patch.object(
            sp_v68,
            "run_signal_plane_forward_cohort_v0",
            side_effect=[passed_a, passed_b],
        ), patch.object(
            sp_v68,
            "build_early_opportunity_dataset_v55",
            return_value=dataset,
        ), patch.object(
            sp_v68,
            "primary_gate_v68",
            return_value=gate,
        ) as primary_gate:
            report = sp_v68.run_signal_plane_v68_v0(
                base_run_key="base",
                bootstrap_report=Path("bootstrap.json"),
                promotion_report=Path("promotion.json"),
                acquisition_duration_seconds=1,
            )

        self.assertEqual(report["classification"], gate.classification)
        self.assertFalse(report["scientific_thresholds_modified"])
        self.assertFalse(report["economic_hypothesis_modified"])
        self.assertEqual(
            report["economic_contract"]["feature"],
            sp_v68.legacy_v68.V68_FEATURE_NAME,
        )
        self.assertEqual(
            report["economic_contract"]["low_max"],
            sp_v68.legacy_v68.V68_LOW_MAX,
        )
        self.assertEqual(
            report["economic_contract"]["mid_max"],
            sp_v68.legacy_v68.V68_MID_MAX,
        )
        primary_gate.assert_called_once_with(rows=rows)


if __name__ == "__main__":
    unittest.main()
